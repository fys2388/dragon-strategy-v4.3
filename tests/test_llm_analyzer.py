# -*- coding: utf-8 -*-
"""LLM 分析器单测：钉住止损/目标价强制校正 + 地产股行业标签修复。

背景：一次推送事故里，LLM 对 4.19 元的万科A 报了 3.80 元止损（-9.3%），
而 config.RISK.stop_loss_pct 是 -5%（正确值应该是 3.98 元）。
单票仓位 3000 元 × 9.3% = 亏 300 元，是风控设计上限的 2 倍。

另外：万科A(000002) 的行业标签曾被标成"综合"（因为名字里没有"地产/置业/建设"），
导致基本面打分和 LLM 叙述把地产股当成综合类企业。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.llm_analyzer import StockAnalyzer  # noqa: E402
from strategies.macd_resonance.config import RISK  # noqa: E402


class TestRiskFieldClamp(unittest.TestCase):
    """止损价/目标价强制夹到 config.RISK 口径。"""

    def _clamp(self, data, price):
        StockAnalyzer._clamp_risk_fields(data, price)
        return data

    def test_stop_loss_clamped_to_config(self):
        """LLM 报 -9.3% 止损（3.80 元）应被强制校正到 -5%（3.98 元）。"""
        price = 4.19
        expected_stop = round(price * (1 - RISK["stop_loss_pct"]), 2)  # 3.98
        data = {"止损价": 3.80, "目标价": 5.20}
        self._clamp(data, price)
        self.assertEqual(data["止损价"], expected_stop)
        self.assertAlmostEqual(data["止损价"], 3.98, places=2)

    def test_target_price_raised_to_first_tp(self):
        """目标价低于首档止盈应被抬升到首档止盈档。"""
        price = 5.66
        min_target = round(price * (1 + RISK["take_profit_1_pct"]), 2)  # 6.23
        data = {"止损价": 5.38, "目标价": 6.00}  # 6.00 < 6.23
        self._clamp(data, price)
        self.assertEqual(data["目标价"], min_target)

    def test_reasonable_values_unchanged(self):
        """LLM 输出符合风控口径时不改。"""
        price = 13.30
        expected_stop = round(price * (1 - RISK["stop_loss_pct"]), 2)  # 12.64
        min_target = round(price * (1 + RISK["take_profit_1_pct"]), 2)  # 14.63
        data = {"止损价": expected_stop, "目标价": 15.50}
        self._clamp(data, price)
        self.assertEqual(data["止损价"], expected_stop)
        self.assertEqual(data["目标价"], 15.50)

    def test_missing_fields_filled(self):
        """LLM 漏字段时应填上风控默认值，不返回 0。"""
        price = 4.19
        data = {}
        self._clamp(data, price)
        self.assertGreater(data["止损价"], 0)
        self.assertGreater(data["目标价"], 0)

    def test_zero_price_no_op(self):
        """价格为 0 时不做任何改动（避免除零）。"""
        data = {"止损价": 3.80, "目标价": 5.20}
        self._clamp(data, 0)
        self.assertEqual(data["止损价"], 3.80)


class TestIndustryInference(unittest.TestCase):
    """地产股行业标签修复：万科A 不再被标成"综合"。"""

    def setUp(self):
        self.analyzer = StockAnalyzer()

    def test_vanke_is_real_estate(self):
        """万科A(000002) 必须归到房地产，不是综合。

        用推送里真实出现的"万 科Ａ"（半角空格 + 全角Ａ）形式，
        钉住名称归一化（去空白 + 全角转半角）的修复。
        """
        industry = self.analyzer._infer_industry("万 科Ａ")
        self.assertEqual(industry, "房地产")

    def test_vanke_plain_name(self):
        """普通写法"万科"也应命中房地产。"""
        self.assertEqual(self.analyzer._infer_industry("万科"), "房地产")

    def test_poli_is_real_estate(self):
        self.assertEqual(self.analyzer._infer_industry("保利发展"), "房地产")

    def test_zhaoshang_snake_is_real_estate(self):
        self.assertEqual(self.analyzer._infer_industry("招商蛇口"), "房地产")

    def test_luohu_is_real_estate(self):
        self.assertEqual(self.analyzer._infer_industry("龙湖集团"), "房地产")

    def test_lotus_holds_still_falls_back(self):
        """莲花控股主营调味品，不在地产名单里，应归到食品饮料（"调味"关键词）。"""
        industry = self.analyzer._infer_industry("莲花控股")
        self.assertNotEqual(industry, "房地产")
        # "控股"不在关键词里，会回落到"综合"，这是可接受的
        # 关键是它不应误判为房地产
        self.assertIn(industry, ["综合", "食品饮料"])

    def test_tianwu_is_electronics(self):
        """天沃科技主营军工电子，命中"电子"关键词。"""
        industry = self.analyzer._infer_industry("天沃科技")
        self.assertEqual(industry, "电子")


class TestAnalysisPrompt(unittest.TestCase):
    """Prompt 里应显式写出 config.RISK 的止损/目标价，防止 LLM 幻觉。"""

    def setUp(self):
        self.analyzer = StockAnalyzer()

    def test_prompt_contains_stop_loss_from_config(self):
        price = 4.19
        expected_stop = round(price * (1 - RISK["stop_loss_pct"]), 2)
        prompt = self.analyzer._build_analysis_prompt("000002", "万 科Ａ", price)
        self.assertIn("硬止损", prompt)
        self.assertIn(f"{expected_stop}", prompt)
        self.assertIn("5%", prompt)  # stop_loss_pct=0.05

    def test_prompt_uses_normalized_industry(self):
        """Prompt 里的行业字段必须经过归一化，万科A 应显示为"房地产"。"""
        prompt = self.analyzer._build_analysis_prompt("000002", "万 科Ａ", 4.19)
        self.assertIn("行业：房地产", prompt)

    def test_prompt_contains_take_profit_from_config(self):
        price = 4.19
        min_target = round(price * (1 + RISK["take_profit_1_pct"]), 2)
        prompt = self.analyzer._build_analysis_prompt("000002", "万 科Ａ", price)
        self.assertIn("首档止盈", prompt)
        self.assertIn(f"{min_target}", prompt)

    def test_prompt_emphasizes_no_fabricating_numbers(self):
        prompt = self.analyzer._build_analysis_prompt("000002", "万 科Ａ", 4.19)
        self.assertIn("不要自造数字", prompt)


class TestAIScorerGradeThresholds(unittest.TestCase):
    """AI 打分器规则打分档位的 emoji/标签阈值。"""

    def setUp(self):
        from strategies.macd_resonance import ai_scorer as ai_mod
        # 直接实例化，不初始化 predictor（add_ai_info_to_message 不用 predictor）
        self.scorer = ai_mod.AIScorer.__new__(ai_mod.AIScorer)
        self.scorer.min_probability = 0.55

    def test_75_score_now_yellow_not_green(self):
        """75 分以前是"🟢强"，现在是"🟡中"（85 起才是强）。"""
        entries = [{"name": "万科A", "code": "000002", "ai_score": 75,
                    "ai_score_basis": "rule_based", "ai_model": "rule_based",
                    "ai_score_hits": ["MACD零轴上方+5"]}]
        msg = self.scorer.add_ai_info_to_message("test", entries)
        self.assertIn("🟡", msg)
        self.assertIn("中", msg)
        self.assertNotIn("🟢", msg)

    def test_90_score_still_green(self):
        """90 分仍然标为 🟢 强。"""
        entries = [{"name": "万科A", "code": "000002", "ai_score": 90,
                    "ai_score_basis": "rule_based", "ai_model": "rule_based",
                    "ai_score_hits": ["MACD零轴上方+5"]}]
        msg = self.scorer.add_ai_info_to_message("test", entries)
        self.assertIn("🟢", msg)
        self.assertIn("强", msg)

    def test_80_score_still_yellow(self):
        """80 分落在中档。"""
        entries = [{"name": "X", "code": "000000", "ai_score": 80,
                    "ai_score_basis": "rule_based", "ai_model": "rule_based"}]
        msg = self.scorer.add_ai_info_to_message("test", entries)
        self.assertIn("🟡", msg)
        self.assertNotIn("🟢", msg)

    def test_60_score_is_weak(self):
        """60 分以下现在是弱。"""
        entries = [{"name": "X", "code": "000000", "ai_score": 60,
                    "ai_score_basis": "rule_based", "ai_model": "rule_based"}]
        msg = self.scorer.add_ai_info_to_message("test", entries)
        self.assertIn("⚪", msg)
        self.assertIn("弱", msg)


if __name__ == "__main__":
    unittest.main()
