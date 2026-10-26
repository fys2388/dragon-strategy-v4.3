# -*- coding: utf-8 -*-
"""持仓管理器模块。

负责：
- 加载持仓（data/portfolio_data.json）
- 检查离场信号（优先级：硬止损 > 日线DIF破零轴 > 60min死叉+顶背离 > 止盈1 > 止盈2）
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import data_source as ds
from .config import RISK, ZERO_AXIS_EPS
from .macd_indicator import calc_macd, check_bullish_divergence, is_death_cross


@dataclass
class ExitSignal:
    code: str
    name: str
    signal_type: str       # hard_stop / zero_axis_break / tf60_divergence / take_profit_1 / take_profit_2
    reason: str
    current_price: float
    profit_pct: float
    suggestion: str


class PortfolioManager:
    """持仓与离场信号管理。"""

    def __init__(self, portfolio_file: Optional[str] = None):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # 优先读取 data/portfolio_data.json（V1.0 格式），兼容根目录旧文件
        candidates = [
            portfolio_file,
            os.path.join(self.base_dir, "data", "portfolio_data.json"),
            os.path.join(self.base_dir, "portfolio_data.json"),
        ]
        self.portfolio_file = next((p for p in candidates if p and os.path.exists(p)),
                                   candidates[1] if candidates else None)

    def load_portfolio(self) -> dict:
        """加载持仓数据。"""
        if not self.portfolio_file or not os.path.exists(self.portfolio_file):
            return {"positions": [], "cash": 0.0, "total_capital": 0.0}
        try:
            with open(self.portfolio_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"positions": [], "cash": 0.0, "total_capital": 0.0}

    def load_positions(self) -> List[Dict]:
        return self.load_portfolio().get("positions", [])

    # ----------------------------------------------------------
    # 单只持仓离场判断
    # ----------------------------------------------------------
    def check_position(self, pos: Dict, quote: Dict) -> Optional[ExitSignal]:
        """检查单只持仓的离场信号。

        优先级：硬止损(-5%) > 日线DIF破零轴 > 60min死叉+顶背离 > 止盈1(+10%) > 止盈2(+15%)
        """
        code = str(pos.get("code", ""))
        name = str(pos.get("name", code))
        entry_price = float(pos.get("entry_price", 0) or 0)
        current_price = float(quote.get("price", 0) or 0)
        if entry_price <= 0 or current_price <= 0:
            return None

        profit_pct = (current_price - entry_price) / entry_price * 100

        # 1. 硬止损（最高优先级）
        if profit_pct <= -RISK["stop_loss_pct"] * 100:
            return ExitSignal(code=code, name=name, signal_type="hard_stop",
                              reason=f"浮亏{profit_pct:.1f}%≤-{RISK['stop_loss_pct'] * 100:.0f}%（硬止损）",
                              current_price=current_price, profit_pct=round(profit_pct, 2),
                              suggestion="立即清仓")

        # 2. 日线 DIF 破零轴
        df_d, dif_d, _, _ = self._tf_macd(code, "daily")
        if not df_d.empty and len(dif_d) > 0 and not _isna(dif_d.iloc[-1]):
            if float(dif_d.iloc[-1]) < -ZERO_AXIS_EPS:
                return ExitSignal(code=code, name=name, signal_type="zero_axis_break",
                                  reason=f"日线DIF {dif_d.iloc[-1]:.3f} 跌破零轴",
                                  current_price=current_price, profit_pct=round(profit_pct, 2),
                                  suggestion="离场观望")

        # 3. 60min 死叉 + 顶背离
        df_60, dif_60, dea_60, _ = self._tf_macd(code, "60m")
        if not df_60.empty and len(df_60) >= 30 and is_death_cross(dif_60, dea_60):
            if check_bullish_divergence(df_60["close"], dif_60):
                return ExitSignal(code=code, name=name, signal_type="tf60_divergence",
                                  reason="60min死叉+顶背离",
                                  current_price=current_price, profit_pct=round(profit_pct, 2),
                                  suggestion="减仓离场")

        # 4. 止盈2（+15% 清仓）——先于止盈1判断（更高级别）
        if profit_pct >= RISK["take_profit_2_pct"] * 100:
            return ExitSignal(code=code, name=name, signal_type="take_profit_2",
                              reason=f"浮盈{profit_pct:.1f}%≥{RISK['take_profit_2_pct'] * 100:.0f}%",
                              current_price=current_price, profit_pct=round(profit_pct, 2),
                              suggestion="全部清仓")

        # 5. 止盈1（+10% 卖半仓）
        if profit_pct >= RISK["take_profit_1_pct"] * 100:
            return ExitSignal(code=code, name=name, signal_type="take_profit_1",
                              reason=f"浮盈{profit_pct:.1f}%≥{RISK['take_profit_1_pct'] * 100:.0f}%",
                              current_price=current_price, profit_pct=round(profit_pct, 2),
                              suggestion="卖出50%仓位")

        return None

    def check_exit_signals(self, positions: Optional[List[Dict]] = None,
                           quotes: Optional[Dict[str, Dict]] = None) -> List[ExitSignal]:
        """批量检查持仓离场信号。"""
        positions = positions if positions is not None else self.load_positions()
        if not positions:
            return []
        codes = [str(p.get("code", "")) for p in positions if p.get("code")]
        if quotes is None:
            quotes = ds.get_realtime_quotes(codes) if codes else {}
        signals = []
        for pos in positions:
            code = str(pos.get("code", ""))
            quote = quotes.get(code, {})
            sig = self.check_position(pos, quote)
            if sig:
                signals.append(sig)
        # 按优先级排序：hard_stop > zero_axis_break > tf60_divergence > take_profit_2 > take_profit_1
        order = {"hard_stop": 0, "zero_axis_break": 1, "tf60_divergence": 2, "take_profit_2": 3, "take_profit_1": 4}
        signals.sort(key=lambda s: order.get(s.signal_type, 9))
        return signals

    def _tf_macd(self, code: str, period: str):
        df = ds.get_kline(code, period, 200 if period == "60m" else 120)
        if df.empty or len(df) < 30:
            return df, None, None, None
        df = calc_macd(df)
        return df, df["dif"], df["dea"], df["macd"]


def _isna(v) -> bool:
    try:
        import pandas as pd
        return bool(pd.isna(v))
    except Exception:
        return v is None
