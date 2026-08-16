# -*- coding: utf-8 -*-
"""看板统计与策略历史记录单测（离线，不依赖网络）。"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_gd():
    spec = importlib.util.spec_from_file_location(
        "generate_dashboard_data", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                "scripts", "generate_dashboard_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_history(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestDashboardStats(unittest.TestCase):
    def setUp(self):
        self.gd = _load_gd()
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        self.tmp.close()
        self.gd.HISTORY_FILE = self.tmp.name

        now = datetime.now()
        rows = [
            {"ts": now.strftime("%Y-%m-%d 10:00:00"), "market_score": 5.0, "can_open": True,
             "entries": [{"code": "600519", "name": "贵州茅台", "price": 1380.0, "score": 8.0}]},
            {"ts": now.strftime("%Y-%m-%d 11:00:00"), "market_score": 4.5, "can_open": True,
             "entries": [{"code": "600519", "name": "贵州茅台", "price": 1381.0, "score": 8.0},
                         {"code": "000001", "name": "平安银行", "price": 12.3, "score": 7.0}]},
            {"ts": (now - timedelta(days=10)).strftime("%Y-%m-%d 10:00:00"), "market_score": 3.0,
             "can_open": False,
             "entries": [{"code": "000333", "name": "美的集团", "price": 60.0, "score": 7.0}]},
        ]
        _write_history(self.tmp.name, rows)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_load_history(self):
        records = self.gd.load_history()
        self.assertEqual(len(records), 3)

    def test_window_dedupe_by_code(self):
        now = datetime.now()
        entries = self.gd.entries_in_window(self.gd.load_history(), 7, now)
        codes = [e["code"] for e in entries]
        self.assertEqual(len(entries), 2, "7天内600519应去重为1次，加上000001共2只")
        self.assertIn("600519", codes)
        self.assertIn("000001", codes)
        # 保留窗口内最早一次推荐价
        e519 = [e for e in entries if e["code"] == "600519"][0]
        self.assertEqual(e519["price"], 1380.0)

    def test_performance_win_rate(self):
        entries = [{"code": "600519", "price": 10.0}, {"code": "000001", "price": 20.0}]
        quotes = {"600519": {"price": 11.0}, "000001": {"price": 19.0}}
        perf = self.gd.compute_performance(entries, quotes)
        self.assertEqual(perf["count"], 2)
        self.assertEqual(perf["avg_return_pct"], 2.5)  # (+10% + -5%)/2 = +2.5%
        self.assertEqual(perf["win_rate_pct"], 50.0)
        self.assertEqual(perf["pos_count"], 1)
        self.assertEqual(perf["neg_count"], 1)

    def test_offline_graceful(self):
        d = self.gd.build_dashboard(7, datetime.now(), {})
        self.assertEqual(d["perf"]["no_price"], 2)
        self.assertEqual(d["perf"]["avg_return_pct"], 0.0)


class TestScannerHistory(unittest.TestCase):
    def test_append_history_writes_jsonl(self):
        from strategies.macd_resonance import scanner as scanner_mod

        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        tmp.close()
        old = scanner_mod.HISTORY_FILE
        scanner_mod.HISTORY_FILE = tmp.name
        try:
            sc = scanner_mod.Scanner.__new__(scanner_mod.Scanner)  # 不触发网络
            sc._append_history({
                "scan_time": "2026-08-16 10:00:00",
                "market_score": 5.0, "can_open": True, "summary": "test",
                "entries": [{"code": "600519", "name": "贵州茅台", "price": 1380.0, "score": 8.0}],
                "exit_signals": [{"code": "000858", "signal_type": "hard_stop",
                                  "profit_pct": -5.2, "suggestion": "立即清仓"}],
            })
            with open(tmp.name, "r", encoding="utf-8") as f:
                rec = json.loads(f.readline())
            self.assertEqual(rec["entries"][0]["code"], "600519")
            self.assertEqual(rec["exit_signals"][0]["signal_type"], "hard_stop")
            self.assertEqual(rec["market_score"], 5.0)
        finally:
            scanner_mod.HISTORY_FILE = old
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
