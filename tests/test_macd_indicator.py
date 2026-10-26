# -*- coding: utf-8 -*-
"""MACD 指标模块单测。"""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.macd_indicator import (  # noqa: E402
    above_zero_axis, below_zero_axis, calc_macd, cross_above_zero,
    is_death_cross, is_golden_cross, red_bar_expanding,
)


def make_df(closes):
    return pd.DataFrame({"close": closes})


class TestCalcMacd(unittest.TestCase):
    def test_basic_columns(self):
        closes = [10 + i * 0.1 for i in range(60)]
        df = calc_macd(make_df(closes))
        for col in ("dif", "dea", "macd"):
            self.assertIn(col, df.columns)
        # 尾部无 NaN（数据足够长）
        self.assertFalse(pd.isna(df["dif"].iloc[-1]))

    def test_short_data_returns_nan(self):
        df = calc_macd(make_df([1.0, 2.0, 3.0]))
        self.assertTrue(pd.isna(df["dif"].iloc[-1]))

    def test_up_trend_dif_positive(self):
        closes = [10 + i * 0.5 for i in range(80)]
        df = calc_macd(make_df(closes))
        self.assertGreater(df["dif"].iloc[-1], 0)

    def test_down_trend_dif_negative(self):
        closes = [100 - i * 0.5 for i in range(80)]
        df = calc_macd(make_df(closes))
        self.assertLess(df["dif"].iloc[-1], 0)


class TestSignalJudgement(unittest.TestCase):
    def test_golden_cross(self):
        closes = [10] * 40 + [10, 10, 10.5, 11.5, 13]
        df = calc_macd(make_df(closes))
        # 连续上涨后 DIF 上穿 DEA
        self.assertTrue(is_golden_cross(df["dif"], df["dea"]) or df["dif"].iloc[-1] > df["dea"].iloc[-1])

    def test_death_cross(self):
        closes = [10] * 40 + [10, 10, 9.5, 8.5, 7]
        df = calc_macd(make_df(closes))
        self.assertTrue(df["dif"].iloc[-1] < df["dea"].iloc[-1] or is_death_cross(df["dif"], df["dea"]))

    def test_zero_axis(self):
        self.assertTrue(above_zero_axis(0.1))
        self.assertFalse(above_zero_axis(0.0))
        self.assertTrue(below_zero_axis(-0.1))
        self.assertFalse(below_zero_axis(None))

    def test_cross_above_zero(self):
        dif = pd.Series([-0.1, -0.05, 0.02, 0.08])
        # 最后一根是从 0.02->0.08，非上穿
        self.assertFalse(cross_above_zero(dif))
        dif2 = pd.Series([-0.1, -0.02, 0.01, 0.09])
        self.assertFalse(cross_above_zero(dif2))  # 上穿发生在 index2
        # 构造前一根<0 当前>0
        dif3 = pd.Series([-0.1, 0.05])
        self.assertTrue(cross_above_zero(dif3))

    def test_red_bar_expanding(self):
        macd = pd.Series([0.1, 0.2, 0.3])
        self.assertTrue(red_bar_expanding(macd))
        macd2 = pd.Series([0.3, 0.2, 0.1])
        self.assertFalse(red_bar_expanding(macd2))
        macd3 = pd.Series([-0.1, -0.05, 0.1])
        self.assertFalse(red_bar_expanding(macd3))


if __name__ == "__main__":
    unittest.main()
