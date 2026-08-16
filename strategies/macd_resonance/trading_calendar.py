# -*- coding: utf-8 -*-
"""交易时段判断（北京时间）。

周一至周五 9:30-11:30, 13:00-15:00 返回 True。
节假日暂不判断（后续可接入交易日历）。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

BJT = timezone(timedelta(hours=8))

_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 0)
_AFTERNOON_END = time(15, 0)


def is_trading_time(now: datetime | None = None) -> bool:
    """判断当前是否为 A 股交易时段。"""
    now = now or datetime.now(BJT)
    if now.weekday() >= 5:  # 周六日
        return False
    t = now.time()
    if _MORNING_START <= t <= _MORNING_END:
        return True
    if _AFTERNOON_START <= t <= _AFTERNOON_END:
        return True
    return False


def now_bjt() -> datetime:
    """当前北京时间。"""
    return datetime.now(BJT)
