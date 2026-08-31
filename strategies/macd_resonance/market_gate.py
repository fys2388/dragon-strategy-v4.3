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

from typing import Optional, Tuple

from . import data_source as ds
from .data_source import get_limit_up_down_count  # noqa: F401  (re-export, 供外部验证命令导入)
from .config import MARKET_GATE


def get_market_score(market_data: Optional[object] = None) -> Tuple[float, str, bool]:
    """计算大盘评分。

    V2.0 新增：
    - 减分项：跌停≥20家 -1，沪指跌幅≥1% -1
    - 系统性风险熔断：沪指跌≥1.5% / 跌停≥30 / 涨跌比≥10:1 → 直接0分禁止开仓

    传入 MarketData（数据自驱层选中源）时，成交额/涨跌停使用传入值；
    未传入时走东财原始拉取（兼容旧调用）。

    Args:
        market_data: data_validator.MarketData 或 None。

    Returns:
        (分数, 档位描述, 是否允许开仓)
    """
    score = 0.0
    details = []

    # 0. 系统性风险前置熔断（触发直接0分，禁止开仓）
    if market_data is not None:
        idx_chg = float(getattr(market_data, 'index_change_pct', 0) or 0)
        up = int(getattr(market_data, 'limit_up_count', 0) or 0)
        down = int(getattr(market_data, 'limit_down_count', 0) or 0)
        if idx_chg <= -1.5 or down >= 30 or (up > 0 and down / up >= 10):
            reason = []
            if idx_chg <= -1.5: reason.append(f"沪指跌{idx_chg:.1f}%≥1.5%")
            if down >= 30: reason.append(f"跌停{down}家≥30")
            if up > 0 and down / up >= 10: reason.append(f"涨跌比{down}:{up}≥10:1")
            details.append(f"🚨 系统性风险熔断：{'、'.join(reason)}")
            description = "\n".join(details) + "\n▶ 评分 0.0/7.0 分 → 🔴 禁止开仓"
            return 0.0, description, False

    # 1. 沪指站上 MA20（+2）
    sh_score, sh_detail = _check_sh_ma20()
    score += sh_score
    details.append(sh_detail)

    # 2. 两市成交额 ≥8000 亿（+1）
    if market_data is not None and market_data.volume_yi > 0:
        total_amount = float(market_data.volume_yi)
    else:
        total_amount = ds.get_market_total_amount_yi()
    if total_amount >= 8000:
        score += 1
        details.append(f"✓ 两市成交额{total_amount:.0f}亿≥8000亿(+1)")
    else:
        details.append(f"✗ 两市成交额{total_amount:.0f}亿<8000亿")

    # 3/4/5. 涨停/跌停家数
    if market_data is not None:
        up = int(market_data.limit_up_count)
        down = int(market_data.limit_down_count)
        idx_chg = float(getattr(market_data, 'index_change_pct', 0) or 0)
    else:
        up, down = get_limit_up_down_count()
        idx_chg = 0.0
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

    # V2.0 减分项
    if down >= 20:
        score -= 1
        details.append(f"✗ 跌停{down}家≥20(-1)")
    if idx_chg <= -1.0:
        score -= 1
        details.append(f"✗ 沪指跌{idx_chg:.1f}%≥1%(-1)")

    score = max(0.0, min(score, MARKET_GATE["total_score"]))
    can_open = score >= MARKET_GATE["open_threshold"]
    if can_open:
        if score >= MARKET_GATE.get("standard_threshold", 4.0):
            level = "🔴 可开仓(标准档)"
        else:
            level = "🟡 可开仓(宽松档)"
    else:
        level = "🟢 观望（仅平仓/空仓）"
    description = "\n".join(details) + f"\n▶ 评分 {score:.1f}/{MARKET_GATE['total_score']:.0f} 分 → {level}"
    return score, description, can_open


def _check_sh_ma20() -> Tuple[float, str]:
    """沪指站上 MA20 + MA20 拐头向上。"""
    indices = ds.get_market_indices()
    sh = indices.get("000001")
    if not sh:
        return 0.0, "✗ 无法获取沪指数据"

    kline = ds.get_kline_daily("000001", count=25, is_index=True)
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
