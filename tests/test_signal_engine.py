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


def make_bull_state(n=25, last_close=10.0, last_vol=300.0, base_vol=100.0):
    """日线 K 线：最后一天放量，且收盘价突破前 20 根 60min 平台。"""
    closes = [last_close - (n - 1 - i) * 0.01 for i in range(n)]
    return pd.DataFrame({
        "datetime": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes, "close": closes,
        # 60min 平台全部低于当前收盘价 → H 闸门（突破）成立
        "high": [last_close - 0.5] * n,
        "low": [c - 0.1 for c in closes],
        "volume": [base_vol] * (n - 1) + [last_vol],
        "amount": [1e6] * n,
    })


def make_macd_state(n=25, dif_start=0.5, dea_start=0.1, step=0.01):
    """持续多头状态：DIF 全程高于 DEA 且为正。

    关键点：全程 DIF>DEA，所以 recent_golden_cross 在任意 lookback 下都是 False
    —— 即「很久以前就已经金叉、现在处于多头状态」，而不是「刚发生金叉」。
    """
    dif = [dif_start + step * i for i in range(n)]
    dea = [dea_start + step * i for i in range(n)]
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    return pd.Series(dif, dtype=float), pd.Series(dea, dtype=float), pd.Series(macd, dtype=float)


class TestLongEntryStateBased(unittest.TestCase):
    """2026-09-22 修复验证：60/30min 闸门从「瞬时金叉」改成「多头状态」。

    线上实测（run 35692924401，14:00 档）104 只候选：
        日线零轴上方 74 只 | 60min 金叉 6 只 | 30min 金叉 3 只
    三个瞬时事件取交集必然为空 → 共振长期 0 推荐。
    """

    def setUp(self):
        self.engine = se_mod.SignalEngine()
        self.engine.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _patch_macd(self, dif_start=0.5, dea_start=0.1):
        """让所有周期都返回「持续多头但无新近金叉」的序列。"""
        df = make_bull_state()
        dif, dea, macd = make_macd_state(dif_start=dif_start, dea_start=dea_start)
        return mock.patch.object(self.engine, "_tf_macd",
                                 return_value=(df.copy(), dif, dea, macd))

    def test_bullish_state_without_fresh_cross_now_passes(self):
        """零轴上方 + 红柱为正 + 放量 + 突破，但没有新近金叉 → 应给出做多信号。

        旧实现在这里 return None（要求 recent_golden_cross(lookback=3)），
        正是线上 0 推荐的成因。
        """
        with self._patch_macd():
            self.engine.reset_gate_counts()
            sig = self.engine.check_long_entry("600519", "测试", 10.0, mode="standard")

        self.assertIsNotNone(sig, "持续多头状态应通过闸门")
        self.assertEqual(sig.signal_type, SignalType.LONG_ENTRY)
        # 状态型闸门：得分来自各周期实际确认到的状态，量纲 1.0~4.0
        self.assertGreater(sig.score, 1.0)
        self.assertLessEqual(sig.score, 4.0)
        # 没有新近金叉，reason 里应体现走的是「零轴上方」而非「金叉」
        self.assertIn("零轴上方", sig.reason)
        self.assertEqual(self.engine.get_gate_counts(), {},
                         "全部通过时不应有闸门拒绝记录")

    def test_gate_counter_records_daily_dif_rejection(self):
        """日线 DIF 在零轴下方 → 拒因必须被计数，而不是只报一行「0 只」。"""
        # ZERO_AXIS_EPS=0.05，DIF 必须跌破 -0.05 才算「零轴下方」
        dif, dea, macd = make_macd_state(dif_start=-0.1, dea_start=-0.2, step=0.001)
        df = make_bull_state()
        with mock.patch.object(self.engine, "_tf_macd", return_value=(df, dif, dea, macd)):
            self.engine.reset_gate_counts()
            sig = self.engine.check_long_entry("600519", "测试", 10.0, mode="standard")

        self.assertIsNone(sig)
        counts = self.engine.get_gate_counts()
        self.assertIn("C日线DIF零轴下", counts)
        self.assertEqual(counts["C日线DIF零轴下"], 1)

    def test_gate_counter_records_volume_rejection(self):
        """量能不足也要被计数。"""
        df = make_bull_state(last_vol=101.0, base_vol=100.0)  # 1.01 倍 < 1.2
        dif, dea, macd = make_macd_state()
        with mock.patch.object(self.engine, "_tf_macd", return_value=(df, dif, dea, macd)):
            self.engine.reset_gate_counts()
            sig = self.engine.check_long_entry("600519", "测试", 10.0, mode="standard")

        self.assertIsNone(sig)
        self.assertTrue(any(k.startswith("G量能") for k in self.engine.get_gate_counts()))

    def test_relaxed_mode_accepts_older_cross(self):
        """宽松档：min_bull_minute_tfs=1，只要 1 个分钟周期多头就通过。

        ⚠️ 2026-09-22 重设计后语义变更：原测试检验「近 N 根前的金叉仍算数」
        的 lookback 窗口机制。新设计改为按分钟周期多头计数（min_bull_minute_tfs），
        不再有"近 N 根金叉"的概念——多头 = DIF > DEA 的当前状态，不区分新鲜度。
        因此本测试改为检验：relaxed 档（min=1）比 standard 档（min=2）
        接受更弱的分钟周期组合。
        """
        # 构造：日线多头；60min DIF>DEA（多头），30min/15min DIF<DEA（空头）
        # → bull_minute_tfs=1，relaxed 通过，standard 拒绝
        n = 25
        dea_bull = [0.1 + 0.005 * i for i in range(n)]       # 60min: 多头
        dif_bull = [dea_bull[i] + 0.02 for i in range(n)]     # DIF > DEA
        dea_bear = [0.1 - 0.005 * i for i in range(n)]        # 30/15min: 空头
        dif_bear = [dea_bear[i] - 0.02 for i in range(n)]     # DIF < DEA
        macd_bull = [(d - e) * 2 for d, e in zip(dif_bull, dea_bull)]
        macd_bear = [(d - e) * 2 for d, e in zip(dif_bear, dea_bear)]

        # daily: DIF 在零轴上方（+0.1）；60min: DIF>DEA；30/15min: DIF<DEA
        # ⚠️ 量比必须落在 [vol_min, vol_max] 区间：relaxed 档 vol_max=2.5，
        # standard 档 vol_max=3.0，所以选 vol_ratio=2.0 让两档都通过 G 闸门。
        df_daily = make_bull_state(last_vol=200.0, base_vol=100.0)
        df_min = make_bull_state(last_vol=200.0, base_vol=100.0)

        def fake_tf_macd(code, period, count):
            if period == "daily":
                # 日线：DIF=0.1（零轴上），DEA=0.08（比 DIF 小），MACD=0.04
                dif = pd.Series([0.1] * 120)
                dea = pd.Series([0.08] * 120)
                macd = pd.Series([0.04] * 120)
                return df_daily, dif, dea, macd
            if period == "60m":
                return df_min, pd.Series(dif_bull), pd.Series(dea_bull), pd.Series(macd_bull)
            # 30m 和 15m 都是空头
            return df_min, pd.Series(dif_bear), pd.Series(dea_bear), pd.Series(macd_bear)

        with mock.patch.object(self.engine, "_tf_macd", side_effect=fake_tf_macd):
            self.engine.reset_gate_counts()
            relaxed = self.engine.check_long_entry("600519", "测试", 10.0, mode="relaxed")
            self.engine.reset_gate_counts()
            standard = self.engine.check_long_entry("600519", "测试", 10.0, mode="standard")

        # relaxed 通过（min_bull_minute_tfs=1，只有 60min 一个多头也够）
        self.assertIsNotNone(relaxed)
        self.assertEqual(relaxed.signal_type, SignalType.LONG_ENTRY)
        # standard 拒绝（min_bull_minute_tfs=2，只有 1 个不够）
        self.assertIsNone(standard)
        self.assertTrue(any(k.startswith("I分钟多头不足")
                            for k in self.engine.get_gate_counts()))

    def test_fresh_cross_on_last_bar_also_passes(self):
        """最后一根刚发生金叉的情形同样通过（新旧口径都覆盖）。"""
        n = 25
        # 只在最后一根发生金叉 → 旧口径通过、状态口径也通过
        dea = [0.1 + 0.005 * i for i in range(n)]
        dif = [dea[i] + 0.05 for i in range(n - 1)] + [dea[-1] + 0.1]
        macd = [(d - e) * 2 for d, e in zip(dif, dea)]
        df = make_bull_state()
        with mock.patch.object(self.engine, "_tf_macd",
                               return_value=(df, pd.Series(dif), pd.Series(dea), pd.Series(macd))):
            self.engine.reset_gate_counts()
            sig = self.engine.check_long_entry("600519", "测试", 10.0, mode="standard")
        self.assertIsNotNone(sig)
        self.assertEqual(sig.signal_type, SignalType.LONG_ENTRY)



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
        # check_long_entry(mode="auto") 会实时取大盘评分（→ 东财行情接口）。
        # 单测固定为「大盘 5 分」→ 标准档，既离线又行为确定。
        self._gate = mock.patch("strategies.macd_resonance.market_gate.get_market_score",
                                return_value=(5.0, "大盘OK", True))
        self._gate.start()

    def tearDown(self):
        self._gate.stop()

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
    @mock.patch("strategies.macd_resonance.portfolio_manager.PortfolioManager.check_exit_signals",
                return_value=[])
    def test_empty_when_market_below_threshold(self, m_exit, m, m_status, m_alert, m_score):
        scanner = Scanner()
        scanner.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = scanner.run()
        self.assertFalse(result["can_open"])
        self.assertEqual(result["entries"], [])


if __name__ == "__main__":
    unittest.main()
