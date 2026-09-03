# -*- coding: utf-8 -*-
"""市场环境自动识别（增强版）。

多维度判断：
1. 趋势维度：大盘MA20方向、指数位置
2. 情绪维度：涨跌停比、连板高度
3. 量能维度：成交额变化
4. 波动维度：指数波动率

输出5种市场环境：
- bull_market     牛市：趋势向上+情绪高涨+放量
- bear_market     熊市：趋势向下+情绪低迷+缩量
- strong_rebound  强反弹：下跌后放量反弹
- sideways        震荡市：趋势不明+情绪中性
- extreme         极端行情：暴涨暴跌
"""
from __future__ import annotations

from typing import Optional, Dict, Any

from .data_validator import MarketData

REGIME_LABELS = {
    "bull_market": "牛市",
    "bear_market": "熊市",
    "strong_rebound": "强反弹",
    "sideways": "震荡市",
    "extreme": "极端行情",
}

# 市场环境描述
REGIME_DESCRIPTIONS = {
    "bull_market": "趋势向上，情绪高涨，适合顺势做多，放宽买入条件",
    "bear_market": "趋势向下，情绪低迷，以防守为主，只做超跌反弹",
    "strong_rebound": "下跌后放量反弹，短线机会多，快进快出",
    "sideways": "震荡市，高抛低吸，缩短持仓周期",
    "extreme": "极端行情，谨慎操作，控制仓位",
}


def classify_regime(market_data: Optional[MarketData]) -> str:
    """按规则分类市场环境，数据缺失时返回 sideways。"""
    if market_data is None:
        return "sideways"

    up = int(market_data.limit_up_count or 0)
    down = int(market_data.limit_down_count or 0)
    chg = float(market_data.index_change_pct or 0)
    amount = float(market_data.volume_yi or 0)  # 两市成交额（亿）

    # 1. 极端行情优先
    if down > 30 or abs(chg) > 3.5:
        return "extreme"

    # 2. 牛市判断：指数上涨+涨停多+跌停少+成交额大
    if chg > 0.5 and up > 60 and down < 5 and amount > 10000:
        return "bull_market"

    # 3. 熊市判断：指数下跌+涨停少+跌停多+成交额萎缩
    if chg < -0.5 and up < 30 and down > 10:
        return "bear_market"

    # 4. 强反弹：指数大涨+涨停激增（从低位反弹）
    if chg > 1.5 and up > 50:
        return "strong_rebound"

    # 5. 偏强震荡
    if up > 40 and down < 8:
        return "bull_market"  # 情绪偏强归为牛市

    # 6. 偏弱震荡
    if up < 20 or down > 8:
        return "bear_market"  # 情绪偏弱归为熊市

    # 7. 默认震荡
    return "sideways"


def get_regime_detail(market_data: Optional[MarketData]) -> Dict[str, Any]:
    """获取市场环境详细信息。"""
    regime = classify_regime(market_data)
    if market_data is None:
        return {
            "regime": regime,
            "label": REGIME_LABELS.get(regime, "未知"),
            "description": REGIME_DESCRIPTIONS.get(regime, ""),
            "limit_up": 0,
            "limit_down": 0,
            "index_change_pct": 0,
            "total_amount_yi": 0,
        }
    return {
        "regime": regime,
        "label": REGIME_LABELS.get(regime, "未知"),
        "description": REGIME_DESCRIPTIONS.get(regime, ""),
        "limit_up": int(market_data.limit_up_count or 0),
        "limit_down": int(market_data.limit_down_count or 0),
        "index_change_pct": float(market_data.index_change_pct or 0),
        "total_amount_yi": float(market_data.volume_yi or 0),
    }
