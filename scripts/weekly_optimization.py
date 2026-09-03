# -*- coding: utf-8 -*-
"""每周策略回测与参数优化脚本。

每周日运行，基于历史跟踪数据自动优化策略参数。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.backtest import run_weekly_optimization, build_optimization_report  # noqa: E402


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
    result = run_weekly_optimization()
    report = build_optimization_report(result)
    print("\n" + report)

    # 推送飞书
    if os.environ.get("PUSH_FEISHU", "true").lower() == "true":
        send_feishu(report)


if __name__ == "__main__":
    main()
