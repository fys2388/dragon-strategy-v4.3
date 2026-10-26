# -*- coding: utf-8 -*-
"""数据源标的池分页单测（mock HTTP，验证稳健性）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import data_source as ds  # noqa: E402


def _page(items, total=None):
    return {"data": {"diff": items, "total": total or len(items)}}


def _item(code, price=10.0, amount=1e9, cap=1e10):
    return {"f12": code, "f14": f"股票{code}", "f2": price, "f6": amount, "f20": cap}


class TestMainboardStocks(unittest.TestCase):
    def test_accumulates_and_dedupes(self):
        # 第1页 3 只（含一只非主板 300xxx），第2页与第1页重叠1只 + 新增1只
        pages = [
            _page([_item("600519"), _item("000001"), _item("300750")]),
            _page([_item("600519"), _item("601318")]),
            _page([]),  # 末尾空页
        ]
        with mock.patch.object(ds, "_request_get", side_effect=pages):
            stocks = ds.get_mainboard_stocks(limit=10)
        codes = [s["code"] for s in stocks]
        self.assertEqual(codes, ["600519", "000001", "601318"])
        self.assertEqual(len(codes), len(set(codes)), "不应有重复 code")
        # 非主板被过滤
        self.assertNotIn("300750", codes)

    def test_skips_failed_page(self):
        # 首页成功，第2页失败跳过，第3页继续收集
        pages = [
            _page([_item("600519")]),
            None,
            _page([_item("000001")]),
            _page([]),
        ]
        with mock.patch.object(ds, "_request_get", side_effect=pages):
            stocks = ds.get_mainboard_stocks(limit=10)
        self.assertEqual([s["code"] for s in stocks], ["600519", "000001"])

    def test_limit_respected(self):
        pages = [_page([_item(f"6000{i}") for i in range(1, 6)]), _page([])]
        with mock.patch.object(ds, "_request_get", side_effect=pages):
            stocks = ds.get_mainboard_stocks(limit=3)
        self.assertEqual(len(stocks), 3)

    def test_total_failure_returns_empty(self):
        with mock.patch.object(ds, "_request_get", return_value=None) as m:
            stocks = ds.get_mainboard_stocks(limit=10)
        self.assertEqual(stocks, [])
        # 快速失败：首页失败只请求 1 次，不翻 20 页
        self.assertEqual(m.call_count, 1)

    def test_first_page_fail_aborts(self):
        with mock.patch.object(ds, "_request_get", return_value=None) as m:
            stocks = ds.get_mainboard_stocks(limit=10)
        self.assertEqual(stocks, [])
        self.assertLessEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
