# -*- coding: utf-8 -*-
"""策略回测与定级脚本。

运行趋势突破策略回测，根据结果决定：
- 通过准入 → 正式纳入（权重30%）
- 试跑观察 → 保持试跑状态（权重20%）
- 不达标 → 淘汰
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.backtest_engine import (
    BacktestEngine, breakout_strategy, macd_resonance_strategy,
    oversold_rebound_strategy, build_backtest_report,
)
from strategies.macd_resonance.strategy_gate import StrategyGate, init_default_strategies


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
    print("🔬 策略回测与定级")
    print("=" * 50)

    # 1. 初始化策略库
    gate = init_default_strategies()

    # 2. 加载优质股票池
    pool_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "quality_pool.json")
    try:
        with open(pool_file, "r", encoding="utf-8") as f:
            pool = json.load(f)
        test_codes = [item["code"] for item in pool[:15]]
    except Exception:
        test_codes = ["600519", "000858", "601318", "000333", "600036",
                      "002594", "601012", "002475", "600276", "601888",
                      "000651", "600887", "002304", "603288", "000568"]

    print(f"回测股票数：{len(test_codes)}只")
    print(f"回测周期：60个交易日")

    engine = BacktestEngine()
    report_lines = [
        "🔬 策略回测与定级报告",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"回测股票：{len(test_codes)}只 | 周期：60天",
        "",
    ]

    # 3. 回测趋势突破策略
    print("\n" + "=" * 50)
    print("回测趋势突破策略...")
    breakout_result = engine.batch_backtest(test_codes, breakout_strategy, days=60)
    breakout_report = build_backtest_report(breakout_result, "趋势突破")
    print(breakout_report)
    report_lines.append(breakout_report)
    report_lines.append("")

    # 4. 提交准入审核
    admission = gate.submit_backtest_result("trend_breakout", breakout_result)
    print(f"\n准入结果：{admission['verdict']}")
    report_lines.append(f"🎯 趋势突破策略定级：{admission['verdict']}")

    # 5. 同时回测现有策略作为对比
    print("\n" + "=" * 50)
    print("回测MACD共振策略（对比）...")
    macd_result = engine.batch_backtest(test_codes[:10], macd_resonance_strategy, days=60)
    macd_report = build_backtest_report(macd_result, "MACD共振")
    print(macd_report)
    report_lines.append("")
    report_lines.append("【对比：MACD共振】")
    report_lines.append(f"  胜率：{macd_result.get('avg_win_rate', 0)}% | 平均收益：{macd_result.get('avg_return_pct', 0)}%")

    # 6. 输出策略库状态
    print("\n" + gate.get_strategy_report())
    report_lines.append("")
    report_lines.append(gate.get_strategy_report())

    final_report = "\n".join(report_lines)
    print("\n" + final_report)

    # 推送飞书
    if os.environ.get("PUSH_FEISHU", "true").lower() == "true":
        send_feishu(final_report)


if __name__ == "__main__":
    main()
