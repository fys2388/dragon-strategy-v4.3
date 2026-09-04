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
from strategies.macd_resonance.breakout import BreakoutScanner, build_breakout_message  # noqa: E402
from strategies.macd_resonance.health_monitor import init_health_monitor  # noqa: E402
from strategies.macd_resonance.ai_scorer import init_ai_scorer  # noqa: E402
from strategies.macd_resonance.market_cluster import init_market_cluster  # noqa: E402
from strategies.macd_resonance import data_source as ds  # noqa: E402
from strategies.macd_resonance.multi_dimension_filter import init_multi_filter  # noqa: E402
from strategies.macd_resonance.sector_strength import get_strong_sectors, build_sector_report  # noqa: E402
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


def ai_filter_entries(entries: list, strategy_type: str = "") -> list:
    """用AI模型过滤候选股票，只保留上涨概率>55%的。
    AI模型不可用时自动降级为原始推荐，不中断运行。
    """
    if not entries:
        return entries
    try:
        scorer = init_ai_scorer(min_probability=0.55)
        scored = scorer.score_candidates(entries, strategy_type)
        return scored
    except Exception as e:
        print(f"⚠️ AI打分失败，保留原始推荐: {e}")
        return entries


def add_multi_dimension_detail(entries: list) -> str:
    """给推荐股票添加多维详情（资金面/基本面/消息面）。"""
    if not entries:
        return ""
    try:
        mfilter = init_multi_filter()
        details = []
        for e in entries:
            code = e.get("code", "")
            name = e.get("name", "")
            if code:
                detail = mfilter.build_stock_detail(code, name)
                if detail:
                    details.append(f"\n  【{name}({code})多维分析】\n{detail}")
        return "\n".join(details)
    except Exception as e:
        print(f"⚠️ 多维详情生成失败: {e}")
        return ""


def get_market_cluster_info() -> dict:
    """获取当前市场聚类状态和策略建议。"""
    try:
        cluster = init_market_cluster()
        index_df = ds.get_kline_daily("000001", count=60)
        if index_df.empty:
            return {}
        # 用默认涨跌停数据（聚类主要看指数走势，涨跌停是辅助）
        result = cluster.predict(index_df, limit_up_count=50, limit_down_count=0, total_volume_yi=10000)
        params = cluster.get_strategy_params(result["cluster_name"])
        result["strategy_params"] = params
        return result
    except Exception as e:
        print(f"⚠️ 市场聚类获取失败: {e}")
        return {}


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

    # 健康度监控：检查连续0推荐，自动降级
    health = init_health_monitor()
    param_override = health.get_current_params_override()
    if param_override["level"] > 0:
        print(f"⚠️ 系统处于降级状态 Level {param_override['level']}：{param_override['general'].get('note', '')}")

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
    # AI打分过滤：只保留上涨概率>55%的候选
    result["entries"] = ai_filter_entries(result.get("entries", []), "resonance")
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
    # 多维详情
    if resonance_entries:
        multi_detail = add_multi_dimension_detail(resonance_entries)
        if multi_detail:
            msg = msg + "\n" + multi_detail
    print(msg)
    print("\n[SUMMARY]", result["summary"])

    # 收集所有策略消息，最后合并推送（避免三条消息轰炸）
    all_messages = [msg]

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

        # AI打分过滤
        oversold_result["entries"] = ai_filter_entries(oversold_result.get("entries", []), "oversold")
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
        # 多维详情
        if oversold_entries:
            multi_detail = add_multi_dimension_detail(oversold_entries)
            if multi_detail:
                oversold_msg = oversold_msg + "\n" + multi_detail
        print(oversold_msg)
        print("\n[OVERSOLD SUMMARY]", oversold_result.get("summary", ""))
        all_messages.append(oversold_msg)

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

    breakout_result = {"entries": []}  # 初始化，防止异常时未定义
    # ===== 趋势突破模式（第三策略，震荡市补充）=====
    try:
        print("\n" + "=" * 50)
        print("🚀 开始趋势突破模式扫描...")
        breakout_scanner = BreakoutScanner()
        breakout_box: dict = {}

        def _breakout_scan():
            breakout_box["r"] = breakout_scanner.run(need_push=True, max_stocks=SCAN_MAX_STOCKS)

        t3 = threading.Thread(target=_breakout_scan, daemon=True)
        t3.start()
        t3.join(timeout=SCAN_TIMEOUT_S)
        if t3.is_alive():
            print(f"⏰ 趋势突破扫描超过 {SCAN_TIMEOUT_S}s 超时")
            breakout_result = {"summary": "趋势突破扫描超时", "diagnosis": "", "scan_elapsed": 0, "entries": []}
        else:
            breakout_result = breakout_box.get("r", {"summary": "趋势突破扫描无结果"})

        # AI打分过滤
        breakout_result["entries"] = ai_filter_entries(breakout_result.get("entries", []), "breakout")
        breakout_msg = build_breakout_message(breakout_result)
        # 智能分析
        breakout_entries = breakout_result.get("entries", [])
        if breakout_entries:
            try:
                analyzer = StockAnalyzer()
                analyzed = analyzer.analyze_batch(breakout_entries)
                analysis_msg = build_analysis_message(analyzed)
                if analysis_msg:
                    breakout_msg = breakout_msg + analysis_msg
            except Exception as e:
                print(f"⚠️ 趋势突破智能分析失败: {e}")
        # 多维详情
        if breakout_entries:
            multi_detail = add_multi_dimension_detail(breakout_entries)
            if multi_detail:
                breakout_msg = breakout_msg + "\n" + multi_detail
        print(breakout_msg)
        print("\n[BREAKOUT SUMMARY]", breakout_result.get("summary", ""))
        all_messages.append(breakout_msg)

        # 记录趋势突破推荐股
        if breakout_entries:
            breakout_time = breakout_result.get("scan_time", now_bjt().strftime("%Y-%m-%d %H:%M:%S"))
            breakout_regime = breakout_result.get("regime", "unknown")
            record_recommendations(breakout_entries, "breakout", breakout_time, breakout_regime)
    except Exception as e:
        print(f"❌ 趋势突破扫描异常: {e}")
        try:
            send_feishu_alert(f"趋势突破模式异常: {e}", "策略异常")
        except Exception:
            pass

    # 统计今日总推荐数
    total_recommendations = (
        len(result.get("entries", [])) +
        len(oversold_result.get("entries", [])) +
        len(breakout_result.get("entries", []))
    )

    # 健康度监控：记录今日推荐数
    health.record_recommendations(total_recommendations)
    if total_recommendations == 0:
        print(f"⚠️ 今日0推荐，连续0推荐天数：{health.state['consecutive_zero_days']}天")
        if health.state["degradation_level"] > 0:
            print(f"   当前降级等级：Level {health.state['degradation_level']}")
    else:
        print(f"✅ 今日推荐{total_recommendations}只，系统状态正常")

    # 获取强势板块
    sector_report = ""
    try:
        strong_sectors = get_strong_sectors(top_n=5)
        if strong_sectors:
            sector_report = build_sector_report(strong_sectors) + "\n\n"
    except Exception as e:
        print(f"⚠️ 板块强度获取失败: {e}")

    # 获取市场聚类状态
    cluster_info = get_market_cluster_info()
    cluster_header = ""
    if cluster_info:
        params = cluster_info.get("strategy_params", {})
        cluster_header = (
            f"🧠 AI市场状态：{cluster_info.get('cluster_name_cn', '未知')}"
            f"（{cluster_info.get('cluster_name', '')}）\n"
            f"📌 {params.get('recommendation', '')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

    # 合并所有策略消息为一条推送
    combined_msg = cluster_header + sector_report + "\n\n".join(all_messages)
    _send_text(combined_msg)
    print(f"\n📨 合并推送完成，共{len(all_messages)}个策略模块，市场状态={cluster_info.get('cluster_name_cn', '未知')}")

    # 打印健康度报告
    print("\n" + health.get_health_report())

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
