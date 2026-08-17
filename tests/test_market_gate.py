# -*- coding: utf-8 -*-
"""涨停/跌停动态统计与大盘门控单测（mock 数据源）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import data_source as ds  # noqa: E402
from strategies.macd_resonance.market_gate import get_market_score  # noqa: E402


def _item(code, chg):
    return {"f12": code, "f14": f"股{code}", "f3": chg, "f4": 0, "f5": 0,
            "f6": 0, "f15": 0, "f16": 0, "f17": 0, "f18": 0}


class TestLimitUpDown(unittest.TestCase):
    def test_counts_limits(self):
        diff = [
            _item("600001", 10.0),   # 涨停
            _item("000001", 9.99),   # 涨停（≥9.9）
            _item("600002", 9.8),    # 非涨停
            _item("000002", -10.0),  # 跌停
            _item("600003", -9.99),  # 跌停
            _item("000003", -9.8),   # 非跌停
            _item("600004", 5.02),   # ST 5% 涨停，不计入
        ]
        with mock.patch.object(ds, "_request_get", return_value={"data": {"diff": diff}}):
            up, down = ds.get_limit_up_down_count()
        self.assertEqual(up, 2)
        self.assertEqual(down, 2)

    def test_failure_returns_zero(self):
        with mock.patch.object(ds, "_request_get", return_value=None):
            up, down = ds.get_limit_up_down_count()
        self.assertEqual((up, down), (0, 0))

    def test_importable_from_market_gate(self):
        from strategies.macd_resonance.market_gate import get_limit_up_down_count as fn
        self.assertTrue(callable(fn))


class TestMarketScoreUsesDynamicCount(unittest.TestCase):
    @mock.patch("strategies.macd_resonance.market_gate.get_limit_up_down_count",
                return_value=(35, 3))
    @mock.patch("strategies.macd_resonance.market_gate.ds.get_market_total_amount_yi",
                return_value=9000.0)
    @mock.patch("strategies.macd_resonance.market_gate._check_sh_ma20",
                return_value=(2.0, "ok"))
    def test_score_counts_limit_up(self, m_sh, m_amount, m_ld):
        score, desc, can_open = get_market_score()
        self.assertGreaterEqual(score, 2.0)  # 涨停35≥30(+1) 且 ≥50 不加，跌停3<10(+1)
        self.assertIn("涨停35家", desc)

    @mock.patch("strategies.macd_resonance.market_gate.get_limit_up_down_count",
                return_value=(0, 0))
    @mock.patch("strategies.macd_resonance.market_gate.ds.get_market_total_amount_yi",
                return_value=9000.0)
    @mock.patch("strategies.macd_resonance.market_gate._check_sh_ma20",
                return_value=(2.0, "ok"))
    def test_zero_limit_counts_still_works(self, m_sh, m_amount, m_ld):
        score, desc, can_open = get_market_score()
        self.assertIn("涨停0家", desc)


class TestScannerDiagnosticLine(unittest.TestCase):
    def test_build_message_has_trigger_line(self):
        from strategies.macd_resonance.scanner import build_message
        result = {
            "market_score": 5.0, "can_open": True, "market_desc": "x",
            "entries": [], "exit_signals": [],
            "diagnosis": "扫描10只→过滤后5只→共振通过1只 | 拒因：无",
            "scan_elapsed": 12.3, "limit_up": 45, "limit_down": 2,
            "scanned_count": 10, "passed_count": 5,
            "resonance_count": 1, "recommend_count": 0,
        }
        msg = build_message(result)
        self.assertIn("⏱ 触发时间：北京时间", msg)
        self.assertIn("扫描耗时12.3s", msg)
        self.assertIn("涨停45家/跌停2家", msg)
        self.assertIn("过滤后5只→共振通过1只", msg)


if __name__ == "__main__":
    unittest.main()
