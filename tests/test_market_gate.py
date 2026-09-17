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


def _no_em_limit_pool():
    """屏蔽 get_limit_up_down_count 的第 1 步「东财官方涨跌停池」。

    根因说明：`_get_em_limit_pool_count()` 直接调 `requests.get`，不经过 `_request_get`。
    只 mock `_request_get` 会让第 1 步打到真实东财接口（曾返回 47/0），
    直接 return 掉，后续 3 个断言全部落空。第 1 步自身由 test_em_* 用例单独覆盖。
    """
    return mock.patch.object(ds, "_get_em_limit_pool_count", return_value=(0, 0))


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
        with _no_em_limit_pool(), \
             mock.patch.object(ds, "_request_get", return_value={"data": {"diff": diff}}):
            up, down = ds.get_limit_up_down_count()
        self.assertEqual(up, 2)
        self.assertEqual(down, 2)

    def test_failure_falls_back_to_sina(self):
        # 东财接口失败 → 自动切换新浪备用源
        with _no_em_limit_pool(), \
             mock.patch.object(ds, "_request_get", return_value=None), \
             mock.patch.object(ds, "_get_sina_limit_count", return_value=(45, 2)):
            up, down = ds.get_limit_up_down_count()
        self.assertEqual((up, down), (45, 2))

    def test_sina_fallback_failure_returns_zero(self):
        # 东财与新浪备用源均失败 → 返回 (0, 0) 不崩溃
        with _no_em_limit_pool(), \
             mock.patch.object(ds, "_request_get", return_value=None), \
             mock.patch.object(ds, "_get_sina_limit_count", return_value=(0, 0)):
            up, down = ds.get_limit_up_down_count()
        self.assertEqual((up, down), (0, 0))

    def test_em_limit_pool_has_priority(self):
        """第 1 步涨跌停池有数据时直接采用，跳过全A列表遍历与新浪备用源。"""
        urls = []

        def fake_get(url, **kw):
            urls.append(url)
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {
                "data": {"pool": ["a", "b"] if "ZTPool" in url else ["c"]}
            }
            return resp

        with mock.patch.object(ds.requests, "get", side_effect=fake_get), \
             mock.patch.object(ds, "_request_get") as m_full_a, \
             mock.patch.object(ds, "_get_sina_limit_count") as m_sina:
            up, down = ds.get_limit_up_down_count()

        self.assertEqual((up, down), (2, 1))
        self.assertEqual(len(urls), 2)
        self.assertTrue(all("push2ex.eastmoney.com" in u for u in urls))
        m_full_a.assert_not_called()   # 已命中第 1 步，不再遍历全A列表
        m_sina.assert_not_called()

    def test_em_limit_pool_failure_falls_through_to_full_a(self):
        """涨跌停池不可达 → 继续第 3 步东财全A列表遍历（本地模式，完全离线）。"""
        diff = [_item("600001", 10.0), _item("000002", -10.0)]
        with mock.patch.object(ds.requests, "get", side_effect=ConnectionError("超时")), \
             mock.patch.object(ds, "_request_get", return_value={"data": {"diff": diff}}):
            up, down = ds.get_limit_up_down_count()
        self.assertEqual((up, down), (1, 1))

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


class TestBuildMessage(unittest.TestCase):
    """build_message 极简版契约（提交 1fdc849「推送极简版」起生效）。

    极简版**不含**触发时间/扫描耗时/涨停跌停家数/数据源/校验状态/诊断行。
    这些字段仍由 Scanner.run() 产出并写入历史与异常日志，但不进飞书推送消息。
    若要恢复这些行属产品文案改动，需先与用户确认，不要为了过测试而改断言。
    """

    def _msg(self, **kw):
        from strategies.macd_resonance.scanner import build_message
        base = {
            "market_score": 5.0, "can_open": True, "market_desc": "x",
            "entries": [], "exit_signals": [],
            "diagnosis": "扫描10只→过滤后5只→共振通过1只 | 拒因：无",
            "scan_elapsed": 12.3, "limit_up": 45, "limit_down": 2,
            "scanned_count": 10, "passed_count": 5,
            "resonance_count": 1, "recommend_count": 0,
        }
        base.update(kw)
        return build_message(base)

    def test_header_can_open_standard(self):
        # A股习惯：红涨绿跌 → 可开仓🔴 / 观望🟢
        msg = self._msg()
        self.assertEqual(msg.splitlines()[0], "📊 MACD共振：大盘5/7 🔴可开仓")
        self.assertIn("  无推荐", msg)

    def test_header_caution_when_score_below_threshold(self):
        # 门控放行但大盘评分 <4 → 宽松档🟡
        self.assertIn("🟡谨慎开仓", self._msg(market_score=3.0))

    def test_header_watch_when_gate_closed(self):
        self.assertIn("🟢观望", self._msg(market_score=5.0, can_open=False))

    def test_entry_lines_one_per_stock(self):
        entries = [
            {"code": "600519", "name": "贵州茅台", "price": 1500.0,
             "resonance_levels": ["日线", "60min"], "score": 85},
            {"code": "300001", "name": "特锐德", "price": 20.0,
             "resonance_levels": ["日线"], "score": 72},
        ]
        msg = self._msg(entries=entries)
        self.assertIn("  1. 贵州茅台(600519) 1500.0元 日线+60min 得分85", msg)
        self.assertIn("  2. 特锐德(300001) 20.0元 日线 得分72", msg)
        self.assertNotIn("无推荐", msg)

    def test_minimal_format_omits_diagnostics(self):
        """极简版刻意不输出诊断信息（含数据源/校验状态/市场环境）。"""
        msg = self._msg(data_source="akshare", validation_state="switched",
                        regime="bull_market")
        for absent in ("触发时间", "扫描耗时", "数据源：", "市场环境：",
                       "涨停45家", "过滤后5只"):
            self.assertNotIn(absent, msg)
        self.assertEqual(len(msg.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
