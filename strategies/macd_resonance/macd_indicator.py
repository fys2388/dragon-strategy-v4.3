# -*- coding: utf-8 -*-
"""MACD 指标计算模块。

标准实现：pandas ewm(span=..., adjust=False)，禁止 offset 手工对齐。
参数固定 (fast=10, slow=20, signal=7)。
"""
from __future__ import annotations

import pandas as pd
from typing import Optional

from .config import MACD_FAST, MACD_SLOW, MACD_SIGNAL, ZERO_AXIS_EPS


def calc_macd(df: pd.DataFrame, fast: int = MACD_FAST, slow: int = MACD_SLOW,
              signal: int = MACD_SIGNAL) -> pd.DataFrame:
    """计算 MACD，输入需包含 close 列。

    返回新增列：dif / dea / macd（macd = 2*(dif-dea)，与国内软件一致）。
    数据不足时对应列填 NaN。
    """
    out = df.copy()
    if "close" not in out.columns or len(out) < slow + signal:
        out["dif"] = pd.Series([float("nan")] * len(out), index=out.index)
        out["dea"] = pd.Series([float("nan")] * len(out), index=out.index)
        out["macd"] = pd.Series([float("nan")] * len(out), index=out.index)
        return out

    ema_fast = out["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = out["close"].ewm(span=slow, adjust=False).mean()
    out["dif"] = ema_fast - ema_slow
    out["dea"] = out["dif"].ewm(span=signal, adjust=False).mean()
    out["macd"] = (out["dif"] - out["dea"]) * 2.0
    return out


def is_golden_cross(dif: pd.Series, dea: pd.Series) -> bool:
    """最近一根 K 线是否金叉（DIF 上穿 DEA）。"""
    if len(dif) < 2 or pd.isna(dif.iloc[-2]) or pd.isna(dif.iloc[-1]):
        return False
    return bool(dif.iloc[-2] <= dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1])


def is_death_cross(dif: pd.Series, dea: pd.Series) -> bool:
    """最近一根 K 线是否死叉（DIF 下穿 DEA）。"""
    if len(dif) < 2 or pd.isna(dif.iloc[-2]) or pd.isna(dif.iloc[-1]):
        return False
    return bool(dif.iloc[-2] >= dea.iloc[-2] and dif.iloc[-1] < dea.iloc[-1])


def above_zero_axis(dif_value: Optional[float]) -> bool:
    """DIF 是否在零轴上方（> eps）。"""
    if dif_value is None or pd.isna(dif_value):
        return False
    return float(dif_value) > ZERO_AXIS_EPS


def below_zero_axis(dif_value: Optional[float]) -> bool:
    """DIF 是否在零轴下方深处（< -eps）。"""
    if dif_value is None or pd.isna(dif_value):
        return False
    return float(dif_value) < -ZERO_AXIS_EPS


def cross_above_zero(dif: pd.Series) -> bool:
    """最近一根 K 线 DIF 上穿零轴（前一根 <0，当前 >0）。"""
    if len(dif) < 2 or pd.isna(dif.iloc[-2]) or pd.isna(dif.iloc[-1]):
        return False
    return bool(dif.iloc[-2] < 0 and dif.iloc[-1] > 0)


def red_bar_expanding(macd: pd.Series) -> bool:
    """MACD 红柱放大：当前红柱 > 前一根红柱，且均为正。"""
    if len(macd) < 2 or pd.isna(macd.iloc[-2]) or pd.isna(macd.iloc[-1]):
        return False
    return bool(macd.iloc[-1] > 0 and macd.iloc[-2] > 0 and macd.iloc[-1] > macd.iloc[-2])


def check_bullish_divergence(price: pd.Series, dif: pd.Series) -> bool:
    """60 分钟顶背离：价格创新高但 DIF 未创新高（取最近两段局部高点）。"""
    if len(price) < 30:
        return False
    # 找最近两个价格局部高点（间隔至少 5 根）
    highs = []
    for i in range(3, len(price) - 3):
        if price.iloc[i] == max(price.iloc[i - 3:i + 4]):
            if not highs or i - highs[-1][0] >= 5:
                highs.append((i, float(price.iloc[i]), float(dif.iloc[i])))
    if len(highs) < 2:
        return False
    p1, p2 = highs[-2], highs[-1]
    return bool(p2[1] > p1[1] and p2[2] < p1[2])
