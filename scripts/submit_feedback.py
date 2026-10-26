# -*- coding: utf-8 -*-
"""用户反馈录入脚本（workflow_dispatch 入口）。

此前 `user_feedback.record_feedback()` 全仓库 0 调用方，反馈数据恒为 0 条，
周度优化的"用户反馈"部分永远只能输出「暂无用户反馈」。
本脚本把反馈接入 workflow_dispatch：在 GitHub Actions UI 填好输入后触发
`.github/workflows/user_feedback.yml`，反馈会写入 data/user_feedback.jsonl
并随回传步骤提交进仓库（strategy_cloud_deploy.yml 的回传清单已含该文件）。

用法（本地调试）：
    python scripts/submit_feedback.py --type negative --code 600519 --name 贵州茅台 \
        --content "推荐了但当天就跌停，入场条件太宽松"

用法（云端 workflow_dispatch）：由 user_feedback.yml 注入环境变量
    FEEDBACK_TYPE / FEEDBACK_CONTENT / FEEDBACK_CODE / FEEDBACK_NAME
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.user_feedback import record_feedback  # noqa: E402

VALID_TYPES = {"positive", "negative", "preference"}


def submit(feedback_type: str, content: str, stock_code: str = "", stock_name: str = "") -> dict:
    """录入一条反馈并返回记录。"""
    if feedback_type not in VALID_TYPES:
        raise ValueError(
            f"非法 feedback_type={feedback_type!r}，只接受 {'/'.join(sorted(VALID_TYPES))}"
        )
    content = (content or "").strip()
    if not content:
        raise ValueError("反馈内容不能为空")
    return record_feedback(feedback_type, content, stock_code=stock_code, stock_name=stock_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="录入用户反馈到 data/user_feedback.jsonl")
    parser.add_argument("--type", choices=sorted(VALID_TYPES), default=os.environ.get("FEEDBACK_TYPE", ""))
    parser.add_argument("--content", default=os.environ.get("FEEDBACK_CONTENT", ""))
    parser.add_argument("--code", default=os.environ.get("FEEDBACK_CODE", ""))
    parser.add_argument("--name", default=os.environ.get("FEEDBACK_NAME", ""))
    args = parser.parse_args()

    try:
        rec = submit(args.type, args.content, stock_code=args.code, stock_name=args.name)
    except ValueError as e:
        print(f"❌ 反馈录入失败: {e}")
        return 1

    print(f"✅ 反馈已录入（{rec['timestamp']}）")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
