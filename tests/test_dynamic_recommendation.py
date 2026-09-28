# -*- coding: utf-8 -*-
"""动态市场建议单测：验证根据 market_gate 分数动态调整 recommendation。

历史事故：market_cluster.py 的 recommendation 是硬编码的"谨慎开仓"，
但 market_gate 实际分数 0/7 时应该"暂停开仓"。用户看到"谨慎开仓"
以为可以下单，但大盘 0/7 实际不允许开仓（can_open=False）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.v43_push import _generate_dynamic_recommendation  # noqa: E402


class TestDynamicRecommendation(unittest.TestCase):
    """_generate_dynamic_recommendation 单测。"""

    def _make_cluster_info(self, regime="sideways_down"):
        """构造 mock 的 cluster_info。"""
        regime_cn = {
            "sideways_down": "震荡下行",
            "sideways_up": "震荡上行",
            "bull_trend": "牛市趋势",
            "bear_trend": "熊市趋势",
            "narrow_range": "窄幅震荡",
            "extreme": "极端行情",
        }.get(regime, "未知")
        return {
            "cluster_name": regime,
            "cluster_name_cn": regime_cn,
            "strategy_params": {
                "recommendation": f"{regime_cn}：超跌反弹为主，谨慎开仓，仓位25%"
            },
        }

    def test_low_score_shows_pause_warning(self):
        """大盘评分 < open_threshold(3.0) 时应显示"暂停开仓"。"""
        cluster_info = self._make_cluster_info("sideways_down")
        rec = _generate_dynamic_recommendation(cluster_info, market_score=0.0)
        self.assertIn("暂停开仓", rec)
        self.assertIn("0/7", rec)
        self.assertNotIn("谨慎开仓", rec)

    def test_low_score_1(self):
        """大盘评分 1 < 3 时也应显示"暂停开仓"。"""
        cluster_info = self._make_cluster_info("sideways_down")
        rec = _generate_dynamic_recommendation(cluster_info, market_score=1)
        self.assertIn("暂停开仓", rec)
        self.assertIn("1/7", rec)

    def test_low_score_2(self):
        """大盘评分 2 < 3 时也应显示"暂停开仓"。"""
        cluster_info = self._make_cluster_info("sideways_down")
        rec = _generate_dynamic_recommendation(cluster_info, market_score=2)
        self.assertIn("暂停开仓", rec)
        self.assertIn("2/7", rec)

    def test_medium_score_shows_caution(self):
        """大盘评分 3 (>= open_threshold, < standard_threshold) 时应显示"谨慎开仓"。"""
        cluster_info = self._make_cluster_info("sideways_down")
        rec = _generate_dynamic_recommendation(cluster_info, market_score=3)
        self.assertIn("谨慎开仓", rec)
        self.assertIn("宽松档", rec)
        self.assertIn("3/7", rec)
        self.assertNotIn("暂停开仓", rec)

    def test_medium_score_3_5(self):
        """大盘评分 3.5 (>= 3.0, < 4.0) 时也应显示"谨慎开仓"。

        注意：:.0f 格式会四舍五入，3.5 显示为 4/7。
        """
        cluster_info = self._make_cluster_info("sideways_down")
        rec = _generate_dynamic_recommendation(cluster_info, market_score=3.5)
        self.assertIn("谨慎开仓", rec)
        self.assertIn("宽松档", rec)
        self.assertIn("4/7", rec)  # 3.5 四舍五入为 4

    def test_high_score_uses_base_recommendation(self):
        """大盘评分 4 (>= standard_threshold) 时应使用原始 recommendation。"""
        cluster_info = self._make_cluster_info("sideways_down")
        rec = _generate_dynamic_recommendation(cluster_info, market_score=4)
        self.assertIn("震荡下行", rec)
        self.assertIn("超跌反弹", rec)
        self.assertNotIn("暂停开仓", rec)
        self.assertNotIn("谨慎开仓，轻仓试错", rec)

    def test_high_score_5(self):
        """大盘评分 5 >= 4 时应使用原始 recommendation。"""
        cluster_info = self._make_cluster_info("sideways_down")
        rec = _generate_dynamic_recommendation(cluster_info, market_score=5)
        self.assertIn("震荡下行", rec)
        self.assertIn("超跌反弹", rec)

    def test_bull_trend_high_score(self):
        """牛市 + 高评分时应使用原始 recommendation。"""
        cluster_info = self._make_cluster_info("bull_trend")
        cluster_info["strategy_params"]["recommendation"] = "牛市趋势：MACD共振为主，可适当放宽条件"
        rec = _generate_dynamic_recommendation(cluster_info, market_score=5)
        self.assertIn("牛市趋势", rec)
        self.assertIn("MACD共振", rec)

    def test_empty_cluster_info(self):
        """cluster_info 为空时不应崩溃。"""
        rec = _generate_dynamic_recommendation({}, market_score=2)
        self.assertIn("暂停开仓", rec)


if __name__ == "__main__":
    unittest.main()