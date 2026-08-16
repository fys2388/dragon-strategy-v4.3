# -*- coding: utf-8 -*-
"""V1.0 策略推送入口（重写）。

调用 MACD 多周期共振策略扫描器，推送飞书。
兼容工作流调用：python scripts/v43_push.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

# 允许直接运行脚本时导入 strategies 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.scanner import Scanner, build_message  # noqa: E402


def is_trading_time(now: datetime) -> bool:
    """交易时段判断（周一至周五 9:15-15:00，跳过 11:30-13:00）。"""
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    if hm < 915 or hm > 1500:
        return False
    if 1130 <= hm <= 1259:
        return False
    return True


def main():
    now = datetime.now()
    test_mode = os.environ.get("TEST_MODE", "").lower() == "true"
    if not test_mode and not is_trading_time(now):
        print(f"📌 非交易时段 {now.strftime('%Y-%m-%d %H:%M')}，退出")
        return

    scanner = Scanner()
    result = scanner.run(need_push=True)
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
