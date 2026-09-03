# -*- coding: utf-8 -*-
"""系统健康度监控与自动降级机制。

核心能力：
1. 记录每天的推荐数量和质量
2. 监控连续0推荐天数
3. 自动降级：连续N天0推荐时自动放宽条件
4. 自动恢复：有推荐后逐步恢复原参数
5. 健康度报告：系统运行状态总览

降级等级：
- Level 0：正常（严格条件）
- Level 1：连续3天0推荐 → MACD取消15min要求，得分降到40
- Level 2：连续5天0推荐 → 振幅放宽到55%，超跌要求降到20%
- Level 3：连续7天0推荐 → 全市场扫描（取消优质池限制）
- 恢复：有推荐后3天，逐步降回上一级
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEALTH_FILE = os.path.join(BASE_DIR, "data", "system_health.json")

# 降级阈值
DEGRADATION_THRESHOLDS = {
    1: 3,   # Level 1：连续3天0推荐
    2: 5,   # Level 2：连续5天0推荐
    3: 7,   # Level 3：连续7天0推荐
}

# 恢复阈值
RECOVERY_DAYS = 3  # 有推荐后3天逐步恢复


class HealthMonitor:
    """系统健康度监控器。"""

    def __init__(self):
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        try:
            if os.path.exists(HEALTH_FILE):
                with open(HEALTH_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "daily_recommendations": {},   # {date: count}
            "consecutive_zero_days": 0,
            "degradation_level": 0,
            "last_recommendation_date": None,
            "degradation_history": [],
            "recovery_history": [],
            "updated_at": None,
        }

    def _save_state(self):
        os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
        self.state["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(HEALTH_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def record_recommendations(self, count: int, date: str = None):
        """记录某天的推荐数量。"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        self.state["daily_recommendations"][date] = count

        if count > 0:
            self.state["last_recommendation_date"] = date
            # 有推荐，检查是否需要恢复
            self._check_recovery()
        else:
            # 0推荐，增加连续天数
            if date not in self.state["daily_recommendations"] or self.state["daily_recommendations"][date] == 0:
                self.state["consecutive_zero_days"] += 1
                self._check_degradation()

        self._save_state()

    def _check_degradation(self):
        """检查是否需要降级。"""
        zero_days = self.state["consecutive_zero_days"]
        current_level = self.state["degradation_level"]

        # 计算应该降级到哪一级
        target_level = 0
        for level, threshold in sorted(DEGRADATION_THRESHOLDS.items()):
            if zero_days >= threshold:
                target_level = level

        if target_level > current_level:
            old_level = current_level
            self.state["degradation_level"] = target_level
            self.state["degradation_history"].append({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "from_level": old_level,
                "to_level": target_level,
                "reason": f"连续{zero_days}天0推荐",
            })
            print(f"⚠️ 系统降级：Level {old_level} → Level {target_level}（连续{zero_days}天0推荐）")

    def _check_recovery(self):
        """检查是否需要恢复。"""
        last_rec_date = self.state.get("last_recommendation_date")
        if not last_rec_date:
            return

        # 计算自上次推荐以来的天数
        try:
            last_date = datetime.strptime(last_rec_date, "%Y-%m-%d")
            days_since = (datetime.now() - last_date).days
        except Exception:
            days_since = 0

        # 如果有推荐且连续0天被重置
        if self.state["consecutive_zero_days"] > 0:
            self.state["consecutive_zero_days"] = 0

        # 有推荐后，逐步恢复
        current_level = self.state["degradation_level"]
        if current_level > 0 and days_since == 0:
            # 刚有推荐，降一级
            old_level = current_level
            self.state["degradation_level"] = current_level - 1
            self.state["recovery_history"].append({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "from_level": old_level,
                "to_level": current_level - 1,
                "reason": "出现推荐，逐步恢复",
            })
            print(f"✅ 系统恢复：Level {old_level} → Level {current_level - 1}（出现推荐）")

    def get_current_params_override(self) -> Dict[str, Any]:
        """获取当前降级等级对应的参数覆盖。"""
        level = self.state["degradation_level"]
        overrides = {
            "level": level,
            "macd": {},
            "oversold": {},
            "general": {},
        }

        if level >= 1:
            overrides["macd"]["min_score"] = 40
            overrides["macd"]["require_tf15_cross_zero"] = False
            overrides["general"]["note"] = "Level1：MACD取消15min要求，得分降到40"

        if level >= 2:
            overrides["macd"]["amplitude_20d_max"] = 55
            overrides["oversold"]["drop_20d_min"] = 20
            overrides["oversold"]["today_gain_min"] = 3
            overrides["general"]["note"] = "Level2：振幅放宽到55%，超跌要求降到20%"

        if level >= 3:
            overrides["general"]["use_full_market"] = True
            overrides["general"]["note"] = "Level3：全市场扫描（取消优质池限制）"

        return overrides

    def get_health_report(self) -> str:
        """生成健康度报告。"""
        lines = [
            "💓 系统健康度报告",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        # 降级状态
        level = self.state["degradation_level"]
        zero_days = self.state["consecutive_zero_days"]
        level_names = {0: "正常", 1: "轻度降级", 2: "中度降级", 3: "重度降级"}
        level_colors = {0: "🟢", 1: "🟡", 2: "🟠", 3: "🔴"}
        lines.append(f"{level_colors.get(level, '⚪')} 当前状态：{level_names.get(level, '未知')}（Level {level}）")
        lines.append(f"📅 连续0推荐：{zero_days}天")

        # 最近7天推荐情况
        lines.append("\n📊 最近7天推荐：")
        today = datetime.now()
        for i in range(6, -1, -1):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            count = self.state["daily_recommendations"].get(date, 0)
            weekday = ["一", "二", "三", "四", "五", "六", "日"][(today - timedelta(days=i)).weekday()]
            marker = "✅" if count > 0 else "❌"
            lines.append(f"  {date}(周{weekday})：{marker} {count}只推荐")

        # 参数覆盖
        overrides = self.get_current_params_override()
        if level > 0:
            lines.append(f"\n⚙️ 当前降级参数：{overrides['general'].get('note', '无')}")

        # 最近降级/恢复记录
        recent_degradations = self.state["degradation_history"][-3:]
        if recent_degradations:
            lines.append("\n📉 最近降级记录：")
            for d in recent_degradations:
                lines.append(f"  {d['date']}：Level {d['from_level']}→{d['to_level']}（{d['reason']}）")

        recent_recoveries = self.state["recovery_history"][-3:]
        if recent_recoveries:
            lines.append("\n📈 最近恢复记录：")
            for r in recent_recoveries:
                lines.append(f"  {r['date']}：Level {r['from_level']}→{r['to_level']}（{r['reason']}）")

        return "\n".join(lines)

    def should_use_full_market(self) -> bool:
        """是否应该使用全市场扫描（Level 3）。"""
        return self.state["degradation_level"] >= 3


def init_health_monitor() -> HealthMonitor:
    """初始化健康度监控器。"""
    return HealthMonitor()
