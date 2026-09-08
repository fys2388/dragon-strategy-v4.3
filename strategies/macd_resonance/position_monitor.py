# -*- coding: utf-8 -*-
"""持仓监控模块（融合黄阳买卖一致性原则）。

核心能力：
1. 读取用户实际持仓配置
2. 实时获取持仓股票现价
3. 计算盈亏、止损止盈距离
4. 触发止损/止盈预警推送
5. 与风险控制器联动（持仓数量限制、回撤控制）
6. 买卖一致性检查（黄阳原则）：买入理由消失就卖出，不因涨跌改变判断
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

    def _check_buy_reason(self, pos: Dict, current_price: float) -> Dict[str, Any]:
        """买卖一致性检查（黄阳原则）：买入理由消失就卖出。

        黄阳核心观点：买入一只股票是因为某个理由（低估/成长/趋势突破），
        当这个理由消失时就应该卖出，不能因为涨了就舍不得卖，
        也不能因为跌了就死扛。

        检查逻辑：
        - 突破策略：检查是否仍在20日均线之上、是否仍突破20日新高
        - MACD共振：检查MACD是否仍金叉、是否仍在零轴之上
        - 超跌反弹：检查反弹是否失效（跌破支撑位）
        - 通用：检查20日均线是否跌破（熊猫有财核心规则）

        Returns:
            {valid: bool, reason: str, disappeared: [消失的理由]}
        """
        from . import data_source as ds
        code = pos["code"]
        name = pos["name"]
        buy_reason = pos.get("buy_reason", {})
        strategy = buy_reason.get("strategy", "unknown")

        disappeared = []
        try:
            df = ds.get_kline_daily(code, count=30)
            if df.empty or len(df) < 20:
                return {"valid": True, "reason": "数据不足，无法检查", "disappeared": []}

            closes = df["close"].astype(float)
            current = float(closes.iloc[-1])
            ma20 = float(closes.iloc[-20:].mean())

            # 通用检查：20日均线（熊猫有财核心规则）
            if current < ma20:
                disappeared.append(f"跌破20日均线(现价{current:.2f}<MA20 {ma20:.2f})")

            # 突破策略检查
            if strategy == "breakout":
                highs = df["high"].astype(float)
                recent_high = float(highs.iloc[-21:-1].max()) if len(highs) >= 21 else float(highs.max())
                if current < recent_high * 0.97:
                    disappeared.append(f"跌破突破位(现价{current:.2f}<突破位{recent_high:.2f}的97%)")
                # 量能检查
                volumes = df["volume"].astype(float)
                if len(volumes) >= 6:
                    avg_vol_5d = float(volumes.iloc[-6:-1].mean())
                    today_vol = float(volumes.iloc[-1])
                    if today_vol < avg_vol_5d * 0.7:
                        disappeared.append("量能萎缩(今日成交量<5日均量70%)")

            # MACD共振策略检查
            elif strategy == "macd_resonance":
                try:
                    from .macd_indicator import calc_macd
                    macd_result = calc_macd(closes.tolist())
                    dif = macd_result.get("dif", [0])[-1]
                    dea = macd_result.get("dea", [0])[-1]
                    if dif < dea:
                        disappeared.append("MACD死叉(DIF<DEA)")
                    if dif < 0:
                        disappeared.append("DIF跌破零轴")
                except Exception:
                    pass

            # 超跌反弹策略检查
            elif strategy == "oversold":
                # 反弹失效：从低点反弹后又跌回低点附近
                lows = df["low"].astype(float)
                recent_low = float(lows.iloc[-20:].min())
                if current < recent_low * 1.03:
                    disappeared.append(f"反弹失效(现价{current:.2f}接近低点{recent_low:.2f})")

        except Exception as e:
            return {"valid": True, "reason": f"检查异常: {e}", "disappeared": []}

        if disappeared:
            return {
                "valid": False,
                "reason": f"买入理由消失：{'、'.join(disappeared)}",
                "disappeared": disappeared,
            }
        return {"valid": True, "reason": "买入理由仍然成立", "disappeared": []}

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

            # 止损止盈检查（含移动止盈Trailing Stop）
            base_stop_loss = entry_price * (1 - pos.get("stop_loss_pct", 0.05)) if entry_price > 0 else 0
            take_profit_price = entry_price * (1 + pos.get("take_profit_pct", 0.08)) if entry_price > 0 else 0

            # 移动止盈：获取持仓期间最高价，动态调整止损线
            trailing_stop_price = base_stop_loss
            highest_since_entry = current_price
            try:
                from . import data_source as _ds
                _df = _ds.get_kline_daily(code, count=60)
                if not _df.empty and len(_df) > 5:
                    _closes = _df["close"].astype(float).tolist()
                    # 取最近30天最高价作为持仓期间最高价参考
                    highest_since_entry = max(_closes[-30:]) if len(_closes) >= 30 else max(_closes)
                    pnl_at_high = (highest_since_entry - entry_price) / entry_price * 100 if entry_price > 0 else 0
                    if pnl_at_high >= 8:
                        # 盈利超过8%后，从最高价回撤3%卖出（让利润奔跑）
                        trailing_stop_price = highest_since_entry * 0.97
                    elif pnl_at_high >= 5:
                        # 盈利超过5%后，止损线上移到成本价（保本）
                        trailing_stop_price = entry_price
            except Exception:
                pass

            # 实际止损价取基础止损和移动止损的较高者
            stop_loss_price = max(base_stop_loss, trailing_stop_price) if entry_price > 0 else 0

            # 买卖一致性检查（黄阳原则）
            buy_reason_check = self._check_buy_reason(pos, current_price)

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
                elif not buy_reason_check["valid"]:
                    # 黄阳买卖一致性：买入理由消失，优先级仅次于硬止损
                    status = "🟡 买入理由消失"
                    alert_level = "buy_reason_gone"
                    alerts.append({
                        "code": code, "name": name, "level": "buy_reason_gone",
                        "message": f"{name}({code}){buy_reason_check['reason']}，按买卖一致性原则建议卖出（不因涨跌改变判断）",
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
                "buy_reason_valid": buy_reason_check["valid"],
                "buy_reason_detail": buy_reason_check["reason"],
                "trailing_active": trailing_stop_price > base_stop_loss if entry_price > 0 else False,
                "highest_since_entry": round(highest_since_entry, 2),
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
                trailing_note = ""
                if pos.get("trailing_active"):
                    trailing_note = " [移动止盈中]"
                lines.append(f"    止损{pos['stop_loss_price']:.2f}元 | 止盈{pos['take_profit_price']:.2f}元 | {pos['status']}{trailing_note}")
            # 买卖一致性检查（黄阳原则）
            if not pos.get("buy_reason_valid", True):
                lines.append(f"    🟡 买卖一致性：{pos.get('buy_reason_detail', '买入理由消失')}")

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
