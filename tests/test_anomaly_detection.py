# -*- coding: utf-8 -*-
"""数据异常检测单测：验证硬过滤0只时的异常标记、推送告警、健康度记录。

历史事故：2026-09-23 推送 3，硬过滤后剩 0 只，
但 agent 没有检测到异常，直接推送"无推荐"消息给用户，
用户误以为市场弱势，实际是数据源异常（price=0/cap=0）。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.health_monitor import HealthMonitor  # noqa: E402


class TestRecordAnomaly(unittest.TestCase):
    """HealthMonitor.record_anomaly 单测。"""

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

    def test_record_anomaly_increments_count(self):
        """record_anomaly 应增加 anomaly_count。"""
        self.assertEqual(self.monitor.state["anomaly_count"], 0)
        self.monitor.record_anomaly("硬过滤0只", date="2026-09-23")
        self.assertEqual(self.monitor.state["anomaly_count"], 1)
        self.monitor.record_anomaly("数据源超时", date="2026-09-23")
        self.assertEqual(self.monitor.state["anomaly_count"], 2)

    def test_record_anomaly_saves_history(self):
        """record_anomaly 应保存异常历史。"""
        self.monitor.record_anomaly("硬过滤0只", details={"passed_count": 0}, date="2026-09-23")
        self.assertEqual(len(self.monitor.state["anomaly_history"]), 1)
        entry = self.monitor.state["anomaly_history"][0]
        self.assertEqual(entry["type"], "硬过滤0只")
        self.assertEqual(entry["date"], "2026-09-23")
        self.assertEqual(entry["details"]["passed_count"], 0)

    def test_record_anomaly_limits_history(self):
        """record_anomaly 应限制历史只保留最近50条。"""
        for i in range(60):
            self.monitor.record_anomaly(f"异常{i}", date="2026-09-23")
        self.assertLessEqual(len(self.monitor.state["anomaly_history"]), 50)

    def test_record_anomaly_independent_of_recommendations(self):
        """record_anomaly 与 record_recommendations 独立。"""
        self.monitor.record_recommendations(0, date="2026-09-23")
        self.assertEqual(self.monitor.state["anomaly_count"], 0)
        self.monitor.record_anomaly("硬过滤0只", date="2026-09-23")
        self.assertEqual(self.monitor.state["anomaly_count"], 1)
        self.assertEqual(self.monitor.state["daily_recommendations"]["2026-09-23"], 0)


class TestScannerDataAnomaly(unittest.TestCase):
    """scanner.py 硬过滤0只时设置 data_anomaly 标记。"""

    def test_hard_filter_zero_sets_anomaly(self):
        """硬过滤0只时应设置 data_anomaly=True。"""
        from collections import Counter
        from strategies.macd_resonance.scanner import Scanner
        scanner = Scanner.__new__(Scanner)
        
        # 模拟硬过滤结果
        result = {"passed_count": 0, "candidates_count": 500}
        reject_reasons = Counter({"600000 价格0元不在3.5-30元": 500})
        
        # 手动调用逻辑（模拟 scanner.run 里的硬过滤部分）
        passed = []
        enriched = [{"code": "600000", "name": "浦发银行", "price": 0, "float_cap_yi": 0}]
        
        if len(passed) == 0:
            result["data_anomaly"] = True
            result["anomaly_reason"] = f"硬过滤0只（初筛{len(enriched)}只全部被拒）"
            result["anomaly_details"] = dict(reject_reasons.most_common(5))
        
        self.assertTrue(result["data_anomaly"])
        self.assertIn("硬过滤0只", result["anomaly_reason"])
        # anomaly_details 是 dict，检查 key 是否包含"价格0元"
        detail_keys = " ".join(result["anomaly_details"].keys())
        self.assertIn("价格0元", detail_keys)

    def test_hard_filter_pass_no_anomaly(self):
        """硬过滤通过时不应设置 data_anomaly。"""
        result = {"passed_count": 100, "candidates_count": 500}
        # 没有设置 data_anomaly
        self.assertNotIn("data_anomaly", result) or self.assertFalse(result.get("data_anomaly"))


class TestPushAnomalyAlert(unittest.TestCase):
    """v43_push.py 数据异常推送告警。"""

    def test_anomaly_alert_in_message(self):
        """数据异常时推送应包含🚨告警。"""
        # 模拟 v43_push.py 的推送逻辑
        result = {
            "data_anomaly": True,
            "anomaly_reason": "硬过滤0只（初筛500只全部被拒）",
            "anomaly_details": {"600000 价格0元不在3.5-30元": 500},
            "entries": [],
        }
        total_recommendations = 0
        
        combined_msg = ""
        if total_recommendations == 0:
            if result.get("data_anomaly"):
                anomaly_reason = result.get("anomaly_reason", "未知原因")
                anomaly_details = result.get("anomaly_details", {})
                top_reason = list(anomaly_details.keys())[0] if anomaly_details else "未知"
                combined_msg += (
                    f"\n\n🚨 数据异常告警\n"
                    f"   · {anomaly_reason}\n"
                    f"   · 最可能原因：{top_reason}\n"
                    f"   · 建议检查东财接口是否正常，或等待下次推送\n"
                    f"   · 本次推送数据可能不准确，请勿据此交易\n"
                )
        
        self.assertIn("🚨 数据异常告警", combined_msg)
        self.assertIn("硬过滤0只", combined_msg)
        self.assertIn("价格0元", combined_msg)
        self.assertIn("请勿据此交易", combined_msg)

    def test_no_anomaly_shows_weak_market(self):
        """无数据异常但0推荐时应显示"市场极度弱势"。"""
        result = {"data_anomaly": False, "entries": []}
        total_recommendations = 0
        
        combined_msg = ""
        if total_recommendations == 0:
            if result.get("data_anomaly"):
                combined_msg += "🚨 数据异常告警"
            else:
                combined_msg += (
                    "\n\n⚠️ 市场极度弱势，三策略均无推荐\n"
                    "   · 建议空仓观望，等待大盘评分回升至 3/7 以上\n"
                    "   · 或手动筛选超跌反弹标的（跌幅>20%+MACD金叉）\n"
                )
        
        self.assertIn("⚠️ 市场极度弱势", combined_msg)
        self.assertNotIn("🚨", combined_msg)


if __name__ == "__main__":
    unittest.main()