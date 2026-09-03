# -*- coding: utf-8 -*-
"""每周策略回测与参数优化模块。

基于tracking.jsonl中的历史推荐数据，统计不同市场环境下的表现，
自动调整策略参数，实现闭环迭代。

优化逻辑：
- 胜率<50%：收紧条件（提高最低得分、收紧振幅、提高超跌要求）
- 胜率>70%：放宽条件（降低最低得分、放宽振幅、降低超跌要求）
- 50%-70%：保持当前参数
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Dict, List, Any

from .tracking import _load_records, TRACKING_FILE
from .adaptive_config import (
    MACD_PARAMS, OVERSOLD_PARAMS, save_optimized_params,
    OPTIMIZED_PARAMS_FILE,
)
from .market_regime import REGIME_LABELS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def analyze_performance_by_regime() -> Dict[str, Any]:
    """按市场环境分析策略表现。"""
    records = _load_records()

    # 按策略+市场环境分组
    groups = defaultdict(list)
    for r in records:
        strategy = r.get("strategy", "unknown")
        regime = r.get("regime", "unknown")
        if r.get("day5_return_pct") is not None:
            groups[(strategy, regime)].append(r)

    analysis = {}
    for (strategy, regime), recs in groups.items():
        if len(recs) < 3:  # 样本太少不统计
            continue
        returns = [r["day5_return_pct"] for r in recs]
        win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
        avg_return = sum(returns) / len(returns)
        max_return = max(returns)
        min_return = min(returns)
        analysis[f"{strategy}_{regime}"] = {
            "strategy": strategy,
            "regime": regime,
            "count": len(recs),
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_return, 2),
            "max_return": round(max_return, 2),
            "min_return": round(min_return, 2),
        }

    return analysis


def optimize_params(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """根据表现分析优化参数。"""
    optimized = {"macd": {}, "oversold": {}}
    changes = []

    for key, perf in analysis.items():
        strategy = perf["strategy"]
        regime = perf["regime"]
        win_rate = perf["win_rate"]
        count = perf["count"]

        if count < 5:  # 样本太少不优化
            continue

        # 获取当前参数
        if strategy == "resonance":
            current = MACD_PARAMS.get(regime, MACD_PARAMS["sideways"])
            param_group = "macd"
        else:
            current = OVERSOLD_PARAMS.get(regime, OVERSOLD_PARAMS["sideways"])
            param_group = "oversold"

        new_params = {}

        if win_rate < 50:
            # 胜率低，收紧条件
            if strategy == "resonance":
                new_params["min_score"] = min(current.get("min_score", 60) + 10, 90)
                new_params["amplitude_20d_max"] = max(current.get("amplitude_20d_max", 40) - 5, 25)
                changes.append(f"[{regime}] MACD胜率{win_rate}%<50%，收紧：得分+10，振幅-5%")
            else:
                new_params["drop_20d_min"] = min(current.get("drop_20d_min", 25) + 5, 50)
                new_params["today_gain_min"] = min(current.get("today_gain_min", 4) + 1, 8)
                changes.append(f"[{regime}] 超跌胜率{win_rate}%<50%，收紧：超跌+5%，涨幅+1%")

        elif win_rate > 70:
            # 胜率高，放宽条件捕捉更多机会
            if strategy == "resonance":
                new_params["min_score"] = max(current.get("min_score", 60) - 5, 40)
                new_params["amplitude_20d_max"] = min(current.get("amplitude_20d_max", 40) + 5, 60)
                changes.append(f"[{regime}] MACD胜率{win_rate}%>70%，放宽：得分-5，振幅+5%")
            else:
                new_params["drop_20d_min"] = max(current.get("drop_20d_min", 25) - 3, 15)
                new_params["today_gain_min"] = max(current.get("today_gain_min", 4) - 0.5, 2)
                changes.append(f"[{regime}] 超跌胜率{win_rate}%>70%，放宽：超跌-3%，涨幅-0.5%")

        if new_params:
            optimized[param_group][regime] = new_params

    return {"params": optimized, "changes": changes}


def run_weekly_optimization() -> Dict[str, Any]:
    """执行每周优化。"""
    print("=" * 50)
    print("🔄 开始每周策略回测与参数优化...")
    print("=" * 50)

    # 1. 分析表现
    analysis = analyze_performance_by_regime()
    print(f"\n📊 历史表现分析（按市场环境）：")
    if not analysis:
        print("  样本不足，暂不优化（需要至少5只已完成跟踪的股票）")
        return {"status": "insufficient_data", "analysis": {}, "changes": []}

    for key, perf in analysis.items():
        label = REGIME_LABELS.get(perf["regime"], perf["regime"])
        print(f"  {perf['strategy']} | {label} | 样本{perf['count']}只 | "
              f"胜率{perf['win_rate']}% | 平均收益{perf['avg_return']}%")

    # 2. 优化参数
    result = optimize_params(analysis)
    changes = result["changes"]

    if changes:
        print(f"\n🔧 参数优化调整：")
        for c in changes:
            print(f"  {c}")

        # 3. 保存优化结果
        save_optimized_params(
            macd_params=result["params"]["macd"],
            oversold_params=result["params"]["oversold"],
        )
        status = "optimized"
    else:
        print(f"\n✅ 参数无需调整（胜率在50%-70%区间或样本不足）")
        status = "no_change"

    return {
        "status": status,
        "analysis": analysis,
        "changes": changes,
        "optimized_params": result["params"],
    }


def build_optimization_report(result: Dict[str, Any]) -> str:
    """生成优化报告。"""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"🔄 每周策略回测与参数优化报告",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏱ 生成时间：{now}",
        "",
    ]

    if result["status"] == "insufficient_data":
        lines.append("📊 历史样本不足，暂不优化")
        lines.append("   需要至少5只已完成5日跟踪的股票")
        lines.append("   持续积累数据中...")
        return "\n".join(lines)

    lines.append("📊 历史表现（按市场环境）：")
    for key, perf in result["analysis"].items():
        label = REGIME_LABELS.get(perf["regime"], perf["regime"])
        win_color = "🟢" if perf["win_rate"] >= 50 else "🔴"
        lines.append(
            f"  {perf['strategy']} | {label} | 样本{perf['count']}只 | "
            f"{win_color}胜率{perf['win_rate']}% | 平均收益{perf['avg_return']}%"
        )

    lines.append("")
    if result["changes"]:
        lines.append("🔧 本周参数调整：")
        for c in result["changes"]:
            lines.append(f"  {c}")
        lines.append("")
        lines.append("✅ 优化参数已保存，下次扫描自动生效")
    else:
        lines.append("✅ 参数无需调整，保持当前配置")

    return "\n".join(lines)
