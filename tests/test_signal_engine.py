# -*- coding: utf-8 -*-
"""信号引擎 + 扫描器单测（mock 数据源与指标函数，验证信号逻辑）。"""
import os
import sys
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import signal_engine as se_mod  # noqa: E402
from strategies.macd_resonance.scanner import Scanner  # noqa: E402
from strategies.macd_resonance.signal_engine import SignalResult, SignalType  # noqa: E402


def make_kline_df(n=80):
    """构造 K 线 DataFrame。"""
    closes = [10 + i * 0.02 for i in range(n)]
    df = pd.DataFrame({
        "datetime": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes, "close": closes,
        "high": [c + 0.1 for c in closes],
        "low": [c - 0.1 for c in closes],
        "volume": [10000.0] * n,
        "amount": [10000000.0] * n,
    })
    return df


def make_market_data():
    """构造数据自驱层的 MarketData 快照（供扫描器集成测试 mock）。"""
    from strategies.macd_resonance.data_validator import MarketData
    return MarketData(
        index_price=3300.0, index_change_pct=0.5, volume_yi=9000.0,
        limit_up_count=50, limit_down_count=3,
        timestamp="2026-08-17 10:00:00", source="eastmoney",
    )


def fake_calc_macd(df, fast=10, slow=20, signal=7, dif_val=0.1):
    out = df.copy()
    out["dif"] = [0.0] * (len(out) - 1) + [dif_val]
    out["dea"] = [0.0] * (len(out) - 1) + [dif_val - 0.05]
    out["macd"] = [0.1] * (len(out) - 2) + [0.2, 0.3]
    return out


class TestSignalEngine(unittest.TestCase):
    def setUp(self):
        self.engine = se_mod.SignalEngine()
        self.engine.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.engine.portfolio_file = os.path.join(self.engine.base_dir, "portfolio_data.json")

    @mock.patch.object(se_mod.ds, "get_kline")
    @mock.patch.object(se_mod, "calc_macd", side_effect=fake_calc_macd)
    @mock.patch.object(se_mod, "is_golden_cross", return_value=True)
    @mock.patch.object(se_mod, "red_bar_expanding", return_value=True)
    @mock.patch.object(se_mod, "cross_above_zero", return_value=True)
    def test_long_entry_all_conditions(self, m1, m2, m3, m4, m5):
        df = make_kline_df()
        df.loc[df.index[-1], "volume"] = 30000.0  # 量能 3 倍
        df.loc[df.index[-20:], "high"] = 9.0  # 突破平台
        m5.return_value = df  # get_kline

        sig = self.engine.check_long_entry("600519", "测试", 12.0)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.signal_type, SignalType.LONG_ENTRY)

    @mock.patch.object(se_mod.ds, "get_kline")
    @mock.patch.object(se_mod, "calc_macd", side_effect=lambda df, fast=10, slow=20, signal=7: fake_calc_macd(df, dif_val=-0.2))
    def test_long_entry_blocked_when_daily_dif_below_zero(self, m1, m2):
        m1.return_value = make_kline_df()
        sig = self.engine.check_long_entry("600519", "测试", 12.0)
        self.assertIsNone(sig)

    @mock.patch.object(se_mod.ds, "get_kline", return_value=make_kline_df())
    @mock.patch.object(se_mod, "calc_macd", side_effect=lambda df, fast=10, slow=20, signal=7: fake_calc_macd(df, dif_val=0.1))
    def test_long_exit_on_loss(self, m1, m2):
        with mock.patch.object(self.engine, "_position_for", return_value={"code": "600519", "entry_price": 10.0}):
            sig = self.engine.analyze_stock("600519", "测试", 9.5)  # 浮亏5%
        self.assertEqual(sig.signal_type, SignalType.LONG_EXIT)
        self.assertIn("止损", sig.reason)

    @mock.patch.object(se_mod.ds, "get_kline", return_value=make_kline_df())
    @mock.patch.object(se_mod, "calc_macd", side_effect=lambda df, fast=10, slow=20, signal=7: fake_calc_macd(df, dif_val=0.1))
    def test_hold_when_no_position(self, m1, m2):
        sig = self.engine.analyze_stock("600519", "测试", 12.0)
        self.assertEqual(sig.signal_type, SignalType.HOLD)


class TestScannerGate(unittest.TestCase):
    def setUp(self):
        import tempfile
        from strategies.macd_resonance import scanner as scanner_mod
        self._old = scanner_mod.HISTORY_FILE
        self._tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        self._tmp.close()
        scanner_mod.HISTORY_FILE = self._tmp.name

    def tearDown(self):
        import os
        from strategies.macd_resonance import scanner as scanner_mod
        scanner_mod.HISTORY_FILE = self._old
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    @mock.patch("strategies.macd_resonance.scanner.get_market_score",
                return_value=(2.0, "评分不足", False))
    @mock.patch("strategies.macd_resonance.scanner.update_source_status")
    @mock.patch("strategies.macd_resonance.scanner.send_feishu_alert", return_value=True)
    @mock.patch("strategies.macd_resonance.scanner.get_data_with_fallback",
                return_value=(make_market_data(), "eastmoney"))
    def test_empty_when_market_below_threshold(self, m, m_status, m_alert, m_score):
        scanner = Scanner()
        scanner.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = scanner.run()
        self.assertFalse(result["can_open"])
        self.assertEqual(result["entries"], [])


if __name__ == "__main__":
    unittest.main()
