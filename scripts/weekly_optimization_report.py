# -*- coding: utf-8 -*-
"""周度优化报告推送脚本。

每周日收盘后自动运行，生成Agent自主优化报告并推送到飞书。
包含：本周策略表现、优化建议、已自动应用的参数调整。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.weekly_optimizer import generate_weekly_report


def send_feishu(text: str):
    """推送到飞书。"""
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL")
        print(text)
        return
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        print(f"✅ 飞书推送完成 HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


def main():
    print("=" * 50)
    print("🔄 生成周度策略优化报告")
    print("=" * 50)

    report = generate_weekly_report()
    print(report)
    print()

    send_feishu(report)
    print("✅ 周度优化报告完成")


if __name__ == "__main__":
    main()
