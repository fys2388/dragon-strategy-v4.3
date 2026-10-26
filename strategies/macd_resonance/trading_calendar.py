# -*- coding: utf-8 -*-
"""交易时段判断（北京时间）。

时区：UTC+8 固定偏移（使用标准库 timezone，不依赖系统 tzdata，跨平台一致）
交易时段：
  - 盘前：09:00-09:30（允许盘前扫描）
  - 上午：09:30-11:30
  - 下午：13:00-15:00
  - 收盘后：15:00-16:00（允许复盘）

非交易时段：11:30-13:00（午休）、15:00-09:00（夜间）

节假日：维护 A 股休市日历，非交易日返回 False（含周末 + 法定节假日）。
"""
from __future__ import annotations

from datetime import datetime, date, time, timedelta, timezone
from typing import Optional

# 北京时间固定 UTC+8，使用标准库 timezone（不依赖系统 tzdata，跨平台一致）
BJT = timezone(timedelta(hours=8))

# =============================================================================
# A 股休市日历（数据来源：交易所公告，每年1月由证监会发布次年安排）
# 格式：{年份: [休市日期, ...]}
# 覆盖未来两年；每年年底需更新下一年日历。
# =============================================================================
HOLIDAYS: dict[int, set[date]] = {
    2026: {
        # 元旦
        date(2026, 1, 1),  # 周四
        date(2026, 1, 2),  # 周五
        date(2026, 1, 3),  # 周六（补休）
        # 春节（农历新年 2/17）
        date(2026, 2, 16),  # 周一
        date(2026, 2, 17),  # 周二
        date(2026, 2, 18),  # 周三
        date(2026, 2, 19),  # 周四
        date(2026, 2, 20),  # 周五
        # 清明节
        date(2026, 4, 3),   # 周五
        date(2026, 4, 4),   # 周六（清明）
        date(2026, 4, 5),   # 周日
        # 劳动节
        date(2026, 5, 1),   # 周五
        date(2026, 5, 2),   # 周六
        date(2026, 5, 3),   # 周日
        date(2026, 5, 4),   # 周一
        # 端午节
        date(2026, 6, 19),  # 周五（端午）
        date(2026, 6, 20),  # 周六
        date(2026, 6, 21),  # 周日
        # 中秋节
        date(2026, 9, 25),  # 周五（中秋）
        date(2026, 9, 26),  # 周六
        date(2026, 9, 27),  # 周日
        # 国庆节 + 中秋
        date(2026, 10, 1),  # 周四
        date(2026, 10, 2),  # 周五
        date(2026, 10, 5),  # 周一
        date(2026, 10, 6),  # 周二
        date(2026, 10, 7),  # 周三
    },
    2027: {
        # 元旦
        date(2027, 1, 1),  # 周六
        date(2027, 1, 2),  # 周日
        date(2027, 1, 4),  # 周一（补休）
        # 春节（农历新年 2/6）
        date(2027, 2, 8),  # 周日
        date(2027, 2, 10),  # 周二
        date(2027, 2, 11),  # 周三
        date(2027, 2, 12),  # 周四
        date(2027, 2, 13),  # 周五
        # 清明节
        date(2027, 4, 4),  # 周日（清明）
        date(2027, 4, 5),  # 周一
        # 劳动节
        date(2027, 5, 1),  # 周六
        date(2027, 5, 3),  # 周一（补休）
        date(2027, 5, 4),  # 周二
        date(2027, 5, 5),  # 周三
        # 端午节
        date(2027, 6, 9),  # 周三（端午）
        date(2027, 6, 10),  # 周四
        date(2027, 6, 11),  # 周五
        # 中秋节
        date(2027, 9, 15),  # 周三（中秋）
        date(2027, 9, 16),  # 周四
        date(2027, 9, 17),  # 周五
        # 国庆节
        date(2027, 10, 1),  # 周五
        date(2027, 10, 4),  # 周一
        date(2027, 10, 5),  # 周二
        date(2027, 10, 6),  # 周三
        date(2027, 10, 7),  # 周四
    },
}


def is_holiday(d: date | datetime | None = None) -> bool:
    """判断给定日期是否为 A 股休市日（法定节假日或周末）。

    Args:
        d: 日期对象；None 时使用北京时间当前日期。
    Returns:
        True 表示休市（含周末）。
    """
    now = d or now_bjt()
    dt = now.date() if isinstance(now, datetime) else now
    year = dt.year
    # 周末
    if dt.weekday() >= 5:
        return True
    # 法定节假日
    return dt in HOLIDAYS.get(year, set())


def is_trading_day(d: date | datetime | None = None) -> bool:
    """判断给定日期是否为 A 股交易日（非周末且非法定假日）。"""
    return not is_holiday(d)


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
    """判断当前是否为 A 股交易时段（盘中）。非交易日（周末/节假日）返回 False。"""
    now = now or now_bjt()
    if is_holiday(now):
        return False
    t = now.time()
    # 上午 9:30-11:30 或 下午 13:00-15:00
    return (_MORNING_START <= t <= _MORNING_END) or (_AFTERNOON_START <= t <= _AFTERNOON_END)


def is_premarket(now: Optional[datetime] = None) -> bool:
    """判断是否为盘前窗口（9:00-9:30）。非交易日返回 False。"""
    now = now or now_bjt()
    if is_holiday(now):
        return False
    t = now.time()
    return _PREMARKET_START <= t <= _PREMARKET_END


def is_aftermarket(now: Optional[datetime] = None) -> bool:
    """判断是否为收盘后窗口（15:00-16:00）。非交易日返回 False。"""
    now = now or now_bjt()
    if is_holiday(now):
        return False
    t = now.time()
    return _POSTMARKET_START <= t <= _POSTMARKET_END


def is_scan_window(now: Optional[datetime] = None) -> bool:
    """判断是否在可扫描窗口（盘前 + 盘中 + 收盘后）。非交易日返回 False。"""
    now = now or now_bjt()
    if is_holiday(now):
        return False
    t = now.time()
    # 盘前 9:00-9:30 或 盘中 9:30-11:30/13:00-15:00 或 收盘后 15:00-16:00
    return (_PREMARKET_START <= t <= _MORNING_END) or \
           (_AFTERNOON_START <= t <= _POSTMARKET_END)


def get_current_session(now: Optional[datetime] = None) -> str:
    """返回当前时段名称。非交易日返回 'closed'。"""
    now = now or now_bjt()
    if is_holiday(now):
        return "closed"
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
