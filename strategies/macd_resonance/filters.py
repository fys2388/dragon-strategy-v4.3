# -*- coding: utf-8 -*-
"""硬过滤层模块。

一票否决制：满足任意一条直接排除。
"""
from __future__ import annotations

from typing import Tuple

from .config import HARD_FILTERS


def is_mainboard(code: str) -> bool:
    """沪深主板：60/00 开头。"""
    return code.startswith(("60", "00"))


def is_st(name: str) -> bool:
    """ST / *ST / 退市整理。"""
    return "ST" in name.upper() or "退" in name


def pass_hard_filters(stock_info: dict) -> Tuple[bool, str]:
    """硬过滤一票否决。

    Args:
        stock_info: 需含 code/name/price/float_cap_yi/amount_yi

    Returns:
        (是否通过, 拒绝原因)
    """
    code = str(stock_info.get("code", ""))
    name = str(stock_info.get("name", ""))

    # 1. 非主板排除
    if not is_mainboard(code):
        return False, f"{code} 非沪深主板"

    # 2. ST/退市排除
    if is_st(name):
        return False, f"{code} ST/退市风险"

    # 3. 股价范围
    price = float(stock_info.get("price", 0) or 0)
    if price < HARD_FILTERS["price_min"] or price > HARD_FILTERS["price_max"]:
        return False, f"{code} 价格{price:.2f}元不在{HARD_FILTERS['price_min']}-{HARD_FILTERS['price_max']}元"

    # 4. 流通市值范围
    cap = float(stock_info.get("float_cap_yi", 0) or 0)
    if cap < HARD_FILTERS["cap_min_yi"] or cap > HARD_FILTERS["cap_max_yi"]:
        return False, f"{code} 流通市值{cap:.1f}亿不在{HARD_FILTERS['cap_min_yi']}-{HARD_FILTERS['cap_max_yi']}亿"

    # 5. 近20日日均成交额（单位：万元）。实时成交额不可用时跳过（不阻断）
    amount_20d = float(stock_info.get("amount_20d_wan", 0) or 0)
    if amount_20d > 0 and amount_20d < HARD_FILTERS["amount_20d_min"]:
        return False, f"{code} 20日日均成交{amount_20d:.0f}万<{HARD_FILTERS['amount_20d_min']:.0f}万"

    # 6. 近20日累计振幅（上限）。数据缺失时跳过（不阻断）
    amplitude_20d = float(stock_info.get("amplitude_20d_pct", 0) or 0)
    if amplitude_20d > 0 and amplitude_20d > HARD_FILTERS["amplitude_20d_max"]:
        return False, f"{code} 20日振幅{amplitude_20d:.1f}%>{HARD_FILTERS['amplitude_20d_max']:.0f}%"

    # 7. 未来3个月大额解禁（≥总股本5%）—— 数据源无法获取时跳过不阻断
    unlock_pct = float(stock_info.get("unlock_pct_3m", 0) or 0)
    if unlock_pct >= 5.0:
        return False, f"{code} 3个月内解禁{unlock_pct:.1f}%≥5%"

    return True, f"{code} 硬过滤通过"
