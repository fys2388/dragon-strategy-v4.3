# -*- coding: utf-8 -*-
"""三分仓位管理与支撑位测算（融合熊猫有财投资体系）。

来源：熊猫有财ETF投资体系
- 三分仓位：底仓30% + 加仓30% + 备用40%
- 支撑位测算：（阶段高点-阶段低点）÷3 + 阶段低点 = 短期有效支撑位

核心逻辑：
1. 首次建仓只用底仓（30%），不一次性满仓
2. 确认趋势后（突破后回踩不破20日均线）加仓30%
3. 保留40%备用金，应对回调加仓或空仓等待机会
4. 止损位基于支撑位测算，而非固定百分比
"""
from __future__ import annotations

import os
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSITION_FILE = os.path.join(BASE_DIR, "data", "position_sizing.json")


@dataclass
class PositionPlan:
    """单只股票的三分仓位计划。"""
    code: str
    name: str
    entry_price: float
    total_capital: float = 5000.0

    # 三分仓位
    base_pct: float = 0.30       # 底仓30%
    add_pct: float = 0.30        # 加仓30%
    reserve_pct: float = 0.40    # 备用40%

    # 状态
    base_filled: bool = False    # 底仓已建
    add_filled: bool = False     # 加仓已建
    add_trigger_price: float = 0.0  # 加仓触发价（回踩20日均线不破）
    support_price: float = 0.0   # 支撑位（止损参考）
    stop_loss_price: float = 0.0  # 止损价

    def base_amount(self) -> float:
        return self.total_capital * self.base_pct

    def add_amount(self) -> float:
        return self.total_capital * self.add_pct

    def reserve_amount(self) -> float:
        return self.total_capital * self.reserve_pct

    def max_position_amount(self) -> float:
        return self.base_amount() + self.add_amount()


class PositionSizingManager:
    """三分仓位管理器（融合熊猫有财体系）。"""

    def __init__(self, total_capital: float = 5000.0):
        self.total_capital = total_capital
        self.plans = self._load_plans()

    def _load_plans(self) -> Dict[str, PositionPlan]:
        try:
            if os.path.exists(POSITION_FILE):
                with open(POSITION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                plans = {}
                for code, pdata in data.get("plans", {}).items():
                    plans[code] = PositionPlan(**pdata)
                return plans
        except Exception:
            pass
        return {}

    def _save_plans(self):
        os.makedirs(os.path.dirname(POSITION_FILE), exist_ok=True)
        data = {
            "total_capital": self.total_capital,
            "plans": {code: plan.__dict__ for code, plan in self.plans.items()},
        }
        with open(POSITION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def create_plan(self, code: str, name: str, entry_price: float,
                    support_price: float = 0.0) -> PositionPlan:
        """创建新的三分仓位计划。

        Args:
            code: 股票代码
            name: 股票名称
            entry_price: 入场价
            support_price: 支撑位（用于止损），为0时用入场价-5%

        Returns:
            PositionPlan
        """
        # 止损价：支撑位下方2%，或入场价-5%，取较高者
        if support_price > 0:
            stop_loss = support_price * 0.98
        else:
            stop_loss = entry_price * 0.95

        plan = PositionPlan(
            code=code,
            name=name,
            entry_price=entry_price,
            total_capital=self.total_capital,
            support_price=support_price,
            stop_loss_price=round(stop_loss, 2),
            # 加仓触发价：入场价上方3%（突破后回踩不破20日均线时加仓）
            add_trigger_price=round(entry_price * 1.03, 2),
        )
        self.plans[code] = plan
        self._save_plans()
        return plan

    def get_initial_position_amount(self, code: str) -> float:
        """获取首次建仓金额（底仓30%）。"""
        plan = self.plans.get(code)
        if plan:
            return plan.base_amount()
        return self.total_capital * 0.30

    def should_add_position(self, code: str, current_price: float,
                            ma20: float = 0.0) -> Tuple[bool, str]:
        """判断是否应该加仓。

        加仓条件（熊猫有财顺势加仓原则）：
        1. 底仓已建
        2. 加仓未建
        3. 股价突破加仓触发价（入场价+3%）
        4. 回踩不破20日均线（如果提供了ma20）

        Returns:
            (是否加仓, 原因)
        """
        plan = self.plans.get(code)
        if not plan:
            return False, "无仓位计划"
        if not plan.base_filled:
            return False, "底仓未建"
        if plan.add_filled:
            return False, "加仓已建"
        if current_price < plan.add_trigger_price:
            return False, f"现价{current_price:.2f}<加仓触发价{plan.add_trigger_price:.2f}"
        if ma20 > 0 and current_price < ma20:
            return False, f"现价{current_price:.2f}<20日均线{ma20:.2f}，趋势走弱不加仓"
        return True, f"突破加仓触发价{plan.add_trigger_price:.2f}且站稳20日均线，建议加仓{plan.add_amount():.0f}元"

    def should_stop_loss(self, code: str, current_price: float) -> Tuple[bool, str]:
        """判断是否应该止损（基于支撑位）。

        熊猫有财原则：开仓即亏，说明判断错误，清仓离场。
        止损价基于支撑位测算，而非固定百分比。

        Returns:
            (是否止损, 原因)
        """
        plan = self.plans.get(code)
        if not plan:
            return False, "无仓位计划"
        if current_price <= plan.stop_loss_price:
            return True, f"现价{current_price:.2f}≤止损价{plan.stop_loss_price:.2f}（支撑位{plan.support_price:.2f}下方2%），建议清仓"
        return False, f"现价{current_price:.2f}>止损价{plan.stop_loss_price:.2f}"

    def close_plan(self, code: str):
        """清仓后移除计划。"""
        if code in self.plans:
            del self.plans[code]
            self._save_plans()

    def get_reserve_ratio(self) -> float:
        """获取当前备用金比例（用于判断是否应该空仓等待）。"""
        if not self.plans:
            return 1.0
        total_used = sum(
            (p.base_filled * p.base_pct + p.add_filled * p.add_pct)
            for p in self.plans.values()
        )
        return max(0, 1.0 - total_used)


def calc_support_price(high: float, low: float) -> float:
    """计算短期有效支撑位（熊猫有财方法）。

    公式：（阶段高点 - 阶段低点）÷ 3 + 阶段低点 = 短期有效支撑位

    原理：主力资金不会单纯在日内低点一次性完成吸筹，
    大多采用边拉升边分批建仓的模式，持仓成本偏高。
    个股走完一轮连板拉升后，股价回落至支撑区间就是低吸机会。

    Args:
        high: 阶段高点（前一轮上涨波段最高价）
        low: 阶段低点（前一轮上涨波段最低价）

    Returns:
        支撑位价格
    """
    if high <= low or low <= 0:
        return 0.0
    amplitude = high - low
    support = low + amplitude / 3
    return round(support, 2)


def calc_support_from_klines(closes: list, highs: list, lows: list,
                             lookback: int = 20) -> Dict[str, float]:
    """从K线数据计算支撑位和压力位。

    Args:
        closes: 收盘价列表
        highs: 最高价列表
        lows: 最低价列表
        lookback: 回看天数

    Returns:
        {support: 支撑位, resistance: 压力位, high: 阶段高, low: 阶段低}
    """
    if len(highs) < lookback or len(lows) < lookback:
        lookback = min(len(highs), len(lows))
    if lookback < 5:
        return {"support": 0, "resistance": 0, "high": 0, "low": 0}

    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    support = calc_support_price(recent_high, recent_low)
    # 压力位：高点 - 振幅/3（对称计算）
    resistance = round(recent_high - (recent_high - recent_low) / 3, 2)

    return {
        "support": support,
        "resistance": resistance,
        "high": round(recent_high, 2),
        "low": round(recent_low, 2),
    }


def get_position_advice(strategy_type: str, market_regime: str = "",
                        total_capital: float = 5000.0) -> Dict:
    """根据策略类型和市场环境给出仓位建议（融合熊猫有财三分仓位）。

    Args:
        strategy_type: 策略类型（macd/breakout/oversold）
        market_regime: 市场环境
        total_capital: 总资金

    Returns:
        仓位建议字典
    """
    # 基础三分仓位
    base = {
        "strategy": strategy_type,
        "total_capital": total_capital,
        "base_position_pct": 0.30,
        "add_position_pct": 0.30,
        "reserve_pct": 0.40,
        "base_amount": round(total_capital * 0.30, 0),
        "add_amount": round(total_capital * 0.30, 0),
        "reserve_amount": round(total_capital * 0.40, 0),
        "max_single_stock": round(total_capital * 0.60, 0),  # 底仓+加仓=60%
        "max_positions": 2,
    }

    # 根据市场环境调整
    regime_adjust = {
        "bull_trend": {"base_pct": 0.30, "add_pct": 0.30, "reserve_pct": 0.40, "note": "牛市：满仓运作，顺势加仓"},
        "bear_trend": {"base_pct": 0.15, "add_pct": 0.10, "reserve_pct": 0.75, "note": "熊市：轻仓试探，保留75%现金"},
        "sideways_up": {"base_pct": 0.25, "add_pct": 0.25, "reserve_pct": 0.50, "note": "震荡偏强：半仓运作"},
        "sideways_down": {"base_pct": 0.20, "add_pct": 0.15, "reserve_pct": 0.65, "note": "震荡偏弱：轻仓为主，超跌反弹才加仓"},
        "narrow_range": {"base_pct": 0.20, "add_pct": 0.15, "reserve_pct": 0.65, "note": "窄幅震荡：观望为主，突破才加仓"},
        "extreme": {"base_pct": 0.10, "add_pct": 0.00, "reserve_pct": 0.90, "note": "极端行情：几乎空仓，等待机会"},
    }

    if market_regime in regime_adjust:
        adj = regime_adjust[market_regime]
        base["base_position_pct"] = adj["base_pct"]
        base["add_position_pct"] = adj["add_pct"]
        base["reserve_pct"] = adj["reserve_pct"]
        base["base_amount"] = round(total_capital * adj["base_pct"], 0)
        base["add_amount"] = round(total_capital * adj["add_pct"], 0)
        base["reserve_amount"] = round(total_capital * adj["reserve_pct"], 0)
        base["max_single_stock"] = round(total_capital * (adj["base_pct"] + adj["add_pct"]), 0)
        base["regime_note"] = adj["note"]

    # 策略特定调整
    if strategy_type == "breakout":
        base["stop_loss_pct"] = 0.04  # 突破策略止损更严-4%
        base["take_profit_pct"] = 0.08
        base["strategy_note"] = "突破策略：假突破多，止损更严，首次建仓只用底仓"
    elif strategy_type == "oversold":
        base["stop_loss_pct"] = 0.06
        base["take_profit_pct"] = 0.10
        base["strategy_note"] = "超跌反弹：反弹即减仓，不恋战"
    else:
        base["stop_loss_pct"] = 0.05
        base["take_profit_pct"] = 0.10
        base["strategy_note"] = "MACD共振：趋势确认后加仓"

    return base
