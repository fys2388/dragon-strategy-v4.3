"""
仓位管理

- 单只股票最大仓位 20%
- 同时持有最多 5 只
- 最多 3 个行业
- 分批建仓：1/3 试探，1/3 加仓，1/3 机动
"""

import logging
import json
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path

from config.settings import USER_PROFILE, DATA_DIR

logger = logging.getLogger(__name__)


class PositionManager:
    """仓位管理器"""

    def __init__(self, capital: float = None):
        self.capital = capital or USER_PROFILE["capital"]
        self.max_single_pct = USER_PROFILE["single_stock_max_pct"]
        self.max_holdings = USER_PROFILE["max_holdings"]
        self.max_industries = USER_PROFILE["max_industry_count"]
        self.positions_file = DATA_DIR / "positions.json"
        self.positions = self._load_positions()

    def _load_positions(self) -> List[Dict]:
        """加载持仓"""
        if self.positions_file.exists():
            try:
                with open(self.positions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return []

    def _save_positions(self):
        """保存持仓"""
        self.positions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.positions_file, "w", encoding="utf-8") as f:
            json.dump(self.positions, f, ensure_ascii=False, indent=2)

    def calculate_position_size(self, signal: Dict, current_positions: int = 0) -> Dict:
        """
        计算建仓数量

        Args:
            signal: 信号 dict
            current_positions: 当前持仓数量

        Returns:
            dict with: total_amount, buy_shares, batch_plan
        """
        entry_price = signal["entry_price"]
        stop_loss = signal["stop_loss"]

        # 风险预算：单笔亏损不超过总资金的 2%
        risk_per_trade = self.capital * 0.02
        risk_per_share = entry_price - stop_loss
        max_shares_by_risk = int(risk_per_trade / risk_per_share) if risk_per_share > 0 else 0

        # 单只最大仓位
        max_amount = self.capital * self.max_single_pct
        max_shares_by_capital = int(max_amount / entry_price)

        # 取较小值
        buy_shares = min(max_shares_by_risk, max_shares_by_capital)
        buy_shares = int(buy_shares / 100) * 100  # A股 100 股整数倍
        if buy_shares < 100:
            buy_shares = 100

        total_amount = buy_shares * entry_price

        # 分批计划
        batch_1 = int(buy_shares * 0.4)  # 40% 试探
        batch_2 = int(buy_shares * 0.35)  # 35% 加仓
        batch_3 = buy_shares - batch_1 - batch_2  # 25% 机动

        # 确保每批至少 100 股
        if batch_1 < 100:
            batch_1 = 100
            batch_2 = max(100, buy_shares - batch_1 - 100)
            batch_3 = buy_shares - batch_1 - batch_2

        return {
            "code": signal["code"],
            "name": signal["name"],
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "total_amount": round(total_amount, 2),
            "buy_shares": buy_shares,
            "batch_plan": {
                "batch_1": {"shares": batch_1, "amount": round(batch_1 * entry_price, 2), "desc": "试探建仓"},
                "batch_2": {"shares": batch_2, "amount": round(batch_2 * entry_price, 2), "desc": "确认加仓"},
                "batch_3": {"shares": batch_3, "amount": round(batch_3 * entry_price, 2), "desc": "趋势加仓"},
            },
            "risk_pct": round((entry_price - stop_loss) / entry_price * 100, 2),
            "position_pct": round(total_amount / self.capital * 100, 2),
            "current_positions": current_positions,
            "can_add": current_positions < self.max_holdings,
        }

    def add_position(self, position_info: Dict):
        """添加持仓"""
        self.positions.append(position_info)
        self._save_positions()
        logger.info(f"添加持仓: {position_info['name']} ({position_info['code']})")

    def remove_position(self, code: str):
        """移除持仓"""
        self.positions = [p for p in self.positions if p["code"] != code]
        self._save_positions()
        logger.info(f"移除持仓: {code}")

    def get_positions_summary(self) -> Dict:
        """获取持仓摘要"""
        if not self.positions:
            return {
                "total_positions": 0,
                "total_value": 0,
                "total_cost": 0,
                "total_pnl": 0,
                "positions": [],
            }

        total_cost = sum(p.get("cost", 0) for p in self.positions)
        total_value = sum(p.get("market_value", p.get("cost", 0)) for p in self.positions)
        total_pnl = total_value - total_cost

        return {
            "total_positions": len(self.positions),
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
            "positions": self.positions,
        }

    def check_industry_diversification(self, signals: List[Dict]) -> List[Dict]:
        """检查行业分散度，过滤同行业过多"""
        industries = {}
        filtered = []
        for sig in signals:
            industry = sig.get("industry", "未知")
            if industry not in industries:
                industries[industry] = []
            industries[industry].append(sig)

        # 每个行业最多选 2 只
        for industry, sigs in industries.items():
            filtered.extend(sigs[:2])

        return filtered


# 全局实例
position_manager = PositionManager()
