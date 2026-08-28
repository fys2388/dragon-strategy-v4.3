# -*- coding: utf-8 -*-
"""交易时段判断（北京时间）。

时区：UTC+8 固定偏移（使用标准库 timezone，不依赖系统 tzdata，跨平台一致）
交易时段：
  - 盘前：09:00-09:30（允许盘前扫描）
  - 上午：09:30-11:30
  - 下午：13:00-15:00
  - 收盘后：15:00-16:00（允许复盘）

非交易时段：11:30-13:00（午休）、15:00-09:00（夜间）
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional

# 北京时间固定 UTC+8，使用标准库 timezone（不依赖系统 tzdata，跨平台一致）
BJT = timezone(timedelta(hours=8))

# 交易时段定义
_MORNING_START = time(9, 0)    # 盘前开始（允许扫描）
_MORNING_END = time(11, 30)    # 上午收盘
_AFTERNOON_START = time(13, 0) # 下午开盘
_AFTERNOON_END = time(15, 0)   # 下午收盘
_EVENING_END = time(15, 59)     # 收盘后允许复盘

# 盘前窗口（9:00-9:30）
_PREMARKET_START = time(9, 0)
_PREMARKET_END = time(9, 30)

# 收盘后窗口（15:00-16:00）
_POSTMARKET_START = time(15, 0)
_POSTMARKET_END = time(15, 59)


def now_bjt() -> datetime:
    """当前北京时间。"""
    return datetime.now(BJT)


def is_trading_time(now: Optional[datetime] = None) -> bool:
    """判断当前是否为 A 股交易时段（盘中）。"""
    now = now or now_bjt()
    if now.weekday() >= 5:  # 周六日
        return False
    t = now.time()
    # 上午 9:30-11:30 或 下午 13:00-15:00
    return (_MORNING_START <= t <= _MORNING_END) or (_AFTERNOON_START <= t <= _AFTERNOON_END)


def is_premarket(now: Optional[datetime] = None) -> bool:
    """判断是否为盘前窗口（9:00-9:30）。"""
    now = now or now_bjt()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return _PREMARKET_START <= t <= _PREMARKET_END


def is_aftermarket(now: Optional[datetime] = None) -> bool:
    """判断是否为收盘后窗口（15:00-16:00）。"""
    now = now or now_bjt()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return _POSTMARKET_START <= t <= _POSTMARKET_END


def is_scan_window(now: Optional[datetime] = None) -> bool:
    """判断是否在可扫描窗口（盘前 + 盘中 + 收盘后）。"""
    now = now or now_bjt()
    if now.weekday() >= 5:
        return False
    t = now.time()
    # 盘前 9:00-9:30 或 盘中 9:30-11:30/13:00-15:00 或 收盘后 15:00-16:00
    return (_PREMARKET_START <= t <= _MORNING_END) or \
           (_AFTERNOON_START <= t <= _POSTMARKET_END)


def get_current_session(now: Optional[datetime] = None) -> str:
    """返回当前时段名称。"""
    now = now or now_bjt()
    t = now.time()
    if _PREMARKET_START <= t <= _PREMARKET_END:
        return "premarket"
    if _MORNING_START <= t <= _MORNING_END:
        return "morning"
    if _AFTERNOON_START <= t <= _AFTERNOON_END:
        return "afternoon"
    if _POSTMARKET_START <= t <= _POSTMARKET_END:
        return "aftermarket"
    return "closed"
