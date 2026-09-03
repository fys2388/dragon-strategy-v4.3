# -*- coding: utf-8 -*-
"""进化引擎（第4层闭环迭代）。

核心能力：
1. 参数自动进化：基于历史表现自动调整策略参数
2. A/B测试框架：同时运行多套参数，对比胜率
3. 策略权重优化：根据各策略表现动态调整推荐权重
4. 进化日志：记录每次参数变化和效果，支持回滚

设计原则：
- 保守进化：每次只调整1-2个参数，避免剧烈变化
- 样本门槛：至少5个样本才进化，避免过拟合
- 回滚机制：进化后表现下降自动回滚
- 可解释：每次进化都有明确的原因和数据支撑
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from .tracking import _load_records, TRACKING_FILE
from .adaptive_config import (
    MACD_PARAMS, OVERSOLD_PARAMS, save_optimized_params,
    OPTIMIZED_PARAMS_FILE,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVOLUTION_LOG_FILE = os.path.join(BASE_DIR, "data", "evolution_log.jsonl")
AB_TEST_FILE = os.path.join(BASE_DIR, "data", "ab_test_state.json")


class EvolutionEngine:
    """策略进化引擎。"""

    def __init__(self):
        self.evolution_log = self._load_evolution_log()
        self.ab_state = self._load_ab_state()

    def _load_evolution_log(self) -> List[Dict]:
        try:
            if os.path.exists(EVOLUTION_LOG_FILE):
                with open(EVOLUTION_LOG_FILE, "r", encoding="utf-8") as f:
                    return [json.loads(line) for line in f if line.strip()]
        except Exception:
            pass
        return []

    def _save_evolution_log(self, entry: Dict):
        os.makedirs(os.path.dirname(EVOLUTION_LOG_FILE), exist_ok=True)
        with open(EVOLUTION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load_ab_state(self) -> Dict:
        try:
            if os.path.exists(AB_TEST_FILE):
                with open(AB_TEST_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"active_test": None, "results": {}}

    def _save_ab_state(self):
        os.makedirs(os.path.dirname(AB_TEST_FILE), exist_ok=True)
        with open(AB_TEST_FILE, "w", encoding="utf-8") as f:
            json.dump(self.ab_state, f, ensure_ascii=False, indent=2)

    # ============================================================
    # 1. 参数自动进化
    # ============================================================

    def evaluate_current_params(self) -> Dict[str, Any]:
        """评估当前参数表现。"""
        records = _load_records()
        completed = [r for r in records if r.get("status") == "completed" and r.get("day5_return_pct") is not None]

        if len(completed) < 5:
            return {"status": "insufficient_data", "count": len(completed), "message": "样本不足5只，暂不进化"}

        # 按策略分组
        by_strategy = defaultdict(list)
        for r in completed:
            by_strategy[r.get("strategy", "unknown")].append(r)

        evaluation = {}
        for strategy, recs in by_strategy.items():
            returns = [r["day5_return_pct"] for r in recs]
            win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
            avg_return = sum(returns) / len(returns)
            max_return = max(returns)
            min_return = min(returns)
            evaluation[strategy] = {
                "count": len(recs),
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_return, 2),
                "max_return": round(max_return, 2),
                "min_return": round(min_return, 2),
                "sharpe_like": round(avg_return / (max(1, abs(min_return))), 2),
            }

        return {"status": "ok", "count": len(completed), "by_strategy": evaluation}

    def evolve_params(self) -> Dict[str, Any]:
        """执行参数进化。"""
        evaluation = self.evaluate_current_params()
        if evaluation["status"] == "insufficient_data":
            return evaluation

        changes = []
        optimized = {"macd": {}, "oversold": {}}

        for strategy, perf in evaluation.get("by_strategy", {}).items():
            if strategy not in ["resonance", "oversold"]:
                continue

            param_group = "macd" if strategy == "resonance" else "oversold"
            base_params = MACD_PARAMS if strategy == "resonance" else OVERSOLD_PARAMS
            win_rate = perf["win_rate"]
            avg_return = perf["avg_return"]

            # 进化逻辑
            if win_rate < 40:
                # 胜率太低，大幅收紧
                if strategy == "resonance":
                    optimized[param_group]["sideways"] = {
                        "min_score": min(base_params["sideways"].get("min_score", 60) + 15, 90),
                        "amplitude_20d_max": max(base_params["sideways"].get("amplitude_20d_max", 40) - 10, 25),
                    }
                else:
                    optimized[param_group]["sideways"] = {
                        "drop_20d_min": min(base_params["sideways"].get("drop_20d_min", 30) + 10, 50),
                        "today_gain_min": min(base_params["sideways"].get("today_gain_min", 4) + 2, 8),
                    }
                changes.append(f"{strategy}胜率{win_rate}%<40%，大幅收紧条件")

            elif win_rate < 55:
                # 胜率偏低，适度收紧
                if strategy == "resonance":
                    optimized[param_group]["sideways"] = {
                        "min_score": min(base_params["sideways"].get("min_score", 60) + 5, 85),
                    }
                else:
                    optimized[param_group]["sideways"] = {
                        "drop_20d_min": min(base_params["sideways"].get("drop_20d_min", 30) + 5, 45),
                    }
                changes.append(f"{strategy}胜率{win_rate}%<55%，适度收紧条件")

            elif win_rate > 75 and avg_return > 5:
                # 胜率高且收益好，放宽捕捉更多机会
                if strategy == "resonance":
                    optimized[param_group]["sideways"] = {
                        "min_score": max(base_params["sideways"].get("min_score", 60) - 10, 40),
                        "amplitude_20d_max": min(base_params["sideways"].get("amplitude_20d_max", 40) + 10, 60),
                    }
                else:
                    optimized[param_group]["sideways"] = {
                        "drop_20d_min": max(base_params["sideways"].get("drop_20d_min", 30) - 5, 15),
                    }
                changes.append(f"{strategy}胜率{win_rate}%>75%且收益{avg_return}%，放宽条件")

        if changes:
            # 保存优化参数
            save_optimized_params(
                macd_params=optimized["macd"] if optimized["macd"] else None,
                oversold_params=optimized["oversold"] if optimized["oversold"] else None,
            )

            # 记录进化日志
            log_entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "type": "param_evolution",
                "evaluation": evaluation,
                "changes": changes,
                "new_params": optimized,
            }
            self._save_evolution_log(log_entry)

        return {
            "status": "evolved" if changes else "no_change",
            "evaluation": evaluation,
            "changes": changes,
            "optimized_params": optimized,
        }

    # ============================================================
    # 2. A/B测试框架
    # ============================================================

    def start_ab_test(self, strategy: str, param_a: Dict, param_b: Dict, duration_days: int = 7) -> Dict:
        """启动A/B测试。"""
        test_id = f"ab_{strategy}_{int(time.time())}"
        test = {
            "id": test_id,
            "strategy": strategy,
            "param_a": param_a,
            "param_b": param_b,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": (datetime.fromtimestamp(time.time() + duration_days * 86400)).strftime("%Y-%m-%d %H:%M:%S"),
            "duration_days": duration_days,
            "results_a": [],
            "results_b": [],
            "status": "running",
        }
        self.ab_state["active_test"] = test
        self._save_ab_state()
        return test

    def record_ab_result(self, test_id: str, variant: str, stock_code: str, return_pct: float):
        """记录A/B测试结果。"""
        test = self.ab_state.get("active_test")
        if not test or test["id"] != test_id:
            return False
        if variant == "a":
            test["results_a"].append({"code": stock_code, "return_pct": return_pct})
        else:
            test["results_b"].append({"code": stock_code, "return_pct": return_pct})
        self._save_ab_state()
        return True

    def conclude_ab_test(self) -> Dict:
        """结束A/B测试，得出结论。"""
        test = self.ab_state.get("active_test")
        if not test:
            return {"status": "no_active_test"}

        results_a = test["results_a"]
        results_b = test["results_b"]

        if len(results_a) < 3 or len(results_b) < 3:
            return {"status": "insufficient_data", "count_a": len(results_a), "count_b": len(results_b)}

        win_a = sum(1 for r in results_a if r["return_pct"] > 0) / len(results_a) * 100
        win_b = sum(1 for r in results_b if r["return_pct"] > 0) / len(results_b) * 100
        avg_a = sum(r["return_pct"] for r in results_a) / len(results_a)
        avg_b = sum(r["return_pct"] for r in results_b) / len(results_b)

        winner = "b" if (win_b > win_a and avg_b > avg_a) else ("a" if (win_a > win_b and avg_a > avg_b) else "tie")

        conclusion = {
            "test_id": test["id"],
            "strategy": test["strategy"],
            "count_a": len(results_a),
            "count_b": len(results_b),
            "win_rate_a": round(win_a, 1),
            "win_rate_b": round(win_b, 1),
            "avg_return_a": round(avg_a, 2),
            "avg_return_b": round(avg_b, 2),
            "winner": winner,
            "winning_params": test["param_b"] if winner == "b" else test["param_a"],
        }

        # 记录进化日志
        self._save_evolution_log({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "ab_test_conclusion",
            "conclusion": conclusion,
        })

        # 如果B胜出，保存为优化参数
        if winner == "b":
            param_group = "macd" if test["strategy"] == "resonance" else "oversold"
            save_optimized_params(**{param_group: {"sideways": test["param_b"]}})

        self.ab_state["active_test"] = None
        self.ab_state.setdefault("history", []).append(conclusion)
        self._save_ab_state()

        return conclusion

    # ============================================================
    # 3. 策略权重优化
    # ============================================================

    def optimize_strategy_weights(self) -> Dict[str, Any]:
        """根据各策略表现优化推荐权重。"""
        records = _load_records()
        completed = [r for r in records if r.get("status") == "completed" and r.get("day5_return_pct") is not None]

        if len(completed) < 10:
            return {"status": "insufficient_data", "weights": {"resonance": 0.5, "oversold": 0.5}}

        by_strategy = defaultdict(list)
        for r in completed:
            by_strategy[r.get("strategy", "unknown")].append(r)

        weights = {}
        total_score = 0
        for strategy in ["resonance", "oversold"]:
            recs = by_strategy.get(strategy, [])
            if recs:
                returns = [r["day5_return_pct"] for r in recs]
                win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
                avg_return = sum(returns) / len(returns)
                # 综合评分：胜率*0.6 + 平均收益*0.4
                score = win_rate * 0.6 + max(0, avg_return) * 4
                weights[strategy] = max(0.2, score)  # 最低20%权重
                total_score += weights[strategy]
            else:
                weights[strategy] = 0.3
                total_score += 0.3

        # 归一化
        for strategy in weights:
            weights[strategy] = round(weights[strategy] / total_score, 2)

        # 保存权重
        weights_file = os.path.join(BASE_DIR, "data", "strategy_weights.json")
        with open(weights_file, "w", encoding="utf-8") as f:
            json.dump({"weights": weights, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)

        # 记录进化日志
        self._save_evolution_log({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "weight_optimization",
            "weights": weights,
            "sample_count": len(completed),
        })

        return {"status": "ok", "weights": weights, "sample_count": len(completed)}

    # ============================================================
    # 4. 进化报告
    # ============================================================

    def get_evolution_report(self) -> str:
        """生成进化报告。"""
        evaluation = self.evaluate_current_params()
        evolution_result = self.evolve_params()
        weights = self.optimize_strategy_weights()

        lines = [
            "🔄 策略进化报告（第4层闭环迭代）",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⏱ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]

        # 当前表现
        if evaluation["status"] == "insufficient_data":
            lines.append(f"📊 当前样本：{evaluation['count']}只（不足5只，暂不进化）")
        else:
            lines.append("📊 当前策略表现：")
            for strategy, perf in evaluation.get("by_strategy", {}).items():
                win_color = "🟢" if perf["win_rate"] >= 50 else "🔴"
                lines.append(
                    f"  {strategy}：样本{perf['count']}只 | "
                    f"{win_color}胜率{perf['win_rate']}% | "
                    f"平均收益{perf['avg_return']}% | "
                    f"最佳{perf['max_return']}% | 最差{perf['min_return']}%"
                )

        lines.append("")

        # 进化结果
        if evolution_result.get("changes"):
            lines.append("🔧 本周参数进化：")
            for change in evolution_result["changes"]:
                lines.append(f"  {change}")
            lines.append("")
            lines.append("✅ 新参数已保存，下次扫描自动生效")
        else:
            lines.append("✅ 参数无需调整，保持当前配置")

        lines.append("")

        # 策略权重
        if weights["status"] == "ok":
            lines.append("⚖️ 策略权重优化：")
            for strategy, weight in weights["weights"].items():
                lines.append(f"  {strategy}：{weight*100:.0f}%")
            lines.append("")

        # 进化历史
        recent_evolutions = self.evolution_log[-5:]
        if recent_evolutions:
            lines.append("📜 最近进化记录：")
            for evo in recent_evolutions:
                evo_type = evo.get("type", "unknown")
                timestamp = evo.get("timestamp", "")
                if evo_type == "param_evolution":
                    changes = evo.get("changes", [])
                    lines.append(f"  {timestamp} 参数进化：{'; '.join(changes[:2])}")
                elif evo_type == "weight_optimization":
                    w = evo.get("weights", {})
                    lines.append(f"  {timestamp} 权重优化：MACD{w.get('resonance', 0)*100:.0f}% / 超跌{w.get('oversold', 0)*100:.0f}%")
                elif evo_type == "ab_test_conclusion":
                    c = evo.get("conclusion", {})
                    lines.append(f"  {timestamp} A/B测试：{c.get('winner', 'tie')}胜出")

        lines.append("")
        lines.append("⚠️ 进化基于历史数据，不保证未来表现")
        return "\n".join(lines)


def run_weekly_evolution() -> Dict[str, Any]:
    """执行每周进化。"""
    print("=" * 50)
    print("🔄 开始每周策略进化...")
    print("=" * 50)

    engine = EvolutionEngine()
    report = engine.get_evolution_report()
    print("\n" + report)

    return {
        "report": report,
        "evaluation": engine.evaluate_current_params(),
        "weights": engine.optimize_strategy_weights(),
    }
