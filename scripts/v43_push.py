# -*- coding: utf-8 -*-
"""V1.0 策略推送入口（重写）。

调用 MACD 多周期共振策略扫描器，推送飞书。
兼容工作流调用：python scripts/v43_push.py

报告类型由 REPORT_MODE 环境变量决定：
- "premarket"：推送盘前报告（9:15 档），不扫描
- "scan"    ：执行扫描并推送盘中实时报告
- 未设置     ：按当前北京时间自动选择（9:15-9:30 窗口 → 盘前报告，其余交易时段 → 扫描）
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime

# 允许直接运行脚本时导入 strategies 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.scanner import Scanner, build_message  # noqa: E402
from strategies.macd_resonance.oversold_rebound import OversoldReboundScanner, build_oversold_message  # noqa: E402
from strategies.macd_resonance.tracking import record_recommendations, update_performance  # noqa: E402
from strategies.macd_resonance.llm_analyzer import StockAnalyzer, build_analysis_message  # noqa: E402
from strategies.macd_resonance.trading_calendar import is_trading_time, now_bjt  # noqa: E402

SCAN_TIMEOUT_S = 480  # 扫描硬超时（秒）：数据源异常挂起时兜底
SCAN_MAX_STOCKS = 1200  # 定时扫描标的池规模（按成交额降序，活跃标的；控制 5 分钟节奏内的耗时）


def send_feishu_alert(text: str, title: str = "策略告警"):
    """推送飞书告警（复用扫描器的 webhook 逻辑）。"""
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        return
    import requests
    requests.post(webhook, json={"msg_type": "text", "content": {"text": f"【{title}】{text}"}}, timeout=8)


def should_run(now: datetime) -> bool:
    """运行窗口：盘前 9:15-9:30 + 交易时段 9:30-11:30/13:00-15:00。"""
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    if 915 <= hm < 930:  # 盘前窗口（含 9:15 盘前推送）
        return True
    return is_trading_time(now)


def _send_text(msg: str) -> bool:
    """推送纯文本到飞书。"""
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL，跳过推送")
        return False
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": msg}}, timeout=8)
        print(f"✅ 飞书推送完成，HTTP {resp.status_code}")
        return True
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")
        return False


def push_premarket_report() -> None:
    """盘前报告：复用 morning_noon_push 的生成逻辑（大盘概况+昨日推荐+持仓提醒）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/ 目录
    from morning_noon_push import build_premarket_report  # noqa: E402
    msg = build_premarket_report()
    print(msg)
    print()
    _send_text(msg)


def resolve_report_mode(now: datetime) -> str:
    """由环境变量/时间决定报告类型：premarket | scan | skip。

    REPORT_MODE 由工作流按触发档位显式传入（9:15 档 → premarket，盘中档 → scan），
    不依赖当前时间，GitHub 调度延迟也不会把 9:15 档误判为盘中扫描。
    """
    mode = os.environ.get("REPORT_MODE", "").strip().lower()
    if mode == "premarket":
        # 守卫（仅定时触发时生效）：9:15 档若被 GitHub 延迟到 9:45 之后才运行，
        # 跳过推送，避免迟到盘前报告与盘中实时报告撞车（用户投诉的场景）。
        # 手动触发（TRIGGER=workflow_dispatch）不受守卫限制，可随时验证/兜底。
        trigger = os.environ.get("TRIGGER", "").strip()
        hm = now.hour * 100 + now.minute
        if trigger == "schedule" and hm >= 945:
            print(f"⏰ 盘前档被延迟到 {now.strftime('%H:%M')}，已过盘前窗口，跳过（避免与盘中重复）")
            return "skip"
        return "premarket"
    if mode == "scan":
        return "scan"
    # 手动触发（REPORT_MODE 为空）：按当前时间自动选择
    if now.weekday() >= 5:
        return "skip"
    hm = now.hour * 100 + now.minute
    if 915 <= hm < 930:
        return "premarket"
    return "scan" if is_trading_time(now) else "skip"


def main():
    now = now_bjt()
    test_mode = os.environ.get("TEST_MODE", "").lower() == "true"
    report_mode = resolve_report_mode(now)
    print(f"[交易时段检查] 北京时间={now.strftime('%Y-%m-%d %H:%M:%S')} "
          f"weekday={now.weekday()} is_trading={is_trading_time(now)} "
          f"should_run={should_run(now)} test_mode={test_mode} report_mode={report_mode}")

    if test_mode:
        report_mode = "scan"  # 测试模式始终执行扫描（供手动验证数据源/推送链路）
    if report_mode == "skip":
        print(f"📌 非交易时段 {now.strftime('%Y-%m-%d %H:%M')}，退出")
        return
    if report_mode == "premarket":
        push_premarket_report()
        return

    scanner = Scanner()
    # 硬超时看门狗：数据源在云端异常挂起时，强制结束扫描，避免阻塞节奏
    result_box: dict = {}

    def _scan():
        result_box["r"] = scanner.run(need_push=True, max_stocks=SCAN_MAX_STOCKS)

    t = threading.Thread(target=_scan, daemon=True)
    t.start()
    t.join(timeout=SCAN_TIMEOUT_S)
    if t.is_alive():
        print(f"⏰ 扫描超过 {SCAN_TIMEOUT_S}s 超时，强制结束（数据源可能异常）")
        result = {"summary": f"扫描超时（>{SCAN_TIMEOUT_S}s），已中断"}
        try:
            send_feishu_alert(f"扫描超时（>{SCAN_TIMEOUT_S}s），数据源可能异常。", "扫描超时")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ 超时告警推送失败: {e}")
    else:
        result = result_box.get("r", {"summary": "扫描无结果"})
    msg = build_message(result)
    # 智能分析（如果有推荐股票）
    resonance_entries = result.get("entries", [])
    if resonance_entries:
        try:
            analyzer = StockAnalyzer()
            analyzed = analyzer.analyze_batch(resonance_entries)
            analysis_msg = build_analysis_message(analyzed)
            if analysis_msg:
                msg = msg + analysis_msg
        except Exception as e:
            print(f"⚠️ 智能分析失败: {e}")
    print(msg)
    print("\n[SUMMARY]", result["summary"])

    _send_text(msg)

    # 记录MACD共振推荐股到绩效跟踪
    scan_time = result.get("scan_time", now_bjt().strftime("%Y-%m-%d %H:%M:%S"))
    resonance_entries = result.get("entries", [])
    if resonance_entries:
        regime = result.get("regime", "unknown")
        record_recommendations(resonance_entries, "resonance", scan_time, regime)

    # ===== 超跌反弹模式（并行第二策略）=====
    try:
        print("\n" + "=" * 50)
        print("🚀 开始超跌反弹模式扫描...")
        oversold_scanner = OversoldReboundScanner()
        oversold_box: dict = {}

        def _oversold_scan():
            oversold_box["r"] = oversold_scanner.run(need_push=True, max_stocks=SCAN_MAX_STOCKS)

        t2 = threading.Thread(target=_oversold_scan, daemon=True)
        t2.start()
        t2.join(timeout=SCAN_TIMEOUT_S)
        if t2.is_alive():
            print(f"⏰ 超跌反弹扫描超过 {SCAN_TIMEOUT_S}s 超时")
            oversold_result = {"summary": "超跌反弹扫描超时", "diagnosis": "", "scan_elapsed": 0, "entries": []}
        else:
            oversold_result = oversold_box.get("r", {"summary": "超跌反弹扫描无结果"})

        oversold_msg = build_oversold_message(oversold_result)
        # 智能分析（如果有推荐股票）
        oversold_entries = oversold_result.get("entries", [])
        if oversold_entries:
            try:
                analyzer = StockAnalyzer()
                analyzed = analyzer.analyze_batch(oversold_entries)
                analysis_msg = build_analysis_message(analyzed)
                if analysis_msg:
                    oversold_msg = oversold_msg + analysis_msg
            except Exception as e:
                print(f"⚠️ 超跌反弹智能分析失败: {e}")
        print(oversold_msg)
        print("\n[OVERSOLD SUMMARY]", oversold_result.get("summary", ""))
        _send_text(oversold_msg)

        # 记录超跌反弹推荐股到绩效跟踪
        oversold_entries = oversold_result.get("entries", [])
        if oversold_entries:
            oversold_time = oversold_result.get("scan_time", now_bjt().strftime("%Y-%m-%d %H:%M:%S"))
            oversold_regime = oversold_result.get("regime", "unknown")
            record_recommendations(oversold_entries, "oversold", oversold_time, oversold_regime)
    except Exception as e:
        print(f"❌ 超跌反弹扫描异常: {e}")
        try:
            send_feishu_alert(f"超跌反弹模式异常: {e}", "策略异常")
        except Exception:
            pass

    # 更新所有跟踪股票的表现（每天最后一次扫描时执行）
    try:
        now = now_bjt()
        # 下午14:30之后的扫描执行表现更新（一天一次足够）
        if now.hour >= 14 and now.minute >= 30:
            print("\n" + "=" * 50)
            print("📊 更新选股绩效跟踪...")
            stats = update_performance()
            print(f"[跟踪] 总计{stats['total']}只，更新{stats['updated']}只，完成{stats['completed']}只")
    except Exception as e:
        print(f"⚠️ 绩效跟踪更新失败: {e}")


if __name__ == "__main__":
    main()
