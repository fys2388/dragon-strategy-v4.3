# -*- coding: utf-8 -*-
"""市场环境自动标注。

classify_regime(market_data) -> str：
- "strong_trend"  强趋势：涨停>80 且 跌停<5
- "weak_trend"    偏强：涨停30-80 且 跌停<10
- "range_bound"   震荡：涨停10-30
- "extreme"       极端：跌停>20 或 指数涨跌>3%
判定优先级：extreme > strong_trend > weak_trend > range_bound
"""
from __future__ import annotations

from typing import Optional

from .data_validator import MarketData

REGIME_LABELS = {
    "strong_trend": "强势",
    "weak_trend": "偏强",
    "range_bound": "震荡",
    "extreme": "极端",
}


def classify_regime(market_data: Optional[MarketData]) -> str:
    """按规则分类市场环境，数据缺失时返回 range_bound。"""
    if market_data is None:
        return "range_bound"

    up = int(market_data.limit_up_count or 0)
    down = int(market_data.limit_down_count or 0)
    chg = float(market_data.index_change_pct or 0)

    # 极端优先
    if down > 20 or abs(chg) > 3.0:
        return "extreme"
    if up > 80 and down < 5:
        return "strong_trend"
    if 30 <= up <= 80 and down < 10:
        return "weak_trend"
    if 10 <= up < 30:
        return "range_bound"
    # 涨停<10 且无极端：按弱势兜底
    return "weak_trend" if up >= 5 else "range_bound"
