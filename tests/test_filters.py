# -*- coding: utf-8 -*-
"""硬过滤层单测。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.filters import pass_hard_filters  # noqa: E402


def make_stock(**kw):
    base = {
        "code": "600519", "name": "测试股份", "price": 10.0,
        "float_cap_yi": 100.0, "amount_20d_wan": 30000.0,
        "amplitude_20d_pct": 15.0, "unlock_pct_3m": 0.0,
    }
    base.update(kw)
    return base


class TestHardFilters(unittest.TestCase):
    def test_pass_normal(self):
        ok, reason = pass_hard_filters(make_stock())
        self.assertTrue(ok, reason)

    def test_reject_non_mainboard(self):
        ok, reason = pass_hard_filters(make_stock(code="688001"))
        self.assertFalse(ok)
        self.assertIn("主板", reason)

    def test_reject_st(self):
        ok, _ = pass_hard_filters(make_stock(name="ST测试"))
        self.assertFalse(ok)

    def test_reject_low_price(self):
        ok, reason = pass_hard_filters(make_stock(price=2.0))
        self.assertFalse(ok)
        self.assertIn("价格", reason)

    def test_reject_high_price(self):
        ok, _ = pass_hard_filters(make_stock(price=50.0))
        self.assertFalse(ok)

    def test_reject_small_cap(self):
        ok, reason = pass_hard_filters(make_stock(float_cap_yi=10.0))
        self.assertFalse(ok)
        self.assertIn("市值", reason)

    def test_reject_big_cap(self):
        ok, _ = pass_hard_filters(make_stock(float_cap_yi=900.0))
        self.assertFalse(ok)

    def test_reject_low_amount(self):
        ok, reason = pass_hard_filters(make_stock(amount_20d_wan=1000.0))
        self.assertFalse(ok)
        self.assertIn("成交", reason)

    def test_reject_high_amplitude(self):
        ok, _ = pass_hard_filters(make_stock(amplitude_20d_pct=60.0))
        self.assertFalse(ok)

    def test_reject_unlock(self):
        ok, _ = pass_hard_filters(make_stock(unlock_pct_3m=8.0))
        self.assertFalse(ok)

    def test_missing_optional_metrics_not_block(self):
        # 振幅/解禁/20日均额缺失时不阻断
        s = make_stock(amount_20d_wan=0.0, amplitude_20d_pct=0.0)
        ok, reason = pass_hard_filters(s)
        self.assertTrue(ok, reason)

    def test_boundary_price(self):
        ok, _ = pass_hard_filters(make_stock(price=3.5))
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
