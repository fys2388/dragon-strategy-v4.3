# -*- coding: utf-8 -*-
"""Agent 学习闭环单测（全离线，不打真实行情接口）。

覆盖 5 个此前"文档声称有、实测为空"的环节：
1. loop_config     —— 完成窗口 / 样本门槛的唯一事实源
2. tracking        —— 第 3 个交易日即 completed（冷启动能开门）
3. weekly_optimizer—— 冷启动期 3 条完成样本即可出分析
4. evolution_engine—— 样本门槛 3、权重纳入 breakout、报告无副作用
5. health_monitor  —— 降级阶梯 L0→L3 真触发 + 推荐即恢复 + 同日幂等
6. user_feedback   —— 反馈真的能写入并被周度分析读到
7. ai_scorer       —— 无模型时不伪造概率（score_basis=rule_based）

所有写盘都被重定向到临时目录，不污染 data/。
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import loop_config  # noqa: E402
from strategies.macd_resonance import tracking  # noqa: E402
from strategies.macd_resonance import weekly_optimizer  # noqa: E402
from strategies.macd_resonance import evolution_engine  # noqa: E402
from strategies.macd_resonance import health_monitor  # noqa: E402
from strategies.macd_resonance import user_feedback  # noqa: E402
from strategies.macd_resonance import ai_scorer  # noqa: E402
from strategies.macd_resonance import ai_predictor  # noqa: E402


def _mkdtemp() -> str:
    return tempfile.mkdtemp(prefix="agent_loop_")


def _cleanup(path: str) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _trading_days(start_date: str, n: int) -> list:
    """从 start_date 之后开始，按 tracking._is_trading_day 口径（周一~周五）取 n 个交易日。"""
    d = datetime.strptime(start_date, "%Y-%m-%d")
    out = []
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def _kline_df(start_date: str, closes: list) -> pd.DataFrame:
    """按**交易日**顺序构造日K；closes 里留 None 即可模拟停牌/缺数据。

    注意必须跳过周末，否则和 tracking._get_trading_days() 推导出的交易日序列错位，
    day5 会永远匹配不到价格。
    """
    rows = []
    days = _trading_days(start_date, len(closes))
    for day, close in zip(days, closes):
        if close is None:
            continue
        rows.append({
            "date": day.strftime("%Y-%m-%d"),
            "open": close,
            "high": round(close * 1.01, 2),
            "low": round(close * 0.99, 2),
            "close": close,
            "volume": 100000 + len(rows),
        })
    return pd.DataFrame(rows)


class TestLoopConfig(unittest.TestCase):
    """完成窗口与样本门槛集中在 loop_config，不再散落魔数。"""

    def test_completion_day_is_3(self):
        self.assertEqual(loop_config.COMPLETION_DAY, 3)
        self.assertEqual(loop_config.COMPLETION_DAY_FIELD, "day3_return_pct")
        self.assertEqual(loop_config.FULL_TRACK_DAYS, 20)

    def test_min_samples_for_cold_start(self):
        self.assertEqual(loop_config.min_samples_for("weekly"), 3)
        self.assertEqual(loop_config.min_samples_for("evolution"), 3)
        self.assertEqual(loop_config.min_samples_for("weight"), 3)
        self.assertEqual(loop_config.min_samples_for("full"), loop_config.MIN_SAMPLES_FULL)
        self.assertLessEqual(loop_config.min_samples_for("weekly"), loop_config.MIN_SAMPLES_FULL)

    def test_completion_summary_shape(self):
        s = loop_config.completion_summary()
        self.assertEqual(s["completion_day"], 3)
        self.assertEqual(s["completion_field"], "day3_return_pct")
        self.assertEqual(s["full_track_days"], 20)
        self.assertIn("min_samples", s)
        self.assertEqual(s["min_samples"]["weekly"], 3)
        self.assertEqual(s["min_samples"]["evolution"], 3)


class TestTrackingCompletionDay3(unittest.TestCase):
    """第 3 个交易日收益可用即标记 completed，冷启动才能开出样本门。"""

    def setUp(self):
        self.tmp = _mkdtemp()
        self._orig = {
            "tracking": tracking.TRACKING_FILE,
            "performance": tracking.PERFORMANCE_FILE,
        }
        tracking.TRACKING_FILE = os.path.join(self.tmp, "tracking.jsonl")
        # 绩效汇总也要重定向，否则 get_performance_summary() 会写真实 data/ 目录
        tracking.PERFORMANCE_FILE = os.path.join(self.tmp, "performance_summary.json")

    def tearDown(self):
        tracking.TRACKING_FILE = self._orig["tracking"]
        tracking.PERFORMANCE_FILE = self._orig["performance"]
        _cleanup(self.tmp)

    def _seed(self, code="600001", recommend_date="2026-09-07"):
        """2026-09-07 是周一：交易日序列为 09-08(d1) 09-09(d2) 09-10(d3) 09-11(d4) 09-14(d5)..."""
        tracking.record_recommendations(
            [{"code": code, "name": "测试股", "price": 10.0, "score": 3.5}],
            "resonance", f"{recommend_date} 10:00:00", regime="sideways",
        )

    def test_completes_on_day3_not_day20(self):
        self._seed()
        # 只给 5 个交易日行情：09-08(d1) 09-09(d2) 09-10(d3)=10.6 09-11(d4) 09-14(d5)=10.2
        df = _kline_df("2026-09-07", [10.3, 10.1, 10.6, 10.4, 10.2])
        with mock.patch.object(tracking.ds, "get_kline_daily", return_value=df):
            stats = tracking.update_performance()
        self.assertEqual(stats["completed"], 1, msg=stats)
        rec = tracking._load_records()[0]
        self.assertEqual(rec["status"], "completed")
        self.assertIn("completed_at", rec)
        # 推荐价 10.0 → day3 收 10.6
        self.assertAlmostEqual(rec["day3_return_pct"], 6.0, places=2)
        self.assertAlmostEqual(rec["day5_return_pct"], 2.0, places=2)
        # 只走了 5 个交易日，长窗口不该被填成假数据
        self.assertIsNone(rec.get("day10_return_pct"))
        self.assertIsNone(rec.get("day20_return_pct"))

    def test_gap_in_kline_does_not_early_break(self):
        """缺一个交易日时不能整段中断，否则短窗口收益永远算不出来。"""
        self._seed()
        # 09-09 停牌（None → 不出现在 K 线里）
        df = _kline_df("2026-09-07", [10.3, None, 10.6, 10.4, 10.2])
        with mock.patch.object(tracking.ds, "get_kline_daily", return_value=df):
            stats = tracking.update_performance()
        rec = tracking._load_records()[0]
        self.assertIsNotNone(rec.get("day3_return_pct"), msg="停牌跳过后 day3 仍应算出")
        self.assertAlmostEqual(rec.get("day3_return_pct"), 6.0, places=2)
        self.assertIsNotNone(rec.get("day5_return_pct"))
        self.assertEqual(stats["updated"], 1)

    def test_kline_error_keeps_tracking(self):
        self._seed()
        def _boom(*a, **k):
            raise RuntimeError("数据源不可用")
        with mock.patch.object(tracking.ds, "get_kline_daily", side_effect=_boom):
            stats = tracking.update_performance()
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(tracking._load_records()[0]["status"], "tracking")

    def test_daily_recommend_counts(self):
        tracking.record_recommendations(
            [{"code": "600001", "name": "A", "price": 10.0}],
            "breakout", "2026-09-08 10:00:00",
        )
        tracking.record_recommendations(
            [{"code": "600002", "name": "B", "price": 20.0},
             {"code": "600003", "name": "C", "price": 30.0}],
            "breakout", "2026-09-09 10:00:00",
        )
        # 同日重复推送不重复计数
        tracking.record_recommendations(
            [{"code": "600002", "name": "B", "price": 20.0}],
            "breakout", "2026-09-09 10:30:00",
        )
        counts = tracking.get_daily_recommend_counts()
        self.assertEqual(counts.get("2026-09-08"), 1)
        self.assertEqual(counts.get("2026-09-09"), 2)
        # 按策略过滤
        self.assertEqual(tracking.get_daily_recommend_counts(strategy="breakout").get("2026-09-08"), 1)
        self.assertEqual(tracking.get_daily_recommend_counts(strategy="oversold"), {})

    def test_performance_summary_carries_config_and_breakout(self):
        tracking.record_recommendations(
            [{"code": "600001", "name": "A", "price": 10.0}],
            "breakout", "2026-09-08 10:00:00",
        )
        summary = tracking.get_performance_summary()
        self.assertIn("tracking_config", summary)
        self.assertEqual(summary["tracking_config"]["completion_day"], 3)
        self.assertEqual(summary["tracking_config"]["min_samples"]["weekly"], 3)
        self.assertIn("breakout", summary["by_strategy"])


class TestWeeklyOptimizerColdStart(unittest.TestCase):
    """冷启动期 3 条完成样本即可出分析（原门槛 5，永远打不开）。"""

    @staticmethod
    def _rec(i, day3_ret, day5_ret=None):
        return {
            "strategy": "breakout",
            "status": "completed",
            "code": f"60000{i}",
            "day3_return_pct": day3_ret,
            "day5_return_pct": day5_ret,
        }

    def test_three_completed_records_pass_gate(self):
        recs = [self._rec(1, 2.0), self._rec(2, -1.0), self._rec(3, 4.0)]
        out = weekly_optimizer.analyze_breakout_performance(recs)
        self.assertEqual(out["status"], "ok", msg=out)
        self.assertEqual(out["count"], 3)
        self.assertAlmostEqual(out["avg_return"], 5.0 / 3, places=2)
        self.assertAlmostEqual(out["win_rate"], 66.7, places=1)

    def test_two_completed_records_still_insufficient(self):
        out = weekly_optimizer.analyze_breakout_performance([self._rec(1, 2.0), self._rec(2, 1.0)])
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["min_needed"], 3)

    def test_day5_only_records_do_not_count(self):
        """只算到 5 日、没算到 3 日的记录不算完成样本。"""
        recs = [self._rec(1, None, day5_ret=3.0) for _ in range(10)]
        out = weekly_optimizer.analyze_breakout_performance(recs)
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(out["count"], 0)

    def test_only_breakout_and_completed_counted(self):
        recs = [
            self._rec(1, 2.0),
            {"strategy": "resonance", "status": "completed", "day3_return_pct": 9.9},
            {"strategy": "breakout", "status": "tracking", "day3_return_pct": 9.9},
        ]
        out = weekly_optimizer.analyze_breakout_performance(recs)
        self.assertEqual(out["count"], 1)


class TestEvolutionEngine(unittest.TestCase):
    """样本门槛 3、权重纳入 breakout、报告生成不产生副作用。"""

    def setUp(self):
        self.tmp = _mkdtemp()
        self._orig = {
            "evolution_log": evolution_engine.EVOLUTION_LOG_FILE,
            "ab_test": evolution_engine.AB_TEST_FILE,
            "load_records": evolution_engine._load_records,
        }
        evolution_engine.EVOLUTION_LOG_FILE = os.path.join(self.tmp, "evolution_log.jsonl")
        evolution_engine.AB_TEST_FILE = os.path.join(self.tmp, "ab_test_state.json")
        # 注意：patch 必须在整个测试期间持续生效，不能用 with mock.patch(...) 包住
        # 只构造 engine 的写法——with 一退出补丁就没了，后面 evaluate 会去读真实
        # data/tracking.jsonl（只有 1 条 tracking 记录），count 恒为 0。
        self._records = []
        evolution_engine._load_records = lambda: list(self._records)

    def tearDown(self):
        evolution_engine.EVOLUTION_LOG_FILE = self._orig["evolution_log"]
        evolution_engine.AB_TEST_FILE = self._orig["ab_test"]
        evolution_engine._load_records = self._orig["load_records"]
        _cleanup(self.tmp)

    @staticmethod
    def _recs(n, strategy="breakout", ret=2.0):
        return [{"strategy": strategy, "status": "completed",
                 "code": f"60000{i}", "day3_return_pct": ret} for i in range(1, n + 1)]

    def _engine_with(self, recs):
        self._records = recs
        return evolution_engine.EvolutionEngine()

    def test_evolution_gate_is_3(self):
        eng = self._engine_with(self._recs(3))
        out = eng.evaluate_current_params()
        self.assertEqual(out["status"], "ok", msg=out)
        self.assertEqual(out["count"], 3)
        self.assertIn("breakout", out["by_strategy"])

        eng2 = self._engine_with(self._recs(2))
        out2 = eng2.evaluate_current_params()
        self.assertEqual(out2["status"], "insufficient_data")
        self.assertEqual(out2["min_needed"], 3)

    def test_weights_include_breakout(self):
        recs = self._recs(3, "breakout", ret=5.0)
        eng = self._engine_with(recs)
        with mock.patch.object(evolution_engine, "BASE_DIR", self.tmp):
            out = eng.optimize_strategy_weights()
        self.assertEqual(out["status"], "ok", msg=out)
        self.assertIn("breakout", out["weights"])
        self.assertEqual(len(out["weights"]), 3)  # resonance / oversold / breakout
        total = sum(out["weights"].values())
        # 各项独立保留 2 位小数，合计允许 ±0.03 的舍入误差
        self.assertAlmostEqual(total, 1.0, delta=0.03)

    def test_get_evolution_report_is_side_effect_free(self):
        """只读报告不应该写权重/进化日志（原来会在报告里偷偷改参数）。"""
        eng = self._engine_with(self._recs(3))
        eng.get_evolution_report()
        weights_file = os.path.join(self.tmp, "strategy_weights.json")
        self.assertFalse(os.path.exists(weights_file),
                         msg="get_evolution_report 不应写入 strategy_weights.json")
        self.assertFalse(os.path.exists(evolution_engine.EVOLUTION_LOG_FILE),
                         msg="get_evolution_report 不应写进化日志")


class TestHealthMonitorDegradation(unittest.TestCase):
    """降级阶梯要真触发、推荐即恢复、同一天重复记录不放大零推荐天数。"""

    def setUp(self):
        self.tmp = _mkdtemp()
        self._orig = health_monitor.HEALTH_FILE
        health_monitor.HEALTH_FILE = os.path.join(self.tmp, "system_health.json")

    def tearDown(self):
        health_monitor.HEALTH_FILE = self._orig
        _cleanup(self.tmp)

    def test_degradation_ladder(self):
        h = health_monitor.HealthMonitor()
        for i in range(3):
            h.record_recommendations(0, date=f"2026-09-0{i + 1}")
        self.assertEqual(h.state["degradation_level"], 1)
        for i in range(3, 5):
            h.record_recommendations(0, date=f"2026-09-0{i + 1}")
        self.assertEqual(h.state["degradation_level"], 2)
        for i in range(5, 7):
            h.record_recommendations(0, date=f"2026-09-1{i - 4}")
        self.assertEqual(h.state["degradation_level"], 3)

    def test_recovery_on_recommendation(self):
        h = health_monitor.HealthMonitor()
        for i in range(3):
            h.record_recommendations(0, date=f"2026-09-0{i + 1}")
        self.assertEqual(h.state["degradation_level"], 1)
        h.record_recommendations(2, date="2026-09-04")
        self.assertEqual(h.state["degradation_level"], 0)
        self.assertEqual(h.state["consecutive_zero_days"], 0)

    def test_same_day_recording_is_idempotent(self):
        """盘中一天会被调用约 10 次，不能让连续0推荐天数被放大。"""
        h = health_monitor.HealthMonitor()
        for _ in range(10):
            h.record_recommendations(0, date="2026-09-01")
        self.assertEqual(h.state["consecutive_zero_days"], 1)
        self.assertEqual(h.state["degradation_level"], 0)

    def test_override_matches_scanner_keys(self):
        """降级覆盖的键必须和三个扫描器实际读取的键对得上。"""
        h = health_monitor.HealthMonitor()
        for i in range(5):
            h.record_recommendations(0, date=f"2026-09-0{i + 1}")
        ov = h.get_current_params_override()
        self.assertEqual(ov["level"], 2)
        for key in ("macd", "oversold", "breakout", "general"):
            self.assertIn(key, ov, msg=f"缺少覆盖分组 {key}")
        self.assertGreater(ov["macd"]["min_score"], 0)

    def test_merge_override_does_not_mutate_base(self):
        base = {"min_score": 2.0, "max_recommendations": 4}
        ov = {"macd": {"min_score": 1.5}, "level": 1, "general": {}}
        merged = health_monitor.HealthMonitor.merge_override(base, "macd", ov)
        self.assertEqual(merged["min_score"], 1.5)
        self.assertEqual(merged["max_recommendations"], 4)  # 未被覆盖的保留
        self.assertEqual(base["min_score"], 2.0)            # 原对象不被改
        self.assertNotIn("level", merged)


class TestUserFeedback(unittest.TestCase):
    """反馈必须真的能写入并被周度分析读到（此前 0 调用方，数据恒为 0）。"""

    def setUp(self):
        self.tmp = _mkdtemp()
        self._orig = user_feedback.FEEDBACK_FILE
        user_feedback.FEEDBACK_FILE = os.path.join(self.tmp, "user_feedback.jsonl")

    def tearDown(self):
        user_feedback.FEEDBACK_FILE = self._orig
        _cleanup(self.tmp)

    def test_record_and_analyze(self):
        rec = user_feedback.record_feedback(
            "negative", "推荐了但当天就跌停，入场条件太宽松", stock_code="600519", stock_name="贵州茅台",
        )
        self.assertEqual(rec["type"], "negative")
        self.assertEqual(len(user_feedback.load_feedback(days=30)), 1)

        out = user_feedback.analyze_feedback(days=30)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["negative"], 1)
        self.assertIn("600519", out["negative_stocks"])

    def test_no_feedback(self):
        self.assertEqual(user_feedback.load_feedback(), [])
        out = user_feedback.analyze_feedback()
        self.assertEqual(out["status"], "no_feedback")


class TestAiScorerHonesty(unittest.TestCase):
    """无训练模型时不伪造概率：主字段是规则打分，并显式标注依据。"""

    def test_rule_based_predict_labels_itself(self):
        predictor = ai_predictor.AIPredictor.__new__(ai_predictor.AIPredictor)
        predictor.model = None
        features = pd.Series({
            "macd_golden_cross": 1, "macd_above_zero": 1, "ma_bullish": 1,
            "rsi_6": 50, "new_high_20d": 0, "volume_ratio_5d": 1.0,
            "return_5d": 0.0, "boll_position": 0.5,
        })
        out = predictor._rule_based_predict(features)
        self.assertEqual(out["score_basis"], "rule_based")
        self.assertFalse(out["probability_is_actual_model"])
        self.assertGreaterEqual(out["rule_score"], 50)
        self.assertLessEqual(out["rule_score"], 100)

    def test_model_info_admits_no_model(self):
        predictor = ai_predictor.AIPredictor.__new__(ai_predictor.AIPredictor)
        predictor.model = None
        info = predictor.get_model_info()
        self.assertEqual(info["status"], "no_model")
        self.assertFalse(info["model_trained"])

    def test_score_candidates_marks_basis_and_keeps_probability_absent(self):
        predictor = ai_predictor.AIPredictor.__new__(ai_predictor.AIPredictor)
        predictor.model = None
        rule_out = {
            "score_basis": "rule_based",
            "probability_is_actual_model": False,
            "rule_score": 72.0,
            "probability": 0.72,
            "prediction": 1,
            "model_used": "rule_based",
            "rule_hits": ["MACD金叉+10"],
        }
        scorer = ai_scorer.AIScorer.__new__(ai_scorer.AIScorer)
        scorer.min_probability = 0.55
        scorer.predictor = mock.MagicMock(predict=mock.MagicMock(return_value=rule_out))

        cand = [{"code": "600519", "name": "贵州茅台", "price": 1500.0}]
        out = scorer.score_candidates(cand, "resonance")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ai_score_basis"], "rule_based")
        self.assertAlmostEqual(out[0]["ai_score"], 72.0)
        self.assertNotIn("ai_probability", out[0],
                         msg="规则打分不应写出 ai_probability，避免被当成真实概率")

    def test_message_wording_depends_on_basis(self):
        scorer = ai_scorer.AIScorer.__new__(ai_scorer.AIScorer)
        scorer.min_probability = 0.55
        rule_entry = {"code": "600519", "name": "贵州茅台", "ai_score": 72.0,
                      "ai_score_basis": "rule_based", "ai_model": "rule_based",
                      "ai_score_hits": ["MACD金叉+10"]}
        text = scorer.add_ai_info_to_message("基础消息", [rule_entry])
        self.assertIn("规则打分", text)
        # 规则打分不允许把分数写成"上涨概率 XX"
        self.assertIn("非上涨概率", text)
        self.assertNotIn("上涨概率72", text)

        model_entry = {"code": "600519", "name": "贵州茅台", "ai_score": 78.0,
                       "ai_score_basis": "model", "ai_model": "lightgbm"}
        text2 = scorer.add_ai_info_to_message("基础消息", [model_entry])
        self.assertIn("上涨概率78", text2)


if __name__ == "__main__":
    unittest.main()
