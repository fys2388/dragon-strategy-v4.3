# -*- coding: utf-8 -*-
"""验证新策略并注册到策略准入控制器。

流程：
1. 用回测引擎回测趋势突破策略
2. 检查是否满足准入标准
3. 注册到策略库（候选/试跑/正式）
4. 输出验证报告
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.backtest_engine import (
    BacktestEngine, breakout_strategy, build_backtest_report,
)
from strategies.macd_resonance.strategy_gate import StrategyGate, init_default_strategies


def main():
    print("=" * 50)
    print("🔬 新策略验证：趋势突破")
    print("=" * 50)

    # 1. 初始化默认策略库
    gate = init_default_strategies()

    # 2. 注册趋势突破策略（候选状态）
    register_result = gate.register_strategy(
        strategy_id="trend_breakout",
        name="趋势突破",
        description="突破20日新高+放量+均线多头排列",
        alpha_source="突破前高+放量=筹码集中+新资金进场，突破后惯性上涨",
        applicable_market=["sideways", "bull_market"],
        risk_level="medium",
    )
    print(f"\n📝 策略注册：{register_result}")

    # 3. 回测验证（用10只优质股票池）
    print("\n🔄 开始回测验证...")
    engine = BacktestEngine()

    # 从优质股票池取10只回测
    import json
    pool_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "quality_pool.json")
    try:
        with open(pool_file, "r", encoding="utf-8") as f:
            pool = json.load(f)
        test_codes = [item["code"] for item in pool[:10]]
    except Exception:
        test_codes = ["600519", "000858", "601318", "000333", "600036", "002594", "300750", "601012", "002475", "600276"]

    print(f"回测股票：{test_codes}")
    backtest_result = engine.batch_backtest(test_codes, breakout_strategy, days=60)

    # 4. 输出回测报告
    print("\n" + build_backtest_report(backtest_result, "趋势突破"))

    # 5. 提交回测结果到准入控制器
    print("\n📋 提交准入审核...")
    admission = gate.submit_backtest_result("trend_breakout", backtest_result)
    print(f"审核结果：{admission['verdict']}")

    # 6. 输出策略库报告
    print("\n" + gate.get_strategy_report())


if __name__ == "__main__":
    main()
