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

    def test_backup_down_degraded(self):
        res = validate_market_data(md(), None)
        self.assertEqual(res.chosen_source, "eastmoney")
        self.assertEqual(res.severity, "degraded")
        self.assertTrue(any("备源" in a for a in res.anomalies))

    def test_both_down_fatal(self):
        res = validate_market_data(None, None)
        self.assertEqual(res.severity, "fatal")
        self.assertEqual(res.chosen_source, "none")


class TestRegime(unittest.TestCase):
    """classify_regime 当前 5 档口径（bull/bear/strong_rebound/sideways/extreme）。

    口径已从早期的 strong_trend / weak_trend / range_bound 整体替换，
    旧三档字符串在 market_regime.REGIME_LABELS 中已不存在。
    """

    def test_extreme_by_limit_down(self):
        # 跌停 >30 → 极端行情
        self.assertEqual(classify_regime(md(limit_up_count=10, limit_down_count=31)), "extreme")

    def test_extreme_by_index_swing(self):
        # |涨跌幅| >3.5% 才算极端；边界值 3.5 不触发（代码用严格大于）
        self.assertEqual(classify_regime(md(index_change_pct=4.0)), "extreme")
        self.assertEqual(classify_regime(md(index_change_pct=-4.0)), "extreme")
        self.assertNotEqual(classify_regime(md(index_change_pct=3.5)), "extreme")

    def test_bull_market_by_trend(self):
        # 指数上涨 + 涨停多 + 跌停少 + 放量
        self.assertEqual(classify_regime(md(index_change_pct=0.8, limit_up_count=65,
                                            limit_down_count=2, volume_yi=11000)), "bull_market")

    def test_bull_market_by_emotion(self):
        # 涨 >40 且 跌 <8 → 情绪偏强归牛市
        self.assertEqual(classify_regime(md(limit_up_count=45, limit_down_count=3)), "bull_market")

    def test_bear_market_by_trend(self):
        # 指数下跌 + 涨停少 + 跌停多
        self.assertEqual(classify_regime(md(index_change_pct=-0.8, limit_up_count=20,
                                            limit_down_count=15)), "bear_market")

    def test_bear_market_by_emotion(self):
        # 跌 >8 → 情绪偏弱归熊市
        self.assertEqual(classify_regime(md(limit_up_count=30, limit_down_count=9)), "bear_market")

    def test_strong_rebound(self):
        # 指数大涨 + 涨停激增（未达极端/未达牛市趋势条件）
        self.assertEqual(classify_regime(md(index_change_pct=2.0, limit_up_count=55)), "strong_rebound")

    def test_sideways_default(self):
        # 中性区间：指数 ±0.5% 内、涨停 20-40、跌停 <8
        self.assertEqual(classify_regime(md(limit_up_count=25, limit_down_count=3)), "sideways")

    def test_none_data_returns_sideways(self):
        self.assertEqual(classify_regime(None), "sideways")


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
                "fetch": mock.patch("strategies.macd_resonance.scanner.get_data_with_fallback",
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
        fetched = (md(limit_up_count=45, source="akshare"), "akshare")
        scanner, mocks = self._scanner_with_mocks(fetched)
        with mocks["fetch"] as mf, mocks["status"] as ms, mocks["score"] as msc, \
             mocks["alert"] as ma, mocks["pm"] as mp:
            result = scanner.run()
        self.assertEqual(result["data_source"], "akshare")
        self.assertEqual(result["validation_state"], "switched")
        self.assertEqual(result["limit_up"], 45)
        self.assertEqual(result["regime"], "bull_market")
        ma.assert_called()

    def test_ok_no_alert(self):
        """验收2：双源正常 → 无告警。"""
        fetched = (md(limit_up_count=48), "eastmoney")
        scanner, mocks = self._scanner_with_mocks(fetched)
        with mocks["fetch"] as mf, mocks["status"] as ms, mocks["score"] as msc, \
             mocks["alert"] as ma, mocks["pm"] as mp:
            result = scanner.run()
        self.assertEqual(result["data_source"], "eastmoney")
        self.assertEqual(result["validation_state"], "ok")
        self.assertEqual(result["regime"], "bull_market")
        ma.assert_not_called()

    def test_double_fail_pauses(self):
        """双源异常 → 策略暂停，不执行扫描。"""
        fetched = (None, "none")
        scanner, mocks = self._scanner_with_mocks(fetched)
        with mocks["fetch"] as mf, mocks["status"] as ms, mocks["score"] as msc, \
             mocks["alert"] as ma, mocks["pm"] as mp:
            result = scanner.run()
        self.assertTrue(result["data_error"])
        self.assertIn("策略暂停", result["summary"])
        self.assertEqual(result["entries"], [])
        ma.assert_called_once()
        # 未取到数据 → regime 停在默认档 sideways（与 REGIME_LABELS 口径一致）
        self.assertEqual(result["regime"], "sideways")
        # 门控不应被调用（不扫描）
        self.assertFalse(msc.called)


if __name__ == "__main__":
    unittest.main()
