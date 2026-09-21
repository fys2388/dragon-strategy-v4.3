# -*- coding: utf-8 -*-
"""系统健康度监控与自动降级机制。

核心能力：
1. 记录每天的推荐数量和质量
2. 监控连续0推荐天数
3. 自动降级：连续N天0推荐时自动放宽条件
4. 自动恢复：有推荐后逐步恢复原参数
5. 健康度报告：系统运行状态总览

降级等级（覆盖值与 scanner/oversold/breakout 实际读取的键一一对应）：
- Level 0：正常（严格条件）
- Level 1：连续3天0推荐 → 共振评分门槛降到1.5、突破取消最低得分，各多推几只
- Level 2：连续5天0推荐 → 振幅放宽到55%，超跌20日跌幅要求降到20%，突破量比降到1.2
- Level 3：连续7天0推荐 → 全市场扫描（取消优质股票池限制）+ 突破最多推8只
- 恢复：出现推荐当天降一级
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from .trading_calendar import now_bjt

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
        self.state["updated_at"] = now_bjt().strftime("%Y-%m-%d %H:%M:%S")
        with open(HEALTH_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def record_recommendations(self, count: int, date: str = None):
        """记录某天的推荐数量。

        同一天可被多次调用（盘中每 30 分钟一档，共约 10 档）；
        最后一次调用代表当天真实推荐数，连续0推荐天数按「已记录日期」幂等推导。
        """
        if date is None:
            # 缺省按北京时间取日期（GitHub Actions 上 datetime.now() 是 UTC，会把一个交易日拆成两天）
            date = now_bjt().strftime("%Y-%m-%d")

        self.state["daily_recommendations"][date] = count
        self._recompute_zero_days()

        if count > 0:
            self.state["last_recommendation_date"] = date
            # 有推荐，检查是否需要恢复
            self._check_recovery(date)
        else:
            self._check_degradation()

        self._save_state()

    def _recompute_zero_days(self):
        """从 daily_recommendations 推导「连续0推荐」天数（幂等）。

        修复：原实现在此处对 consecutive_zero_days 做 `+= 1` 累加，
        且判重条件写成 `date not in daily_recommendations`——而该字典在函数开头
        就已被赋值，条件永远为假、同一天重复 record 又会重复累加，
        使连续0推荐天数被放大、降级被提前触发。
        现在直接从已记录的每日推荐数倒序推导，同一份状态重放多少次结果都一样。
        """
        recent = sorted(self.state.get("daily_recommendations", {}).items())
        streak = 0
        for _date, cnt in reversed(recent):
            if cnt and cnt > 0:
                break
            streak += 1
        self.state["consecutive_zero_days"] = streak

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
                "date": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
                "from_level": old_level,
                "to_level": target_level,
                "reason": f"连续{zero_days}天0推荐",
            })
            print(f"⚠️ 系统降级：Level {old_level} → Level {target_level}（连续{zero_days}天0推荐）")

    def _check_recovery(self, record_date: str):
        """检查是否需要恢复（本次记录出现推荐即降一级）。

        修复：原实现用 ``datetime.now() - last_recommendation_date`` 算天数，
        而 health 状态是跨进程持久化的（GitHub Actions 每次全新 checkout、
        上一档可能是几天前甚至上周写的）。只要距上次「有推荐」的记录超过当天，
        本次推荐就永远进不了 ``days_since == 0`` 分支 —— 降级只上不下。
        现在按「本次记录日期」与「上次有推荐日期」相减，去掉墙钟依赖。
        """
        last_rec_date = self.state.get("last_recommendation_date")
        if not last_rec_date:
            return

        try:
            last_date = datetime.strptime(str(last_rec_date)[:10], "%Y-%m-%d").date()
            rec_date = datetime.strptime(str(record_date)[:10], "%Y-%m-%d").date()
            days_since = max((rec_date - last_date).days, 0)
        except Exception:
            return

        # 有推荐了，连续0推荐计数清零
        if self.state["consecutive_zero_days"] > 0:
            self.state["consecutive_zero_days"] = 0

        current_level = self.state["degradation_level"]
        if current_level > 0 and days_since <= RECOVERY_DAYS:
            old_level = current_level
            self.state["degradation_level"] = current_level - 1
            self.state["recovery_history"].append({
                "date": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
                "from_level": old_level,
                "to_level": current_level - 1,
                "reason": f"{record_date} 出现推荐（距上次推荐{days_since}天）",
            })
            print(f"✅ 系统恢复：Level {old_level} → Level {current_level - 1}（{record_date} 出现推荐）")

    def get_current_params_override(self) -> Dict[str, Any]:
        """获取当前降级等级对应的参数覆盖。

        返回结构的键**逐个对齐三个扫描器实际读取的参数**，可直接用
        :meth:`merge_override` 合并生效：

        - ``overrides["macd"]``      → scanner.py 的 ``adaptive_params``
          （``min_score`` 量纲 1.0~4.0，见 adaptive_config.MACD_PARAMS）
        - ``overrides["oversold"]``  → oversold_rebound.py 的 ``cfg``
        - ``overrides["breakout"]``  → breakout.py 的 run() 局部门槛
        - ``overrides["general"]["use_full_market"]``
          → 三个扫描器放弃优质股票池，退回全市场

        历史 bug：这里原先输出 ``require_tf15_cross_zero``、
        ``oversold.drop_20d_min`` 之类的键名，全仓没有任何消费方，
        ``v43_push.py`` 也只把它 print 出来——即所谓"假闭环"。
        """
        level = self.state["degradation_level"]
        overrides: Dict[str, Any] = {
            "level": level,
            "macd": {},
            "oversold": {},
            "breakout": {},
            "general": {},
        }

        if level >= 1:
            overrides["macd"]["min_score"] = 1.5
            overrides["macd"]["max_recommendations"] = 6
            overrides["breakout"]["min_score_override"] = 0
            overrides["breakout"]["max_recommend"] = 5
            overrides["general"]["note"] = (
                "Level1：共振评分门槛降到1.5、突破取消最低得分，共振/突破各多推几只"
            )

        if level >= 2:
            overrides["macd"]["amplitude_20d_max"] = 55
            overrides["oversold"]["drop_20d_min"] = 20
            overrides["oversold"]["today_gain_min"] = 3
            overrides["breakout"]["volume_ratio_min"] = 1.2
            overrides["general"]["note"] = (
                "Level2：振幅放宽到55%，超跌20日跌幅要求降到20%，突破量比降到1.2"
            )

        if level >= 3:
            overrides["general"]["use_full_market"] = True
            overrides["breakout"]["max_recommend"] = 8
            overrides["general"]["note"] = (
                "Level3：全市场扫描（取消优质股票池限制）+ 突破最多推8只"
            )

        return overrides

    @staticmethod
    def merge_override(params: Dict[str, Any], group: str,
                       overrides: Dict[str, Any]) -> Dict[str, Any]:
        """把降级覆盖合并到扫描参数上（不修改入参，返回新 dict）。

        Args:
            params: 原始参数（adaptive_config.get_*_params 的输出等）
            group: "macd" / "oversold" / "breakout"
            overrides: get_current_params_override() 的返回值

        设计成 staticmethod 是为了让扫描器和单测都能在
        不实例化 HealthMonitor、不读 data/system_health.json 的情况下调用。
        """
        merged = dict(params)
        extra = ((overrides or {}).get(group) or {})
        merged.update(extra)
        return merged

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
        today = now_bjt()
        for i in range(6, -1, -1):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            count = self.state["daily_recommendations"].get(date, 0)
            weekday = ["一", "二", "三", "四", "五", "六", "日"][(today - timedelta(days=i)).weekday()]
            marker = "✅" if count > 0 else "❌"
            lines.append(f"  {date}(周{weekday})：{marker} {count}只推荐")

        # 参数覆盖（会真实作用于三个扫描器，不只打印）
        overrides = self.get_current_params_override()
        if level > 0:
            lines.append(f"\n⚙️ 当前降级参数：{overrides['general'].get('note', '无')}")
            applied = []
            if overrides.get("macd"):
                applied.append("共振" + ", ".join(f"{k}={v}" for k, v in overrides["macd"].items()))
            if overrides.get("oversold"):
                applied.append("超跌" + ", ".join(f"{k}={v}" for k, v in overrides["oversold"].items()))
            if overrides.get("breakout"):
                applied.append("突破" + ", ".join(f"{k}={v}" for k, v in overrides["breakout"].items()))
            if overrides.get("general", {}).get("use_full_market"):
                applied.append("三个扫描器退回全市场")
            lines.append(f"   ↳ 生效范围：{'；'.join(applied) or '无'}（下一档扫描开始生效）")
        else:
            lines.append("\n⚙️ 当前无降级覆盖，三个扫描器使用 adaptive_config 默认参数")

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
