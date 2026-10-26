# -*- coding: utf-8 -*-
"""交易时段判断单测（纯函数，无网络依赖）。"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.trading_calendar import (  # noqa: E402
    is_trading_time,
    is_premarket,
    is_aftermarket,
    is_scan_window,
    is_holiday,
    is_trading_day,
    get_current_session,
    now_bjt,
)

BJT = timezone(timedelta(hours=8))


class TestTradingCalendar(unittest.TestCase):
    def _t(self, weekday, hour, minute):
        # 2026-08-17 是周一
        base = datetime(2026, 8, 17, hour, minute, tzinfo=BJT)
        return base.replace(day=base.day + weekday)

    def test_morning_session(self):
        self.assertTrue(is_trading_time(self._t(0, 9, 30)))
        self.assertTrue(is_trading_time(self._t(0, 10, 15)))
        self.assertTrue(is_trading_time(self._t(0, 11, 30)))

    def test_afternoon_session(self):
        self.assertTrue(is_trading_time(self._t(0, 13, 0)))
        self.assertTrue(is_trading_time(self._t(0, 14, 59)))

    def test_break_and_off_hours(self):
        self.assertFalse(is_trading_time(self._t(0, 11, 31)))
        self.assertFalse(is_trading_time(self._t(0, 12, 59)))
        self.assertFalse(is_trading_time(self._t(0, 8, 0)))
        self.assertFalse(is_trading_time(self._t(0, 15, 1)))

    def test_weekend(self):
        self.assertFalse(is_trading_time(self._t(5, 10, 0)))  # 周六
        self.assertFalse(is_trading_time(self._t(6, 10, 0)))  # 周日

    def test_premarket_window(self):
        """盘前窗口 9:00-9:30"""
        self.assertTrue(is_premarket(self._t(0, 9, 0)))
        self.assertTrue(is_premarket(self._t(0, 9, 15)))
        self.assertTrue(is_premarket(self._t(0, 9, 29)))
        self.assertFalse(is_premarket(self._t(0, 9, 31)))
        self.assertFalse(is_premarket(self._t(0, 10, 0)))

    def test_aftermarket_window(self):
        """收盘后窗口 15:00-16:00"""
        self.assertTrue(is_aftermarket(self._t(0, 15, 0)))
        self.assertTrue(is_aftermarket(self._t(0, 15, 30)))
        self.assertTrue(is_aftermarket(self._t(0, 15, 59)))
        self.assertFalse(is_aftermarket(self._t(0, 16, 0)))
        self.assertFalse(is_aftermarket(self._t(0, 14, 59)))

    def test_scan_window(self):
        """可扫描窗口：盘前 + 盘中 + 收盘后"""
        self.assertTrue(is_scan_window(self._t(0, 9, 0)))   # 盘前
        self.assertTrue(is_scan_window(self._t(0, 10, 0)))  # 盘中
        self.assertTrue(is_scan_window(self._t(0, 14, 0)))  # 盘中
        self.assertTrue(is_scan_window(self._t(0, 15, 30))) # 收盘后
        self.assertFalse(is_scan_window(self._t(0, 12, 0))) # 午休
        self.assertFalse(is_scan_window(self._t(0, 20, 0))) # 夜间

    def test_get_current_session(self):
        """时段名称判断"""
        self.assertEqual(get_current_session(self._t(0, 9, 15)), "premarket")
        self.assertEqual(get_current_session(self._t(0, 10, 0)), "morning")
        self.assertEqual(get_current_session(self._t(0, 14, 0)), "afternoon")
        self.assertEqual(get_current_session(self._t(0, 15, 30)), "aftermarket")
        self.assertEqual(get_current_session(self._t(0, 20, 0)), "closed")


class TestHolidayCalendar(unittest.TestCase):
    """节假日日历测试：确保 A 股休市日不会被判定为交易日。"""

    def _dt(self, year, month, day, hour=10, minute=0):
        return datetime(year, month, day, hour, minute, tzinfo=BJT)

    # --- is_holiday: 正常交易日 ---
    def test_normal_trading_day(self):
        self.assertFalse(is_holiday(self._dt(2026, 9, 28)))  # 周一

    def test_weekend_is_holiday(self):
        self.assertTrue(is_holiday(self._dt(2026, 9, 26)))  # 周六
        self.assertTrue(is_holiday(self._dt(2026, 9, 27)))  # 周日

    # --- is_holiday: 法定节假日 ---
    def test_new_year(self):
        self.assertTrue(is_holiday(self._dt(2026, 1, 1)))  # 元旦 周四
        self.assertTrue(is_holiday(self._dt(2026, 1, 2)))  # 元旦 周五
        self.assertTrue(is_holiday(self._dt(2026, 1, 3)))  # 元旦 周六

    def test_spring_festival(self):
        self.assertTrue(is_holiday(self._dt(2026, 2, 17)))  # 春节
        self.assertTrue(is_holiday(self._dt(2026, 2, 20)))  # 春节

    def test_qingming(self):
        self.assertTrue(is_holiday(self._dt(2026, 4, 4)))  # 清明

    def test_labor_day(self):
        self.assertTrue(is_holiday(self._dt(2026, 5, 1)))  # 劳动节
        self.assertTrue(is_holiday(self._dt(2026, 5, 4)))  # 劳动节

    def test_dragon_boat(self):
        self.assertTrue(is_holiday(self._dt(2026, 6, 19)))  # 端午

    def test_mid_autumn(self):
        self.assertTrue(is_holiday(self._dt(2026, 9, 25)))  # 中秋

    def test_national_day(self):
        """国庆：2026-10-02 是本次事故的触发日期"""
        self.assertTrue(is_holiday(self._dt(2026, 10, 2)))
        self.assertTrue(is_holiday(self._dt(2026, 10, 1)))
        self.assertTrue(is_holiday(self._dt(2026, 10, 7)))

    def test_national_day_is_not_trading_day(self):
        self.assertFalse(is_trading_day(self._dt(2026, 10, 2)))

    def test_normal_day_is_trading_day(self):
        self.assertTrue(is_trading_day(self._dt(2026, 9, 28)))  # 周一

    def test_year_2027_holidays(self):
        self.assertTrue(is_holiday(self._dt(2027, 10, 1)))  # 国庆
        self.assertTrue(is_holiday(self._dt(2027, 2, 11)))  # 春节

    def test_unknown_year_fallback(self):
        """未维护的年份：仅判周末，不判节假日"""
        # 2028-09-28 是周四，不在日历中，应为交易日
        self.assertFalse(is_holiday(self._dt(2028, 9, 28)))
        # 2028-09-30 是周六，周末
        self.assertTrue(is_holiday(self._dt(2028, 9, 30)))

    def test_holiday_trading_time_false(self):
        """节假日即使在盘中时段也应返回 False"""
        self.assertFalse(is_trading_time(self._dt(2026, 10, 2, 10, 0)))
        self.assertFalse(is_scan_window(self._dt(2026, 10, 2, 10, 0)))
        self.assertFalse(is_premarket(self._dt(2026, 10, 2, 9, 15)))
        self.assertFalse(is_aftermarket(self._dt(2026, 10, 2, 15, 30)))

    def test_holiday_get_current_session(self):
        """节假日返回 'closed'"""
        self.assertEqual(get_current_session(self._dt(2026, 10, 2, 10, 0)), "closed")
        self.assertEqual(get_current_session(self._dt(2026, 10, 2, 9, 15)), "closed")

    def test_date_object(self):
        """支持传入 date 对象"""
        from datetime import date
        self.assertTrue(is_holiday(date(2026, 10, 2)))
        self.assertFalse(is_holiday(date(2026, 9, 28)))


if __name__ == "__main__":
    unittest.main()
