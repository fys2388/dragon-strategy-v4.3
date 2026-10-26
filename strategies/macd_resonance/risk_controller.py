# -*- coding: utf-8 -*-
"""风险控制器。

核心能力：
1. 单票仓位控制：最多30%
2. 总仓位控制：最多2只股票
3. 止损止盈：-5%止损，+8%/+12%止盈
4. 总回撤控制：账户回撤>8%暂停开仓3天
5. 相关性检查：避免不同策略同时推荐同一只股票
6. 黑名单管理：近期亏损股暂时排除

设计原则：
- 保守优先，先保证不亏大钱，再追求收益
- 所有限制可配置，但默认值适合5000元小资金
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RISK_STATE_FILE = os.path.join(BASE_DIR, "data", "risk_state.json")

# 默认风控参数（适合5000元小资金）
DEFAULT_RISK_CONFIG = {
    "total_capital": 5000,           # 总资金
    "max_position_pct": 0.30,        # 单票最大仓位30%
    "max_positions": 2,              # 最多同时持仓2只
    "stop_loss_pct": 0.05,           # 止损-5%
    "take_profit_1_pct": 0.08,       # 第一止盈+8%
    "take_profit_2_pct": 0.12,       # 第二止盈+12%
    "max_drawdown_pct": 0.08,        # 总回撤>8%暂停
    "drawdown_pause_days": 3,        # 回撤暂停天数
    "blacklist_days": 7,             # 亏损股黑名单天数
    "min_trade_amount": 500,         # 最小交易金额
    "max_daily_trades": 2,           # 每日最多开仓2次
}


class RiskController:
    """风险控制器。"""

    def __init__(self, config: Dict = None):
        self.config = {**DEFAULT_RISK_CONFIG, **(config or {})}
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        try:
            if os.path.exists(RISK_STATE_FILE):
                with open(RISK_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "positions": [],           # 当前持仓
            "blacklist": {},           # 黑名单 {code: 解禁日期}
            "trade_history": [],       # 交易历史
            "peak_capital": self.config["total_capital"],
            "current_capital": self.config["total_capital"],
            "paused_until": None,      # 暂停开仓截止时间
            "daily_trades": {"date": None, "count": 0},
        }

    def _save_state(self):
        os.makedirs(os.path.dirname(RISK_STATE_FILE), exist_ok=True)
        with open(RISK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def can_open_position(self, stock_code: str, stock_name: str = "") -> Dict[str, Any]:
        """检查是否可以开仓。

        Returns:
            {allowed: bool, reason: str, max_amount: float}
        """
        now = datetime.now()

        # 1. 检查是否在暂停期
        if self.state.get("paused_until"):
            pause_until = datetime.strptime(self.state["paused_until"], "%Y-%m-%d")
            if now < pause_until:
                return {
                    "allowed": False,
                    "reason": f"总回撤过大，暂停开仓至{pause_until.strftime('%Y-%m-%d')}",
                    "max_amount": 0,
                }

        # 2. 检查黑名单
        if stock_code in self.state["blacklist"]:
            unblock_date = self.state["blacklist"][stock_code]
            if now.strftime("%Y-%m-%d") < unblock_date:
                return {
                    "allowed": False,
                    "reason": f"近期亏损股，黑名单至{unblock_date}",
                    "max_amount": 0,
                }

        # 3. 检查持仓数量
        if len(self.state["positions"]) >= self.config["max_positions"]:
            return {
                "allowed": False,
                "reason": f"已达最大持仓数{self.config['max_positions']}只",
                "max_amount": 0,
            }

        # 4. 检查是否已持仓
        for pos in self.state["positions"]:
            if pos["code"] == stock_code:
                return {
                    "allowed": False,
                    "reason": "已持仓该股票",
                    "max_amount": 0,
                }

        # 5. 检查每日交易次数
        today = now.strftime("%Y-%m-%d")
        if self.state["daily_trades"]["date"] != today:
            self.state["daily_trades"] = {"date": today, "count": 0}
        if self.state["daily_trades"]["count"] >= self.config["max_daily_trades"]:
            return {
                "allowed": False,
                "reason": f"今日已达最大开仓次数{self.config['max_daily_trades']}次",
                "max_amount": 0,
            }

        # 6. 计算最大可买金额
        max_amount = self.config["total_capital"] * self.config["max_position_pct"]
        # 扣除已占用资金
        used_capital = sum(p["amount"] for p in self.state["positions"])
        available = self.config["total_capital"] - used_capital
        max_amount = min(max_amount, available)

        if max_amount < self.config["min_trade_amount"]:
            return {
                "allowed": False,
                "reason": f"可用资金不足（{max_amount:.0f}元<{self.config['min_trade_amount']}元）",
                "max_amount": 0,
            }

        return {
            "allowed": True,
            "reason": "风控通过",
            "max_amount": round(max_amount, 2),
            "stop_loss_pct": self.config["stop_loss_pct"],
            "take_profit_1_pct": self.config["take_profit_1_pct"],
            "take_profit_2_pct": self.config["take_profit_2_pct"],
        }

    def open_position(self, stock_code: str, stock_name: str, price: float, amount: float) -> Dict:
        """记录开仓。"""
        check = self.can_open_position(stock_code, stock_name)
        if not check["allowed"]:
            return {"status": "rejected", "reason": check["reason"]}

        position = {
            "code": stock_code,
            "name": stock_name,
            "entry_price": price,
            "amount": amount,
            "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stop_loss": round(price * (1 - self.config["stop_loss_pct"]), 2),
            "take_profit_1": round(price * (1 + self.config["take_profit_1_pct"]), 2),
            "take_profit_2": round(price * (1 + self.config["take_profit_2_pct"]), 2),
            "status": "holding",
        }
        self.state["positions"].append(position)
        self.state["daily_trades"]["count"] += 1
        self._save_state()
        return {"status": "opened", "position": position}

    def close_position(self, stock_code: str, exit_price: float, reason: str = "manual") -> Dict:
        """记录平仓，更新回撤和黑名单。"""
        for i, pos in enumerate(self.state["positions"]):
            if pos["code"] == stock_code and pos["status"] == "holding":
                return_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
                pnl = pos["amount"] * return_pct

                # 更新资金
                self.state["current_capital"] += pnl
                self.state["peak_capital"] = max(self.state["peak_capital"], self.state["current_capital"])

                # 记录交易历史
                trade = {
                    "code": stock_code,
                    "name": pos["name"],
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "return_pct": round(return_pct * 100, 2),
                    "pnl": round(pnl, 2),
                    "reason": reason,
                    "exit_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                self.state["trade_history"].append(trade)

                # 亏损股加入黑名单
                if return_pct < -0.03:
                    unblock = (datetime.now() + timedelta(days=self.config["blacklist_days"])).strftime("%Y-%m-%d")
                    self.state["blacklist"][stock_code] = unblock

                # 检查总回撤
                drawdown = (self.state["peak_capital"] - self.state["current_capital"]) / self.state["peak_capital"]
                if drawdown > self.config["max_drawdown_pct"]:
                    pause_until = (datetime.now() + timedelta(days=self.config["drawdown_pause_days"])).strftime("%Y-%m-%d")
                    self.state["paused_until"] = pause_until

                # 移除持仓
                self.state["positions"].pop(i)
                self._save_state()

                return {
                    "status": "closed",
                    "trade": trade,
                    "drawdown_pct": round(drawdown * 100, 2),
                    "paused": drawdown > self.config["max_drawdown_pct"],
                }

        return {"status": "not_found", "reason": "未找到该持仓"}

    def check_correlation(self, new_stock: Dict, existing_recommendations: List[Dict]) -> Dict:
        """检查新推荐与已有推荐的相关性。

        避免不同策略同时推荐同一只股票，或推荐高度相关的股票。
        """
        # 同一只股票
        for rec in existing_recommendations:
            if rec.get("code") == new_stock.get("code"):
                return {
                    "correlated": True,
                    "reason": "同一只股票已被其他策略推荐",
                    "action": "skip",
                }

        # 同一行业（简单判断：名称包含相同关键词）
        new_name = new_stock.get("name", "")
        for rec in existing_recommendations:
            rec_name = rec.get("name", "")
            # 简单的行业相关性检查（后续可优化）
            common_chars = set(new_name) & set(rec_name)
            if len(common_chars) >= 2 and len(new_name) <= 4:
                return {
                    "correlated": True,
                    "reason": f"与{rec_name}可能同行业，建议分散",
                    "action": "warn",
                }

        return {"correlated": False, "reason": "无明显相关性", "action": "allow"}

    def get_risk_report(self) -> str:
        """生成风控报告。"""
        lines = [
            "🛡️ 风控状态报告",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💰 总资金：{self.config['total_capital']}元",
            f"📈 当前资金：{self.state['current_capital']:.0f}元",
            f"📊 峰值资金：{self.state['peak_capital']:.0f}元",
        ]

        # 回撤
        drawdown = (self.state["peak_capital"] - self.state["current_capital"]) / self.state["peak_capital"] * 100
        drawdown_color = "🟢" if drawdown < 5 else ("🟡" if drawdown < 8 else "🔴")
        lines.append(f"{drawdown_color} 当前回撤：{drawdown:.1f}%")

        # 暂停状态
        if self.state.get("paused_until"):
            lines.append(f"⚠️ 暂停开仓至：{self.state['paused_until']}")

        # 持仓
        lines.append(f"\n📋 当前持仓：{len(self.state['positions'])}/{self.config['max_positions']}只")
        for pos in self.state["positions"]:
            lines.append(f"  {pos['name']}({pos['code']}) 成本{pos['entry_price']}元 | 止损{pos['stop_loss']} | 止盈{pos['take_profit_1']}/{pos['take_profit_2']}")

        # 黑名单
        if self.state["blacklist"]:
            lines.append(f"\n🚫 黑名单：{len(self.state['blacklist'])}只")
            for code, unblock in list(self.state["blacklist"].items())[-3:]:
                lines.append(f"  {code} 至{unblock}")

        # 最近交易
        recent = self.state["trade_history"][-3:]
        if recent:
            lines.append(f"\n📝 最近交易：")
            for t in recent:
                color = "🟢" if t["return_pct"] > 0 else "🔴"
                lines.append(f"  {color} {t['name']} {t['return_pct']}% ({t['reason']})")

        return "\n".join(lines)


def init_risk_controller():
    """初始化风险控制器（带默认策略）。"""
    from .strategy_gate import init_default_strategies
    init_default_strategies()
    return RiskController()
