# -*- coding: utf-8 -*-
"""每日选股绩效更新脚本。

在收盘后运行，更新所有跟踪中股票的后续表现。
可由 GitHub Actions 或 Cloudflare Worker 调度。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.tracking import update_performance, get_performance_summary, build_performance_message  # noqa: E402


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
    print("📊 开始更新选股绩效跟踪...")
    print("=" * 50)

    # 更新表现
    stats = update_performance()
    print(f"\n更新统计：总计{stats['total']}只，更新{stats['updated']}只，完成{stats['completed']}只，跟踪中{stats['tracking']}只")

    # 生成汇总
    summary = get_performance_summary()
    msg = build_performance_message(summary)
    print("\n" + msg)

    # 推送飞书（可选，通过环境变量控制）
    if os.environ.get("PUSH_FEISHU", "").lower() == "true":
        send_feishu(msg)

    return summary


if __name__ == "__main__":
    main()
