# -*- coding: utf-8 -*-
"""每日持仓监控脚本。

每天盘中运行，监控持仓的止损止盈，触发预警时推送飞书。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.position_monitor import init_position_monitor


def send_feishu(text: str):
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL")
        return
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
        print(f"✅ 飞书推送完成 HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


def main():
    print("=" * 50)
    print("💼 每日持仓监控")
    print("=" * 50)

    monitor = init_position_monitor()
    result = monitor.monitor()

    # 生成消息
    msg = monitor.build_monitor_message(result)
    print(msg)

    # 有预警时才推送（或配置为每次都推送）
    alerts = result.get("alerts", [])
    push_all = os.environ.get("PUSH_ALL_POSITIONS", "true").lower() == "true"

    if alerts or push_all:
        send_feishu(msg)
        if alerts:
            print(f"\n⚠️ 触发{len(alerts)}条预警，已推送")
        else:
            print("\n✅ 无预警，常规报告已推送")
    else:
        print("\n✅ 无预警，不推送")

    # 输出预警详情
    if alerts:
        print("\n" + "=" * 50)
        print("预警详情：")
        for alert in alerts:
            print(f"  [{alert['level']}] {alert['message']}")


if __name__ == "__main__":
    main()
