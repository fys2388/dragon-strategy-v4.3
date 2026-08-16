# -*- coding: utf-8 -*-
"""信号引擎模块。

A股无做空：所有"做空"逻辑改为「空头规避 AVOID」——仅日志记录、从候选池排除，不推送推荐。

信号优先级：LONG_EXIT > LONG_ENTRY > AVOID > HOLD
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

import pandas as pd

from . import data_source as ds
from .config import RISK, SIGNAL, TIMEFRAME_ORDER, ZERO_AXIS_EPS
from .macd_indicator import (above_zero_axis, below_zero_axis, calc_macd,
                             check_bullish_divergence, cross_above_zero,
                             is_death_cross, is_golden_cross, red_bar_expanding)


class SignalType(Enum):
    LONG_ENTRY = "LONG_ENTRY"   # 做多入场
    LONG_EXIT = "LONG_EXIT"     # 多头离场（止盈/止损）
    AVOID = "AVOID"             # 空头规避（原做空逻辑）
    HOLD = "HOLD"               # 持有不动


@dataclass
class SignalResult:
    code: str
    name: str
    signal_type: SignalType
    score: float = 0.0
    reason: str = ""
    price: float = 0.0
    dif_daily: Optional[float] = None
    dif_60m: Optional[float] = None
    dif_30m: Optional[float] = None
    dif_15m: Optional[float] = None
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    resonance_levels: List[str] = field(default_factory=list)


class SignalEngine:
    """MACD 多周期共振信号引擎。"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.portfolio_file = os.path.join(self.base_dir, "portfolio_data.json")

    # ----------------------------------------------------------
    # 持仓读取
    # ----------------------------------------------------------
    def load_positions(self) -> List[Dict]:
        try:
            with open(self.portfolio_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("positions", [])
        except Exception:
            return []

    def _position_for(self, code: str) -> Optional[Dict]:
        for pos in self.load_positions():
            if str(pos.get("code", "")) == code:
                return pos
        return None

    # ----------------------------------------------------------
    # 多周期 MACD 分析
    # ----------------------------------------------------------
    def _tf_macd(self, code: str, period: str, count: int) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        df = ds.get_kline(code, period, count)
        if df.empty or len(df) < 30:
            return df, pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float)
        df = calc_macd(df)
        return df, df["dif"], df["dea"], df["macd"]

    def _last(self, s: pd.Series) -> Optional[float]:
        if s is None or len(s) == 0 or pd.isna(s.iloc[-1]):
            return None
        return float(s.iloc[-1])

    # ----------------------------------------------------------
    # 入场信号
    # ----------------------------------------------------------
    def check_long_entry(self, code: str, name: str, price: float) -> Optional[SignalResult]:
        """检查做多入场条件（C~H，A/B 由 scanner 前置保证）。"""
        reasons = []

        # C. 日线 DIF 在零轴上方或附近
        df_d, dif_d, dea_d, macd_d = self._tf_macd(code, "daily", 120)
        if df_d.empty:
            return None
        dif_d_last = self._last(dif_d)
        if dif_d_last is None or dif_d_last <= -ZERO_AXIS_EPS:
            return None
        reasons.append("日线DIF零轴上方/附近")

        # D. 60分钟：金叉 + DIF>0 + 红柱放大
        df_60, dif_60, dea_60, macd_60 = self._tf_macd(code, "60m", 200)
        if df_60.empty:
            return None
        if not (is_golden_cross(dif_60, dea_60) and self._last(dif_60) and self._last(dif_60) > 0):
            return None
        if not red_bar_expanding(macd_60):
            return None
        reasons.append("60min金叉红柱放大")

        # E. 30分钟：金叉 + DIF>0
        df_30, dif_30, dea_30, _ = self._tf_macd(code, "30m", 200)
        if df_30.empty:
            return None
        if not (is_golden_cross(dif_30, dea_30) and self._last(dif_30) and self._last(dif_30) > 0):
            return None
        reasons.append("30min金叉")

        # F. 15分钟：金叉 + DIF 上穿零轴
        df_15, dif_15, dea_15, _ = self._tf_macd(code, "15m", 200)
        if df_15.empty:
            return None
        if not (is_golden_cross(dif_15, dea_15) and cross_above_zero(dif_15)):
            return None
        reasons.append("15min金叉上穿零轴")

        # G. 量能确认：当日成交量 > 前5日均量 × 1.3
        if len(df_d) < 6:
            return None
        vol_now = float(df_d["volume"].iloc[-1])
        vol_5d = float(df_d["volume"].iloc[-6:-1].mean())
        if vol_5d <= 0 or vol_now <= vol_5d * SIGNAL["volume_ratio_min"]:
            return None
        reasons.append(f"量能{vol_now / vol_5d:.1f}倍")

        # H. 价格突破：收盘价 > 近20根60分钟K线最高价
        if len(df_60) < SIGNAL["breakout_lookback_60m"]:
            return None
        close_now = float(df_d["close"].iloc[-1])
        high_20 = float(df_60["high"].iloc[-SIGNAL["breakout_lookback_60m"]:].max())
        if close_now <= high_20:
            return None
        reasons.append(f"突破60min平台{high_20:.2f}")

        # 共振强度打分：共振周期越多分越高
        score = 1.0
        levels = ["日线", "60min", "30min", "15min"]
        resonance = ["日线", "60min", "30min", "15min"]
        score += 1.0  # 基础分
        if self._last(dif_d) and self._last(dif_d) > ZERO_AXIS_EPS:
            score += 0.5
        score += 0.5 * TIMEFRAME_ORDER.get("60m", 3)

        return SignalResult(
            code=code, name=name, signal_type=SignalType.LONG_ENTRY, score=round(score, 2),
            reason="；".join(reasons), price=round(price, 2),
            dif_daily=dif_d_last, dif_60m=self._last(dif_60),
            dif_30m=self._last(dif_30), dif_15m=self._last(dif_15),
            resonance_levels=resonance,
        )

    # ----------------------------------------------------------
    # 离场信号
    # ----------------------------------------------------------
    def check_long_exit(self, code: str, name: str, price: float, position: Optional[Dict]) -> Optional[SignalResult]:
        """检查多头离场条件（任一满足即离场）。"""
        reasons = []
        entry_price = float(position.get("entry_price", 0)) if position else 0.0

        df_d, dif_d, dea_d, _ = self._tf_macd(code, "daily", 120)
        if df_d.empty:
            return None
        dif_d_last = self._last(dif_d)
        df_60, dif_60, dea_60, _ = self._tf_macd(code, "60m", 200)
        dif_60_last = self._last(dif_60)

        # A. 日线零轴上方死叉
        if dif_d_last and dif_d_last > 0 and is_death_cross(dif_d, dea_d):
            reasons.append("日线零轴上死叉")

        # B. 60分钟死叉 + 顶背离
        if not df_60.empty and is_death_cross(dif_60, dea_60):
            if check_bullish_divergence(df_60["close"], dif_60):
                reasons.append("60min死叉+顶背离")

        # C. 止盈：浮盈≥10% 卖50%；≥15% 清仓
        if entry_price > 0:
            profit = (price - entry_price) / entry_price
            if profit >= RISK["take_profit_2_pct"]:
                reasons.append(f"浮盈{profit * 100:.1f}%≥{RISK['take_profit_2_pct'] * 100:.0f}%清仓")
            elif profit >= RISK["take_profit_1_pct"]:
                reasons.append(f"浮盈{profit * 100:.1f}%≥{RISK['take_profit_1_pct'] * 100:.0f}%减半仓")

            # D. 硬性止损
            if profit <= -RISK["stop_loss_pct"]:
                reasons.append(f"浮亏{profit * 100:.1f}%≤-{RISK['stop_loss_pct'] * 100:.0f}%硬止损")

        # E. 日线 DIF 跌破 -0.05
        if dif_d_last and dif_d_last < -ZERO_AXIS_EPS:
            reasons.append(f"日线DIF{dif_d_last:.3f}跌破零轴")

        if not reasons:
            return None
        return SignalResult(
            code=code, name=name, signal_type=SignalType.LONG_EXIT,
            reason="；".join(reasons), price=round(price, 2),
            dif_daily=dif_d_last, dif_60m=dif_60_last,
        )

    # ----------------------------------------------------------
    # 空头规避（原做空逻辑）
    # ----------------------------------------------------------
    def check_avoid(self, code: str) -> bool:
        """日线 DIF<-0.05 或 60min 死叉且 DIF<0 → 规避。"""
        _, dif_d, _, _ = self._tf_macd(code, "daily", 120)
        _, dif_60, dea_60, _ = self._tf_macd(code, "60m", 200)
        if below_zero_axis(self._last(dif_d)):
            return True
        if not dif_60.empty and is_death_cross(dif_60, dea_60):
            if self._last(dif_60) and self._last(dif_60) < 0:
                return True
        return False

    # ----------------------------------------------------------
    # 主分析入口
    # ----------------------------------------------------------
    def analyze_stock(self, code: str, name: str = "", price: float = 0.0) -> SignalResult:
        """分析单只股票，返回综合信号。

        优先级：LONG_EXIT > LONG_ENTRY > AVOID > HOLD
        """
        if price <= 0:
            quotes = ds.get_realtime_quotes([code])
            price = quotes.get(code, {}).get("price", 0.0)
        if not name:
            quotes = ds.get_realtime_quotes([code])
            name = quotes.get(code, {}).get("name", code)

        position = self._position_for(code)

        # 1. 持仓中优先检查离场
        if position:
            exit_sig = self.check_long_exit(code, name, price, position)
            if exit_sig:
                return exit_sig

        # 2. 入场
        entry_sig = self.check_long_entry(code, name, price)
        if entry_sig:
            return entry_sig

        # 3. 空头规避
        if self.check_avoid(code):
            return SignalResult(code=code, name=name, signal_type=SignalType.AVOID,
                                reason="空头规避：日线DIF零轴下方/60min死叉", price=round(price, 2))

        # 4. 持有/无信号
        return SignalResult(code=code, name=name, signal_type=SignalType.HOLD,
                            reason="无共振信号", price=round(price, 2))
