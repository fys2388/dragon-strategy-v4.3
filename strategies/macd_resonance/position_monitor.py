# -*- coding: utf-8 -*-
"""持仓监控模块。

核心能力：
1. 读取用户实际持仓配置
2. 实时获取持仓股票现价
3. 计算盈亏、止损止盈距离
4. 触发止损/止盈预警推送
5. 与风险控制器联动（持仓数量限制、回撤控制）
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSITIONS_FILE = os.path.join(BASE_DIR, "data", "positions.json")


class PositionMonitor:
    """持仓监控器。"""

    def __init__(self):
        self.positions = self._load_positions()

    def _load_positions(self) -> Dict:
        try:
            if os.path.exists(POSITIONS_FILE):
                with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"capital": 5000, "positions": [], "updated_at": None}

    def _save_positions(self):
        self.positions["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.positions, f, ensure_ascii=False, indent=2)

    def get_current_prices(self) -> Dict[str, float]:
        """获取持仓股票现价。"""
        from . import data_source as ds
        prices = {}
        for pos in self.positions.get("positions", []):
            try:
                df = ds.get_kline_daily(pos["code"], count=1)
                if not df.empty:
                    prices[pos["code"]] = float(df["close"].iloc[-1])
            except Exception as e:
                print(f"⚠️ 获取{pos['name']}现价失败: {e}")
        return prices

    def monitor(self) -> Dict[str, Any]:
        """监控持仓，返回预警信息。"""
        prices = self.get_current_prices()
        alerts = []
        position_details = []

        total_market_value = 0
        total_cost = 0
        total_pnl = 0

        for pos in self.positions.get("positions", []):
            code = pos["code"]
            name = pos["name"]
            shares = pos["shares"]
            entry_price = pos.get("entry_price", 0)
            current_price = prices.get(code, 0)

            if current_price <= 0:
                position_details.append({
                    "code": code, "name": name, "shares": shares,
                    "current_price": 0, "pnl_pct": 0, "status": "数据获取失败",
                })
                continue

            market_value = current_price * shares
            cost = entry_price * shares if entry_price > 0 else 0
            pnl = market_value - cost if cost > 0 else 0
            pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0

            total_market_value += market_value
            total_cost += cost
            total_pnl += pnl

            # 止损止盈检查
            stop_loss_price = entry_price * (1 - pos.get("stop_loss_pct", 0.05)) if entry_price > 0 else 0
            take_profit_price = entry_price * (1 + pos.get("take_profit_pct", 0.08)) if entry_price > 0 else 0

            status = "持有"
            alert_level = None

            if entry_price > 0:
                if current_price <= stop_loss_price:
                    status = "🔴 触发止损"
                    alert_level = "stop_loss"
                    alerts.append({
                        "code": code, "name": name, "level": "stop_loss",
                        "message": f"{name}({code})现价{current_price:.2f}元，已跌破止损价{stop_loss_price:.2f}元（亏损{pnl_pct:.1f}%），建议止损！",
                    })
                elif current_price >= take_profit_price:
                    status = "🟢 达到止盈"
                    alert_level = "take_profit"
                    alerts.append({
                        "code": code, "name": name, "level": "take_profit",
                        "message": f"{name}({code})现价{current_price:.2f}元，已达到止盈价{take_profit_price:.2f}元（盈利{pnl_pct:.1f}%），建议止盈！",
                    })
                elif pnl_pct <= -3:
                    status = "🟡 接近止损"
                    alert_level = "warning"
                elif pnl_pct >= 5:
                    status = "🟢 接近止盈"

            position_details.append({
                "code": code,
                "name": name,
                "shares": shares,
                "entry_price": entry_price,
                "current_price": current_price,
                "market_value": round(market_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "stop_loss_price": round(stop_loss_price, 2),
                "take_profit_price": round(take_profit_price, 2),
                "status": status,
                "alert_level": alert_level,
            })

        # 总仓位检查
        capital = self.positions.get("capital", 5000)
        position_ratio = total_market_value / capital * 100 if capital > 0 else 0

        return {
            "positions": position_details,
            "alerts": alerts,
            "summary": {
                "total_market_value": round(total_market_value, 2),
                "total_cost": round(total_cost, 2),
                "total_pnl": round(total_pnl, 2),
                "position_ratio": round(position_ratio, 1),
                "position_count": len(self.positions.get("positions", [])),
                "capital": capital,
            },
        }

    def build_monitor_message(self, monitor_result: Dict) -> str:
        """生成持仓监控消息。"""
        summary = monitor_result["summary"]
        lines = [
            "💼 持仓监控报告",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💰 总资金：{summary['capital']}元 | 持仓市值：{summary['total_market_value']}元",
            f"📊 仓位：{summary['position_ratio']}% | 持仓数：{summary['position_count']}只",
        ]

        if summary["total_cost"] > 0:
            pnl_color = "🟢" if summary["total_pnl"] >= 0 else "🔴"
            lines.append(f"{pnl_color} 总盈亏：{summary['total_pnl']}元")

        lines.append("")
        lines.append("【持仓明细】")

        for pos in monitor_result["positions"]:
            if pos.get("current_price", 0) <= 0:
                lines.append(f"  {pos['name']}({pos['code']})：数据获取失败")
                continue

            pnl_color = "🟢" if pos["pnl_pct"] >= 0 else "🔴"
            lines.append(f"  {pos['name']}({pos['code']}) {pos['shares']}股")
            lines.append(f"    现价{pos['current_price']:.2f}元 | 成本{pos['entry_price']:.2f}元 | {pnl_color}{pos['pnl_pct']}% ({pos['pnl']}元)")
            if pos.get("stop_loss_price", 0) > 0:
                lines.append(f"    止损{pos['stop_loss_price']:.2f}元 | 止盈{pos['take_profit_price']:.2f}元 | {pos['status']}")

        # 预警
        alerts = monitor_result.get("alerts", [])
        if alerts:
            lines.append("")
            lines.append("⚠️ 预警：")
            for alert in alerts:
                lines.append(f"  {alert['message']}")

        lines.append("")
        lines.append("⏱ 监控时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return "\n".join(lines)

    def add_position(self, code: str, name: str, shares: int, entry_price: float,
                     stop_loss_pct: float = 0.05, take_profit_pct: float = 0.08):
        """添加持仓。"""
        # 检查是否已存在
        for pos in self.positions["positions"]:
            if pos["code"] == code:
                return {"status": "exists", "message": f"{name}已在持仓中"}

        self.positions["positions"].append({
            "code": code,
            "name": name,
            "shares": shares,
            "entry_price": entry_price,
            "entry_date": datetime.now().strftime("%Y-%m-%d"),
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        })
        self._save_positions()
        return {"status": "added", "message": f"已添加{name}{shares}股"}

    def remove_position(self, code: str):
        """移除持仓。"""
        before = len(self.positions["positions"])
        self.positions["positions"] = [p for p in self.positions["positions"] if p["code"] != code]
        after = len(self.positions["positions"])
        self._save_positions()
        return {"status": "removed" if after < before else "not_found", "removed": before - after}


def init_position_monitor() -> PositionMonitor:
    """初始化持仓监控器。"""
    return PositionMonitor()
