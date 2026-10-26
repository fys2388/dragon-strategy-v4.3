# -*- coding: utf-8 -*-
"""策略准入控制器。

管理策略的完整生命周期：
候选 → 回测验证 → 7天试跑 → 正式纳入 → 持续监控 → 表现下降降权 → 淘汰

核心原则：
- 新策略必须通过回测验证才能进入试跑
- 试跑期只给20%权重，不主推
- 试跑达标才能转正
- 正式策略表现下降自动降权，连续不达标淘汰
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRATEGY_REGISTRY_FILE = os.path.join(BASE_DIR, "data", "strategy_registry.json")

# 策略状态
STATUS_CANDIDATE = "candidate"      # 候选，待回测
STATUS_BACKTEST = "backtesting"     # 回测中
STATUS_TRIAL = "trial"              # 试跑期（7天，20%权重）
STATUS_ACTIVE = "active"            # 正式纳入
STATUS_DEMOTED = "demoted"          # 降权（表现下降）
STATUS_RETIRED = "retired"          # 淘汰

# 准入标准
ADMISSION_CRITERIA = {
    "win_rate_min": 50,          # 胜率>50%
    "avg_return_min": 3,         # 平均收益>3%
    "max_drawdown_max": 10,      # 最大回撤<10%
    "min_trades": 5,             # 交易次数>5
    "trial_days": 7,             # 试跑期7天
    "trial_weight": 0.2,         # 试跑期权重20%
    "demote_win_rate": 40,       # 胜率<40%降权
    "retire_win_rate": 30,       # 胜率<30%淘汰
}


class StrategyGate:
    """策略准入控制器。"""

    def __init__(self):
        self.registry = self._load_registry()

    def _load_registry(self) -> Dict:
        try:
            if os.path.exists(STRATEGY_REGISTRY_FILE):
                with open(STRATEGY_REGISTRY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"strategies": {}, "updated_at": None}

    def _save_registry(self):
        os.makedirs(os.path.dirname(STRATEGY_REGISTRY_FILE), exist_ok=True)
        self.registry["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(STRATEGY_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.registry, f, ensure_ascii=False, indent=2)

    def register_strategy(
        self,
        strategy_id: str,
        name: str,
        description: str,
        alpha_source: str,
        applicable_market: List[str],
        risk_level: str = "medium",
    ) -> Dict:
        """注册新策略（候选状态）。"""
        if strategy_id in self.registry["strategies"]:
            return {"status": "exists", "strategy_id": strategy_id}

        self.registry["strategies"][strategy_id] = {
            "id": strategy_id,
            "name": name,
            "description": description,
            "alpha_source": alpha_source,          # 赚钱逻辑
            "applicable_market": applicable_market,  # 适用市场环境
            "risk_level": risk_level,               # low/medium/high
            "status": STATUS_CANDIDATE,
            "weight": 0,
            "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "backtest_result": None,
            "trial_start": None,
            "trial_results": [],
            "active_since": None,
            "performance": {"win_rate": 0, "avg_return": 0, "total_trades": 0},
            "history": [],
        }
        self._save_registry()
        return {"status": "registered", "strategy_id": strategy_id}

    def submit_backtest_result(self, strategy_id: str, backtest_result: Dict) -> Dict:
        """提交回测结果，判断是否进入试跑。"""
        strategy = self.registry["strategies"].get(strategy_id)
        if not strategy:
            return {"status": "not_found"}

        strategy["backtest_result"] = backtest_result
        strategy["history"].append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "backtest_submitted",
            "result": backtest_result.get("status"),
        })

        # 检查准入标准
        checks = self._check_criteria(backtest_result)
        if checks["passed"]:
            strategy["status"] = STATUS_TRIAL
            strategy["weight"] = ADMISSION_CRITERIA["trial_weight"]
            strategy["trial_start"] = datetime.now().strftime("%Y-%m-%d")
            strategy["history"].append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": "promoted_to_trial",
                "reason": "回测通过准入标准",
            })
            verdict = "回测通过，进入7天试跑期（权重20%）"
        else:
            strategy["status"] = STATUS_CANDIDATE
            verdict = f"回测未通过：{checks['failed_items']}"

        self._save_registry()
        return {
            "status": strategy["status"],
            "verdict": verdict,
            "checks": checks,
        }

    def record_trial_result(self, strategy_id: str, return_pct: float, is_win: bool):
        """记录试跑期结果。"""
        strategy = self.registry["strategies"].get(strategy_id)
        if not strategy or strategy["status"] != STATUS_TRIAL:
            return

        strategy["trial_results"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "return_pct": return_pct,
            "is_win": is_win,
        })
        self._save_registry()

    def check_trial_completion(self, strategy_id: str) -> Dict:
        """检查试跑期是否完成，是否转正。"""
        strategy = self.registry["strategies"].get(strategy_id)
        if not strategy or strategy["status"] != STATUS_TRIAL:
            return {"status": "not_in_trial"}

        trial_start = datetime.strptime(strategy["trial_start"], "%Y-%m-%d")
        days_passed = (datetime.now() - trial_start).days

        if days_passed < ADMISSION_CRITERIA["trial_days"]:
            return {
                "status": "trial_in_progress",
                "days_passed": days_passed,
                "days_remaining": ADMISSION_CRITERIA["trial_days"] - days_passed,
            }

        # 试跑期结束，评估结果
        trial_results = strategy["trial_results"]
        if len(trial_results) < 3:
            strategy["status"] = STATUS_CANDIDATE
            strategy["weight"] = 0
            verdict = "试跑期样本不足（<3次），退回候选"
        else:
            wins = sum(1 for r in trial_results if r["is_win"])
            win_rate = wins / len(trial_results) * 100
            avg_return = sum(r["return_pct"] for r in trial_results) / len(trial_results)

            if win_rate >= 50 and avg_return > 0:
                strategy["status"] = STATUS_ACTIVE
                strategy["weight"] = 0.3  # 正式纳入，初始权重30%
                strategy["active_since"] = datetime.now().strftime("%Y-%m-%d")
                verdict = f"试跑通过，正式纳入（胜率{win_rate:.0f}%，平均收益{avg_return:.1f}%）"
            else:
                strategy["status"] = STATUS_RETIRED
                strategy["weight"] = 0
                verdict = f"试跑未达标（胜率{win_rate:.0f}%），淘汰"

        strategy["history"].append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": "trial_completed",
            "verdict": verdict,
        })
        self._save_registry()
        return {"status": strategy["status"], "verdict": verdict}

    def update_performance(self, strategy_id: str, win_rate: float, avg_return: float, total_trades: int):
        """更新正式策略表现，自动降权/淘汰。"""
        strategy = self.registry["strategies"].get(strategy_id)
        if not strategy or strategy["status"] not in [STATUS_ACTIVE, STATUS_DEMOTED]:
            return

        strategy["performance"] = {
            "win_rate": win_rate,
            "avg_return": avg_return,
            "total_trades": total_trades,
        }

        # 自动降权/淘汰
        if win_rate < ADMISSION_CRITERIA["retire_win_rate"]:
            strategy["status"] = STATUS_RETIRED
            strategy["weight"] = 0
            action = "retired"
            reason = f"胜率{win_rate:.0f}%<30%，淘汰"
        elif win_rate < ADMISSION_CRITERIA["demote_win_rate"]:
            strategy["status"] = STATUS_DEMOTED
            strategy["weight"] = 0.1
            action = "demoted"
            reason = f"胜率{win_rate:.0f}%<40%，降权到10%"
        else:
            action = "ok"
            reason = "表现正常"

        strategy["history"].append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "reason": reason,
        })
        self._save_registry()

    def get_active_strategies(self) -> List[Dict]:
        """获取当前有效策略（正式+试跑），按权重排序。"""
        active = []
        for sid, s in self.registry["strategies"].items():
            if s["status"] in [STATUS_ACTIVE, STATUS_TRIAL, STATUS_DEMOTED] and s["weight"] > 0:
                active.append({
                    "id": sid,
                    "name": s["name"],
                    "status": s["status"],
                    "weight": s["weight"],
                    "applicable_market": s["applicable_market"],
                    "risk_level": s["risk_level"],
                })
        active.sort(key=lambda x: x["weight"], reverse=True)
        return active

    def get_strategy_report(self) -> str:
        """生成策略库报告。"""
        lines = [
            "📋 策略库状态报告",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        status_labels = {
            STATUS_CANDIDATE: "候选",
            STATUS_BACKTEST: "回测中",
            STATUS_TRIAL: "试跑",
            STATUS_ACTIVE: "正式",
            STATUS_DEMOTED: "降权",
            STATUS_RETIRED: "淘汰",
        }

        for sid, s in self.registry["strategies"].items():
            status = status_labels.get(s["status"], s["status"])
            weight = s["weight"] * 100
            perf = s.get("performance", {})
            lines.append(f"\n【{s['name']}】({sid})")
            lines.append(f"  状态：{status} | 权重：{weight:.0f}%")
            lines.append(f"  逻辑：{s['alpha_source']}")
            lines.append(f"  适用：{', '.join(s['applicable_market'])}")
            if perf.get("total_trades", 0) > 0:
                lines.append(f"  表现：胜率{perf['win_rate']:.0f}% | 平均收益{perf['avg_return']:.1f}% | 交易{perf['total_trades']}次")
            if s["status"] == STATUS_TRIAL and s.get("trial_start"):
                trial_start = datetime.strptime(s["trial_start"], "%Y-%m-%d")
                days_passed = (datetime.now() - trial_start).days
                lines.append(f"  试跑进度：{days_passed}/{ADMISSION_CRITERIA['trial_days']}天")

        return "\n".join(lines)

    def _check_criteria(self, backtest_result: Dict) -> Dict:
        """检查准入标准。"""
        checks = {
            "win_rate": backtest_result.get("avg_win_rate", backtest_result.get("win_rate", 0)) > ADMISSION_CRITERIA["win_rate_min"],
            "avg_return": backtest_result.get("avg_return_pct", 0) > ADMISSION_CRITERIA["avg_return_min"],
            "max_drawdown": backtest_result.get("avg_max_drawdown_pct", backtest_result.get("max_drawdown_pct", 99)) < ADMISSION_CRITERIA["max_drawdown_max"],
            "trade_count": backtest_result.get("total_trades", 0) > ADMISSION_CRITERIA["min_trades"],
        }
        failed = [k for k, v in checks.items() if not v]
        return {"passed": all(checks.values()), "checks": checks, "failed_items": failed}


# ============================================================
# 初始化默认策略库
# ============================================================

def init_default_strategies():
    """初始化默认策略库（MACD共振和超跌反弹直接设为正式）。"""
    gate = StrategyGate()

    # MACD多周期共振
    if "macd_resonance" not in gate.registry["strategies"]:
        gate.register_strategy(
            strategy_id="macd_resonance",
            name="MACD多周期共振",
            description="日线+60min+30min+15min多周期MACD金叉共振",
            alpha_source="多周期同时金叉=大资金一致看多，趋势启动",
            applicable_market=["bull_market", "strong_rebound"],
            risk_level="medium",
        )
        s = gate.registry["strategies"]["macd_resonance"]
        s["status"] = STATUS_ACTIVE
        s["weight"] = 0.4
        s["active_since"] = "2026-08-01"

    # 超跌反弹
    if "oversold_rebound" not in gate.registry["strategies"]:
        gate.register_strategy(
            strategy_id="oversold_rebound",
            name="超跌反弹",
            description="20日跌25%+当日涨4%+量比1.8+60min金叉",
            alpha_source="跌多了+放量=恐慌结束+资金抄底，均值回归",
            applicable_market=["bear_market", "sideways"],
            risk_level="high",
        )
        s = gate.registry["strategies"]["oversold_rebound"]
        s["status"] = STATUS_ACTIVE
        s["weight"] = 0.3
        s["active_since"] = "2026-08-15"

    gate._save_registry()
    return gate
