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


if __name__ == "__main__":
    unittest.main()
