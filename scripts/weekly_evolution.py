# -*- coding: utf-8 -*-
"""每周策略进化脚本（第4层闭环迭代）。

每周日运行，自动评估策略表现、进化参数、优化权重。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.evolution_engine import run_weekly_evolution  # noqa: E402


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
    result = run_weekly_evolution()
    report = result["report"]

    # 推送飞书
    if os.environ.get("PUSH_FEISHU", "true").lower() == "true":
        send_feishu(report)


if __name__ == "__main__":
    main()
