# -*- coding: utf-8 -*-
"""持仓管理器单测（mock 行情与K线，验证离场信号逻辑）。"""
import os
import sys
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.portfolio_manager import PortfolioManager  # noqa: E402


def make_pos(entry_price):
    return {"code": "600519", "name": "贵州茅台", "entry_price": entry_price, "quantity": 100}


def make_kline_df(dif_last=0.1):
    n = 60
    closes = [10 + i * 0.01 for i in range(n)]
    df = pd.DataFrame({
        "datetime": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes, "close": closes,
        "high": [c + 0.1 for c in closes],
        "low": [c - 0.1 for c in closes],
        "volume": [10000.0] * n,
        "amount": [1e7] * n,
    })
    m = df.copy()
    m["dif"] = [0.0] * (n - 1) + [dif_last]
    m["dea"] = [0.0] * (n - 1) + [dif_last - 0.05]
    m["macd"] = [0.1] * n
    return m


class TestPortfolioManager(unittest.TestCase):
    def setUp(self):
        self.pm = PortfolioManager()

    def _check(self, entry_price, current_price, kline_df=None, period_data=None):
        with mock.patch.object(self.pm, "_tf_macd", side_effect=period_data or
                               (lambda c, p: (make_kline_df(), make_kline_df()["dif"],
                                              make_kline_df()["dea"], make_kline_df()["macd"]))):
            return self.pm.check_position(make_pos(entry_price), {"price": current_price})

    def test_hard_stop_loss(self):
        sig = self._check(10.0, 9.4)  # 浮亏 -6%
        self.assertIsNotNone(sig)
        self.assertEqual(sig.signal_type, "hard_stop")
        self.assertIn("硬止损", sig.reason)

    def test_take_profit_1_half(self):
        sig = self._check(10.0, 11.1)  # 浮盈 +11%
        self.assertEqual(sig.signal_type, "take_profit_1")
        self.assertIn("50%", sig.suggestion)

    def test_take_profit_2_clear(self):
        sig = self._check(10.0, 11.6)  # 浮盈 +16%
        self.assertEqual(sig.signal_type, "take_profit_2")
        self.assertIn("清仓", sig.suggestion)

    def test_zero_axis_break(self):
        # 日线 DIF = -0.2 < -0.05 → 零轴破位（浮亏未到5%）
        def fake_tf(code, period):
            df = make_kline_df(dif_last=-0.2)
            return df, df["dif"], df["dea"], df["macd"]
        sig = self._check(10.0, 9.9, period_data=fake_tf)
        self.assertEqual(sig.signal_type, "zero_axis_break")

    def test_no_signal(self):
        sig = self._check(10.0, 10.1)  # 浮盈 1%
        self.assertIsNone(sig)

    def test_priority_hard_stop_over_take_profit(self):
        # 浮盈 12% 但日线 DIF 破零轴 → 零轴破位应优先于止盈1
        def fake_tf(code, period):
            df = make_kline_df(dif_last=-0.2)
            return df, df["dif"], df["dea"], df["macd"]
        sig = self._check(10.0, 11.2, period_data=fake_tf)
        self.assertEqual(sig.signal_type, "zero_axis_break")

    def test_empty_positions(self):
        self.assertEqual(self.pm.check_exit_signals([]), [])


if __name__ == "__main__":
    unittest.main()
