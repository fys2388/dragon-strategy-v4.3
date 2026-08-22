# -*- coding: utf-8 -*-
"""V1.0 策略推送入口（重写）。

调用 MACD 多周期共振策略扫描器，推送飞书。
兼容工作流调用：python scripts/v43_push.py
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime

# 允许直接运行脚本时导入 strategies 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.scanner import Scanner, build_message  # noqa: E402
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


def main():
    now = now_bjt()
    test_mode = os.environ.get("TEST_MODE", "").lower() == "true"
    print(f"[交易时段检查] 北京时间={now.strftime('%Y-%m-%d %H:%M:%S')} "
          f"weekday={now.weekday()} is_trading={is_trading_time(now)} "
          f"should_run={should_run(now)} test_mode={test_mode}")
    if not test_mode and not should_run(now):
        print(f"📌 非交易时段 {now.strftime('%Y-%m-%d %H:%M')}，退出")
        return

    scanner = Scanner()
    # 硬超时看门狗：数据源在云端异常挂起时，强制结束扫描，避免阻塞 5 分钟节奏
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
    print(msg)
    print("\n[SUMMARY]", result["summary"])

    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL，跳过推送")
        return
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": msg}}, timeout=8)
        print(f"✅ 飞书推送完成，HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


if __name__ == "__main__":
    main()
