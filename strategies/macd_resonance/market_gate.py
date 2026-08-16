# -*- coding: utf-8 -*-
"""大盘门控模块（7 分制）。

复用原 V4.3.1 大盘评分逻辑：
- 沪指站上MA20: +2（站上+1，MA20拐头向上+1）
- 两市成交额≥8000亿: +1
- 涨停家数≥30: +1
- 跌停家数<10: +1
- 涨停家数≥50: +2
总分≥4 允许开仓。
"""
from __future__ import annotations

from typing import Tuple

from . import data_source as ds
from .config import MARKET_GATE


def get_market_score() -> Tuple[float, str, bool]:
    """计算大盘评分。

    Returns:
        (分数, 档位描述, 是否允许开仓)
    """
    score = 0.0
    details = []

    # 1. 沪指站上 MA20（+2）
    sh_score, sh_detail = _check_sh_ma20()
    score += sh_score
    details.append(sh_detail)

    # 2. 两市成交额 ≥8000 亿（+1）
    total_amount = ds.get_market_total_amount_yi()
    if total_amount >= 8000:
        score += 1
        details.append(f"✓ 两市成交额{total_amount:.0f}亿≥8000亿(+1)")
    else:
        details.append(f"✗ 两市成交额{total_amount:.0f}亿<8000亿")

    # 3/4/5. 涨停/跌停家数
    up, down = ds.count_limit_up_down()
    if up >= 30:
        score += 1
        details.append(f"✓ 涨停{up}家≥30(+1)")
    else:
        details.append(f"✗ 涨停{up}家<30")
    if down < 10:
        score += 1
        details.append(f"✓ 跌停{down}家<10(+1)")
    else:
        details.append(f"✗ 跌停{down}家≥10")
    if up >= 50:
        score += 2
        details.append(f"✓ 涨停{up}家≥50(+2)")
    else:
        details.append(f"✗ 涨停{up}家<50")

    score = min(score, MARKET_GATE["total_score"])
    can_open = score >= MARKET_GATE["open_threshold"]
    level = "🟢 可开仓" if can_open else "🔴 观望（仅平仓/空仓）"
    description = "\n".join(details) + f"\n▶ 评分 {score:.1f}/{MARKET_GATE['total_score']:.0f} 分 → {level}"
    return score, description, can_open


def _check_sh_ma20() -> Tuple[float, str]:
    """沪指站上 MA20 + MA20 拐头向上。"""
    indices = ds.get_market_indices()
    sh = indices.get("000001")
    if not sh:
        return 0.0, "✗ 无法获取沪指数据"

    kline = ds.get_kline_daily("000001", count=25)
    if len(kline) < 21:
        return 0.0, "✗ 沪指日线数据不足"

    closes = kline["close"].astype(float)
    price = float(sh["price"])
    ma20 = float(closes.iloc[-20:].mean())
    ma20_prev = float(closes.iloc[-21:-1].mean())

    score = 0.0
    parts = []
    if price > ma20:
        score += 1
        parts.append("站上MA20(+1)")
    else:
        parts.append(f"未站上MA20({price:.0f}<{ma20:.0f})")
    if ma20 > ma20_prev:
        score += 1
        parts.append("MA20拐头向上(+1)")
    else:
        parts.append("MA20未拐头")

    return min(score, 2.0), f"{'✓' if score > 0 else '✗'} 沪指: " + ", ".join(parts)
