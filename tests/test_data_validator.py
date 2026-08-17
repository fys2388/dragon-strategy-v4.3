# -*- coding: utf-8 -*-
"""数据自驱层 V2.0 单测：多源校验/自动降级/告警/市场环境。"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import data_validator as dv  # noqa: E402
from strategies.macd_resonance.data_validator import (MarketData,  # noqa: E402
                                                      validate_market_data)
from strategies.macd_resonance.market_regime import classify_regime  # noqa: E402


def md(**kw):
    base = dict(index_price=3300.0, index_change_pct=0.5, volume_yi=9000.0,
                limit_up_count=50, limit_down_count=3,
                timestamp="2026-08-17 10:00:00", source="eastmoney")
    base.update(kw)
    return MarketData(**base)


class TestValidateMarketData(unittest.TestCase):
    def test_switch_when_primary_limit_zero(self):
        """验收1：主源涨停0家，备源45家 → 严重异常，切备源。"""
        primary = md(limit_up_count=0, source="eastmoney")
        backup = md(limit_up_count=45, source="akshare")
        res = validate_market_data(primary, backup)
        self.assertEqual(res.chosen_source, "akshare")
        self.assertEqual(res.severity, "critical")
        self.assertFalse(res.passed)
        self.assertTrue(any("涨停" in a for a in res.anomalies))

    def test_ok_when_similar(self):
        """验收2：双源正常 → 使用主源，无异常。"""
        primary = md(limit_up_count=48)
        backup = md(limit_up_count=52, source="akshare")
        res = validate_market_data(primary, backup)
        self.assertEqual(res.chosen_source, "eastmoney")
        self.assertEqual(res.severity, "ok")
        self.assertTrue(res.passed)
        self.assertEqual(res.anomalies, [])

    def test_index_diff_critical(self):
        primary = md(index_price=3300.0)
        backup = md(index_price=3400.0, source="akshare")  # 差3%
        res = validate_market_data(primary, backup)
        self.assertEqual(res.severity, "critical")
        self.assertEqual(res.chosen_source, "akshare")

    def test_volume_diff_warning(self):
        primary = md(volume_yi=9000.0)
        backup = md(volume_yi=7000.0, source="akshare")  # 差22%
        res = validate_market_data(primary, backup)
        self.assertEqual(res.severity, "warning")
        self.assertEqual(res.chosen_source, "eastmoney")

    def test_primary_down_switch(self):
        res = validate_market_data(None, md(source="akshare"))
        self.assertEqual(res.chosen_source, "akshare")
        self.assertEqual(res.severity, "warning")

    def test_both_down_fatal(self):
        res = validate_market_data(None, None)
        self.assertEqual(res.severity, "fatal")
        self.assertEqual(res.chosen_source, "none")


class TestRegime(unittest.TestCase):
    def test_strong_trend(self):
        self.assertEqual(classify_regime(md(limit_up_count=90, limit_down_count=2)), "strong_trend")
        self.assertEqual(classify_regime(md(limit_up_count=81, limit_down_count=4)), "strong_trend")

    def test_weak_trend(self):
        self.assertEqual(classify_regime(md(limit_up_count=50, limit_down_count=5)), "weak_trend")
        self.assertEqual(classify_regime(md(limit_up_count=30, limit_down_count=9)), "weak_trend")

    def test_range_bound(self):
        self.assertEqual(classify_regime(md(limit_up_count=20, limit_down_count=3)), "range_bound")

    def test_extreme(self):
        self.assertEqual(classify_regime(md(limit_up_count=10, limit_down_count=25)), "extreme")
        self.assertEqual(classify_regime(md(limit_up_count=90, index_change_pct=3.5)), "extreme")


class TestSourceStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        self.tmp.close()
        self._old = dv.STATUS_FILE
        dv.STATUS_FILE = self.tmp.name

    def tearDown(self):
        dv.STATUS_FILE = self._old
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_status_keeps_last_10(self):
        for i in range(12):
            dv.update_source_status("eastmoney", ok=(i % 2 == 0))
        with open(self.tmp.name, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertLessEqual(len(data["eastmoney"]["recent"]), 10)
        self.assertEqual(data["eastmoney"]["success"], 5)


class TestScannerIntegration(unittest.TestCase):
    def setUp(self):
        import tempfile
        from strategies.macd_resonance import scanner as sc_mod
        self._old = sc_mod.HISTORY_FILE
        self._tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        self._tmp.close()
        sc_mod.HISTORY_FILE = self._tmp.name

    def tearDown(self):
        import os
        from strategies.macd_resonance import scanner as sc_mod
        sc_mod.HISTORY_FILE = self._old
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    # 门控默认不过：避免 run() 继续执行标的池/信号分析的真实网络调用
    def _scanner_with_mocks(self, fetched, market_score=(2.0, "评分不足", False)):
        from strategies.macd_resonance.scanner import Scanner, PortfolioManager
        return (
            Scanner(),
            {
                "fetch": mock.patch("strategies.macd_resonance.scanner._fetch_both",
                                    return_value=fetched),
                "status": mock.patch("strategies.macd_resonance.scanner.update_source_status"),
                "score": mock.patch("strategies.macd_resonance.scanner.get_market_score",
                                    return_value=market_score),
                "alert": mock.patch("strategies.macd_resonance.scanner.send_feishu_alert",
                                    return_value=True),
                "pm": mock.patch.object(PortfolioManager, "check_exit_signals",
                                        return_value=[]),
            },
        )

    def test_switch_to_backup_and_alert(self):
        """验收1：主源涨停0家 → 自动切备源 + 推送告警。"""
        fetched = {"eastmoney": md(limit_up_count=0, source="eastmoney"),
                   "akshare": md(limit_up_count=45, source="akshare")}
        scanner, mocks = self._scanner_with_mocks(fetched)
        with mocks["fetch"] as mf, mocks["status"] as ms, mocks["score"] as msc, \
             mocks["alert"] as ma, mocks["pm"] as mp:
            result = scanner.run()
        self.assertEqual(result["data_source"], "akshare")
        self.assertEqual(result["validation_state"], "switched")
        self.assertEqual(result["limit_up"], 45)
        self.assertEqual(result["regime"], "weak_trend")
        ma.assert_called()

    def test_ok_no_alert(self):
        """验收2：双源正常 → 无告警。"""
        fetched = {"eastmoney": md(limit_up_count=48),
                   "akshare": md(limit_up_count=52, source="akshare")}
        scanner, mocks = self._scanner_with_mocks(fetched)
        with mocks["fetch"] as mf, mocks["status"] as ms, mocks["score"] as msc, \
             mocks["alert"] as ma, mocks["pm"] as mp:
            result = scanner.run()
        self.assertEqual(result["data_source"], "eastmoney")
        self.assertEqual(result["validation_state"], "ok")
        self.assertEqual(result["regime"], "weak_trend")
        ma.assert_not_called()

    def test_double_fail_pauses(self):
        """双源异常 → 策略暂停，不执行扫描。"""
        fetched = {"eastmoney": None, "akshare": None}
        scanner, mocks = self._scanner_with_mocks(fetched)
        with mocks["fetch"] as mf, mocks["status"] as ms, mocks["score"] as msc, \
             mocks["alert"] as ma, mocks["pm"] as mp:
            result = scanner.run()
        self.assertTrue(result["data_error"])
        self.assertEqual(result["summary"], "数据异常，策略暂停")
        self.assertEqual(result["entries"], [])
        ma.assert_called_once()
        # 门控不应被调用（不扫描）
        self.assertFalse(msc.called)


class TestBuildMessageDataSourceLine(unittest.TestCase):
    def test_data_source_line(self):
        from strategies.macd_resonance.scanner import build_message
        result = {
            "market_score": 5.0, "can_open": True, "market_desc": "x",
            "entries": [], "exit_signals": [],
            "diagnosis": "", "scan_elapsed": 3.2,
            "limit_up": 45, "limit_down": 2,
            "scanned_count": 10, "passed_count": 6, "resonance_count": 1,
            "recommend_count": 1, "data_source": "akshare",
            "validation_state": "switched", "regime": "weak_trend",
        }
        msg = build_message(result)
        self.assertIn("📡 数据源：东财(主)/AkShare(备) | 校验：⚠️已切换", msg)
        self.assertIn("市场环境：weak_trend(弱势)", msg)
        self.assertIn("扫描10只→过滤6只→通过1只", msg)


if __name__ == "__main__":
    unittest.main()
