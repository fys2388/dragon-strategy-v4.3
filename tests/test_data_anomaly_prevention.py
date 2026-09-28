# -*- coding: utf-8 -*-
"""数据异常预防单测：验证数据源过滤、硬过滤区分、健康度降级。

历史事故：2026-09-23 推送 3，硬过滤后剩 0 只，
但 agent 没有检测到异常，直接推送"无推荐"消息给用户。
根本原因：数据源返回 price=0/cap=0 的股票，被硬过滤全部拒绝。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.filters import pass_hard_filters  # noqa: E402
from strategies.macd_resonance.health_monitor import HealthMonitor  # noqa: E402


class TestFiltersDataAnomaly(unittest.TestCase):
    """pass_hard_filters 区分'数据异常'和'正常拒绝'。"""

    def test_price_zero_is_data_anomaly(self):
        """price=0 应标记为'数据异常'而非'正常拒绝'。"""
        stock = {
            "code": "600000",
            "name": "浦发银行",
            "price": 0.0,  # 数据异常
            "float_cap_yi": 100.0,
        }
        passed, reason = pass_hard_filters(stock)
        self.assertFalse(passed)
        self.assertIn("数据异常", reason)
        self.assertIn("价格", reason)

    def test_cap_zero_is_data_anomaly(self):
        """cap=0 应标记为'数据异常'而非'正常拒绝'。"""
        stock = {
            "code": "600000",
            "name": "浦发银行",
            "price": 10.0,
            "float_cap_yi": 0.0,  # 数据异常
        }
        passed, reason = pass_hard_filters(stock)
        self.assertFalse(passed)
        self.assertIn("数据异常", reason)
        self.assertIn("流通市值", reason)

    def test_price_below_min_is_normal_reject(self):
        """price < 3.5 但 > 0 应是'正常拒绝'而非'数据异常'。"""
        stock = {
            "code": "600000",
            "name": "浦发银行",
            "price": 2.5,  # 低于最小值但 > 0
            "float_cap_yi": 100.0,
        }
        passed, reason = pass_hard_filters(stock)
        self.assertFalse(passed)
        self.assertNotIn("数据异常", reason)
        self.assertIn("价格", reason)

    def test_cap_below_min_is_normal_reject(self):
        """cap < 40 但 > 0 应是'正常拒绝'而非'数据异常'。"""
        stock = {
            "code": "600000",
            "name": "浦发银行",
            "price": 10.0,
            "float_cap_yi": 30.0,  # 低于最小值但 > 0
        }
        passed, reason = pass_hard_filters(stock)
        self.assertFalse(passed)
        self.assertNotIn("数据异常", reason)
        self.assertIn("流通市值", reason)

    def test_valid_stock_passes(self):
        """正常股票应通过硬过滤。"""
        stock = {
            "code": "600000",
            "name": "浦发银行",
            "price": 10.0,
            "float_cap_yi": 100.0,
            "amount_20d_wan": 10000.0,
            "amplitude_20d_pct": 20.0,
        }
        passed, reason = pass_hard_filters(stock)
        self.assertTrue(passed)
        self.assertIn("通过", reason)


class TestHealthMonitorAnomalyDegradation(unittest.TestCase):
    """HealthMonitor 异常计数纳入降级逻辑。"""

    def setUp(self):
        """每个测试用例用独立的内存 state，不读写真实文件。"""
        self.monitor = HealthMonitor()
        self.monitor.state = {
            "daily_recommendations": {},
            "consecutive_zero_days": 0,
            "degradation_level": 0,
            "last_recommendation_date": None,
            "degradation_history": [],
            "recovery_history": [],
            "anomaly_count": 0,
            "anomaly_history": [],
            "updated_at": None,
        }
        # mock _save_state 避免写文件
        self.monitor._save_state = mock.Mock()

    def test_anomaly_count_triggers_degradation(self):
        """累计 3 次数据异常应触发 Level 1 降级。"""
        self.assertEqual(self.monitor.state["degradation_level"], 0)
        
        # 记录 3 次数据异常
        for i in range(3):
            self.monitor.record_anomaly("硬过滤0只", date="2026-09-23")
        
        # 检查降级
        self.assertEqual(self.monitor.state["degradation_level"], 1)
        self.assertEqual(len(self.monitor.state["degradation_history"]), 1)
        self.assertIn("数据异常", self.monitor.state["degradation_history"][0]["reason"])

    def test_anomaly_count_below_threshold_no_degradation(self):
        """累计 2 次数据异常不应触发降级。"""
        self.assertEqual(self.monitor.state["degradation_level"], 0)
        
        # 记录 2 次数据异常
        for i in range(2):
            self.monitor.record_anomaly("硬过滤0只", date="2026-09-23")
        
        # 检查降级
        self.assertEqual(self.monitor.state["degradation_level"], 0)
        self.assertEqual(len(self.monitor.state["degradation_history"]), 0)

    def test_zero_days_still_triggers_degradation(self):
        """连续 3 天 0 推荐仍应触发降级（原有逻辑不变）。"""
        self.assertEqual(self.monitor.state["degradation_level"], 0)
        
        # 记录 3 天 0 推荐
        for i in range(3):
            self.monitor.record_recommendations(0, date=f"2026-09-{20+i}")
        
        # 检查降级
        self.assertEqual(self.monitor.state["degradation_level"], 1)
        self.assertEqual(len(self.monitor.state["degradation_history"]), 1)
        self.assertIn("0推荐", self.monitor.state["degradation_history"][0]["reason"])

    def test_both_conditions_trigger_degradation(self):
        """连续 0 推荐 + 数据异常应触发降级（记录组合原因）。"""
        self.assertEqual(self.monitor.state["degradation_level"], 0)
        
        # 记录 1 天 0 推荐 + 3 次数据异常（达到阈值）
        self.monitor.record_recommendations(0, date="2026-09-20")
        self.monitor.record_anomaly("硬过滤0只", date="2026-09-20")
        self.monitor.record_anomaly("硬过滤0只", date="2026-09-21")
        self.monitor.record_anomaly("硬过滤0只", date="2026-09-22")
        
        # 检查降级
        self.assertEqual(self.monitor.state["degradation_level"], 1)
        self.assertEqual(len(self.monitor.state["degradation_history"]), 1)
        # 原因应包含"数据异常"
        self.assertIn("数据异常", self.monitor.state["degradation_history"][0]["reason"])


if __name__ == "__main__":
    unittest.main()