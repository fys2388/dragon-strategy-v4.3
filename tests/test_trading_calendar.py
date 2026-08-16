# -*- coding: utf-8 -*-
"""交易时段判断单测（纯函数，无网络依赖）。"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.trading_calendar import is_trading_time  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
