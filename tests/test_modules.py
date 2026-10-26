"""
alpha-pick 单元测试

运行：python -m pytest tests/ -v
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config.settings import USER_PROFILE, DATA_DIR


class TestMarketGate(unittest.TestCase):
    """测试大盘闸门"""

    def test_evaluate_returns_dict(self):
        from src.risk.market_gate import market_gate
        result = market_gate.evaluate()
        self.assertIsInstance(result, dict)
        self.assertIn("score", result)
        self.assertIn("level", result)
        self.assertIn("summary", result)

    def test_score_range(self):
        from src.risk.market_gate import market_gate
        result = market_gate.evaluate()
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 10)

    def test_level_valid(self):
        from src.risk.market_gate import market_gate
        result = market_gate.evaluate()
        valid_levels = ["strong", "normal", "weak", "closed"]
        self.assertIn(result["level"], valid_levels)


class TestPositionManager(unittest.TestCase):
    """测试仓位管理"""

    def setUp(self):
        from src.risk.position import PositionManager
        self.pm = PositionManager(capital=500000)

    def test_calculate_position_size(self):
        signal = {
            "code": "600519",
            "name": "贵州茅台",
            "entry_price": 1500.0,
            "stop_loss": 1395.0,
            "target_1": 1725.0,
            "target_2": 1875.0,
        }
        result = self.pm.calculate_position_size(signal)
        self.assertIn("buy_shares", result)
        self.assertIn("total_amount", result)
        self.assertIn("position_pct", result)
        self.assertIn("batch_plan", result)
        self.assertGreater(result["buy_shares"], 0)
        self.assertLessEqual(result["position_pct"], 100)

    def test_batch_plan_sums_to_total(self):
        signal = {
            "code": "600519",
            "name": "贵州茅台",
            "entry_price": 1500.0,
            "stop_loss": 1395.0,
            "target_1": 1725.0,
            "target_2": 1875.0,
        }
        result = self.pm.calculate_position_size(signal)
        batch_total = (
            result["batch_plan"]["batch_1"]["shares"] +
            result["batch_plan"]["batch_2"]["shares"] +
            result["batch_plan"]["batch_3"]["shares"]
        )
        self.assertEqual(batch_total, result["buy_shares"])

    def test_positions_persistence(self):
        # 测试添加和加载
        self.pm.add_position({
            "code": "600519",
            "name": "贵州茅台",
            "entry_price": 1500.0,
            "cost_price": 1500.0,
            "shares": 100,
            "stop_loss": 1395.0,
            "target_1": 1725.0,
            "target_2": 1875.0,
            "entry_date": datetime.now().strftime("%Y-%m-%d"),
        })
        self.assertEqual(len(self.pm.positions), 1)
        self.assertEqual(self.pm.positions[0]["code"], "600519")

        # 清除测试数据
        self.pm.remove_position("600519")
        self.assertEqual(len(self.pm.positions), 0)


class TestPerformanceTracker(unittest.TestCase):
    """测试绩效追踪"""

    def setUp(self):
        # 使用临时文件
        self.temp_file = str(DATA_DIR / "test_performance_history.json")
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)

    def tearDown(self):
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)

    def test_record_daily(self):
        from src.risk.performance_tracker import PerformanceTracker
        tracker = PerformanceTracker(history_file=self.temp_file)

        tracker.record_daily({
            "date": "2026-10-26",
            "total_equity": 500000.0,
            "total_positions": 0,
            "total_cost": 0,
            "total_pnl": 0,
            "total_pnl_pct": 0,
            "market_gate_level": "weak",
            "market_gate_score": 3.1,
            "new_signals": [],
            "closed_trades": [],
            "holdings": [],
        })

        self.assertEqual(len(tracker.history["daily_records"]), 1)
        self.assertEqual(tracker.history["daily_records"][0]["date"], "2026-10-26")

    def test_get_metrics(self):
        from src.risk.performance_tracker import PerformanceTracker
        tracker = PerformanceTracker(history_file=self.temp_file)

        # 记录几天数据
        for i in range(5):
            tracker.record_daily({
                "date": f"2026-10-{22+i:02d}",
                "total_equity": 500000 + i * 1000,
                "total_positions": 2,
                "total_cost": 200000,
                "total_pnl": i * 1000,
                "total_pnl_pct": i * 0.5,
                "market_gate_level": "normal",
                "market_gate_score": 5.0,
                "new_signals": [],
                "closed_trades": [],
                "holdings": [],
            })

        metrics = tracker.get_metrics()
        self.assertIn("total_return_pct", metrics)
        self.assertIn("max_drawdown_pct", metrics)
        self.assertIn("sharpe_ratio", metrics)
        self.assertGreater(metrics["trading_days"], 0)


class TestCorrelationAnalyzer(unittest.TestCase):
    """测试相关性分析"""

    def test_analyze_empty_positions(self):
        from src.risk.correlation import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        result = analyzer.analyze([])
        self.assertIsNotNone(result)
        self.assertIn("recommendations", result)

    def test_analyze_single_position(self):
        from src.risk.correlation import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        result = analyzer.analyze([{"code": "600519", "name": "贵州茅台"}])
        self.assertIsNotNone(result)
        self.assertIn("recommendations", result)

    def test_check_before_add_empty(self):
        from src.risk.correlation import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        result = analyzer.check_before_add("600519", [])
        self.assertTrue(result["should_add"])


class TestDataCache(unittest.TestCase):
    """测试数据缓存"""

    def test_cache_set_get(self):
        from src.data.cache import cache
        cache.set("test_key", {"value": 123}, ttl=3600)
        result = cache.get("test_key")
        self.assertEqual(result, {"value": 123})

    def test_cache_ttl_expiry(self):
        from src.data.cache import cache
        # 设置缓存
        cache.set("test_expired", {"value": 456})
        # 用负TTL获取（模拟已过期）
        result = cache.get("test_expired", ttl=-1)
        self.assertIsNone(result)

    def test_cache_clear(self):
        from src.data.cache import cache
        cache.set("test_clear", {"value": 789}, ttl=3600)
        cache.clear()
        result = cache.get("test_clear")
        self.assertIsNone(result)


class TestSignalDetector(unittest.TestCase):
    """测试信号检测"""

    def test_detector_init(self):
        from src.signals.entry import signal_detector
        self.assertIsNotNone(signal_detector)

    def test_detect_all_empty(self):
        from src.signals.entry import signal_detector
        empty_df = pd.DataFrame()
        result = signal_detector.detect_all(empty_df)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
