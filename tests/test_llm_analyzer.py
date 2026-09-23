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

    def test_lotus_holds_still_falls_back_without_code(self):
        """莲花控股 名字里没有行业词，仅靠关键词会归"综合"（保留旧行为）。"""
        industry = self.analyzer._infer_industry("莲花控股")
        self.assertEqual(industry, "综合")

    def test_lotus_holds_falls_back_to_food_via_code(self):
        """莲花控股(600186) 通过代码兜底表归到食品饮料。"""
        industry = self.analyzer._infer_industry("莲花控股", code="600186")
        self.assertEqual(industry, "食品饮料")

    def test_tianwu_is_electronics(self):
        """天沃科技主营军工电子，命中"电子"关键词。"""
        self.assertEqual(self.analyzer._infer_industry("天沃科技"), "电子")

    def test_qianjin_pharma_is_pharma(self):
        """千金药业应命中医药（关键词新增"药业"）。"""
        self.assertEqual(self.analyzer._infer_industry("千金药业"), "医药")

    def test_kweichow_moutai_is_food(self):
        """贵州茅台应命中食品饮料（白酒龙头）。"""
        self.assertEqual(self.analyzer._infer_industry("贵州茅台"), "食品饮料")

    def test_wuliangye_is_food(self):
        """五粮液应命中食品饮料。"""
        self.assertEqual(self.analyzer._infer_industry("五粮液"), "食品饮料")

    def test_yili_is_food(self):
        """伊利股份应命中食品饮料。"""
        self.assertEqual(self.analyzer._infer_industry("伊利股份"), "食品饮料")

    def test_byd_is_automotive(self):
        """比亚迪应命中汽车（关键词新增"比亚迪"）。"""
        self.assertEqual(self.analyzer._infer_industry("比亚迪"), "汽车")

    def test_tangli_bread_falls_back_via_code(self):
        """桃李面包(603866) 名字里没有"面包"关键词，走代码兜底。"""
        self.assertEqual(
            self.analyzer._infer_industry("桃李面包", code="603866"), "食品饮料"
        )

    def test_code_none_or_empty_falls_back_to_generic(self):
        """code 为空/None 时不查询兜底表，仍归综合。"""
        self.assertEqual(self.analyzer._infer_industry("莲花控股", code=""), "综合")
        self.assertEqual(self.analyzer._infer_industry("莲花控股", code=None), "综合")

    def test_keyword_priority_over_code_fallback(self):
        """关键词命中优先于代码兜底表（兜底表不覆盖关键词）。"""
        from strategies.macd_resonance.llm_analyzer import STOCK_CODE_INDUSTRY
        # 临时把万科的代码标成"化工"，看是否被关键词覆盖
        STOCK_CODE_INDUSTRY["000002"] = "化工"
        try:
            # 万科 关键词命中"房地产"，优先于代码兜底
            self.assertEqual(
                self.analyzer._infer_industry("万科", code="000002"), "房地产"
            )
        finally:
            STOCK_CODE_INDUSTRY.pop("000002", None)


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
