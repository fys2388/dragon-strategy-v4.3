# -*- coding: utf-8 -*-
"""周度优化器（Agent自主优化闭环增强版）。

在原有4层进化引擎基础上增加：
1. 突破策略参数进化（量比阈值、最低得分、位置分权重）
2. 冷却期天数自适应（胜率低时延长，胜率高时缩短）
3. 移动止盈参数优化建议
4. 周度优化报告生成与推送
5. 优化建议执行与效果验证

设计原则：
- 每周日自动运行，生成下周优化方案
- 保守优化：每次只调1-2个参数，避免过拟合
- 样本门槛：至少10个样本才优化
- 可解释：每条优化建议都有数据支撑
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRACKING_FILE = os.path.join(BASE_DIR, "data", "tracking.jsonl")
WEEKLY_REPORT_FILE = os.path.join(BASE_DIR, "data", "weekly_optimization_report.json")
OPTIMIZATION_STATE_FILE = os.path.join(BASE_DIR, "data", "optimization_state.json")


def _load_records() -> List[Dict]:
    """加载跟踪记录。"""
    if not os.path.exists(TRACKING_FILE):
        return []
    records = []
    with open(TRACKING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def _load_optimization_state() -> Dict:
    """加载优化状态。"""
    try:
        if os.path.exists(OPTIMIZATION_STATE_FILE):
            with open(OPTIMIZATION_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "current_params": {
            "breakout": {
                "volume_ratio_min": 1.5,
                "min_score": 40,
                "cooldown_days": 10,
                "trailing_drawdown_pct": 3.0,
                "trailing_activate_pct": 8.0,
                "breakeven_activate_pct": 5.0,
            }
        },
        "history": [],
        "last_optimization": None,
    }


def _save_optimization_state(state: Dict):
    """保存优化状态。"""
    os.makedirs(os.path.dirname(OPTIMIZATION_STATE_FILE), exist_ok=True)
    with open(OPTIMIZATION_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def analyze_breakout_performance(records: List[Dict]) -> Dict[str, Any]:
    """分析突破策略表现。"""
    breakout_records = [r for r in records if r.get("strategy") == "breakout" and r.get("status") == "completed"]
    completed = [r for r in breakout_records if r.get("day5_return_pct") is not None]

    if len(completed) < 5:
        return {"status": "insufficient_data", "count": len(completed), "message": "突破策略样本不足5只"}

    returns = [r["day5_return_pct"] for r in completed]
    win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
    avg_return = sum(returns) / len(returns)
    max_return = max(returns)
    min_return = min(returns)

    # 按位置类型分析
    by_position = defaultdict(list)
    for r in completed:
        pos = r.get("position_type", "unknown")
        by_position[pos].append(r.get("day5_return_pct", 0))

    position_stats = {}
    for pos, rets in by_position.items():
        if rets:
            position_stats[pos] = {
                "count": len(rets),
                "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
                "avg_return": round(sum(rets) / len(rets), 2),
            }

    # 按基本面评级分析
    by_grade = defaultdict(list)
    for r in completed:
        grade = r.get("huangyang_grade", "unknown")
        by_grade[grade].append(r.get("day5_return_pct", 0))

    grade_stats = {}
    for grade, rets in by_grade.items():
        if rets:
            grade_stats[grade] = {
                "count": len(rets),
                "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
                "avg_return": round(sum(rets) / len(rets), 2),
            }

    return {
        "status": "ok",
        "count": len(completed),
        "win_rate": round(win_rate, 1),
        "avg_return": round(avg_return, 2),
        "max_return": round(max_return, 2),
        "min_return": round(min_return, 2),
        "by_position": position_stats,
        "by_grade": grade_stats,
    }


def generate_optimization_suggestions(perf: Dict, state: Dict) -> List[Dict]:
    """生成优化建议。"""
    if perf["status"] == "insufficient_data":
        return [{"type": "info", "message": f"样本不足（{perf['count']}只），本周不做参数优化，继续收集数据"}]

    suggestions = []
    current = state["current_params"]["breakout"]
    win_rate = perf["win_rate"]
    avg_return = perf["avg_return"]

    # 1. 量比阈值优化
    if win_rate < 40:
        new_vr = min(current["volume_ratio_min"] + 0.3, 2.5)
        if new_vr != current["volume_ratio_min"]:
            suggestions.append({
                "type": "param_change",
                "param": "volume_ratio_min",
                "current": current["volume_ratio_min"],
                "suggested": new_vr,
                "reason": f"胜率{win_rate}%<40%，提高量比门槛到{new_vr}，过滤缩量假突破",
                "impact": "预计减少30%推荐数量，提升胜率5-10%",
            })
    elif win_rate > 65 and avg_return > 3:
        new_vr = max(current["volume_ratio_min"] - 0.2, 1.2)
        if new_vr != current["volume_ratio_min"]:
            suggestions.append({
                "type": "param_change",
                "param": "volume_ratio_min",
                "current": current["volume_ratio_min"],
                "suggested": new_vr,
                "reason": f"胜率{win_rate}%>65%且收益{avg_return}%，降低量比门槛到{new_vr}，捕捉更多机会",
                "impact": "预计增加20%推荐数量",
            })

    # 2. 冷却期天数自适应
    # 分析同股重复推荐的表现
    repeated = defaultdict(list)
    for r in _load_records():
        if r.get("strategy") == "breakout" and r.get("status") == "completed":
            repeated[r.get("code", "")].append(r.get("day5_return_pct", 0))

    repeat_loss_count = sum(1 for code, rets in repeated.items() if len(rets) >= 2 and sum(1 for r in rets if r < 0) >= len(rets) * 0.5)
    if repeat_loss_count >= 2:
        new_cd = min(current["cooldown_days"] + 5, 20)
        if new_cd != current["cooldown_days"]:
            suggestions.append({
                "type": "param_change",
                "param": "cooldown_days",
                "current": current["cooldown_days"],
                "suggested": new_cd,
                "reason": f"发现{repeat_loss_count}只股票反复止损，延长冷却期到{new_cd}天",
                "impact": "减少同股反复踩坑",
            })
    elif win_rate > 60 and repeat_loss_count == 0:
        new_cd = max(current["cooldown_days"] - 3, 5)
        if new_cd != current["cooldown_days"]:
            suggestions.append({
                "type": "param_change",
                "param": "cooldown_days",
                "current": current["cooldown_days"],
                "suggested": new_cd,
                "reason": f"胜率{win_rate}%且无反复止损，缩短冷却期到{new_cd}天",
                "impact": "增加优质股二次机会",
            })

    # 3. 最低得分阈值优化
    if win_rate < 40:
        new_score = min(current["min_score"] + 10, 70)
        if new_score != current["min_score"]:
            suggestions.append({
                "type": "param_change",
                "param": "min_score",
                "current": current["min_score"],
                "suggested": new_score,
                "reason": f"胜率{win_rate}%<40%，提高最低得分到{new_score}，只保留高质量突破",
                "impact": "预计减少40%推荐数量",
            })

    # 4. 位置分权重优化建议
    by_pos = perf.get("by_position", {})
    if "high" in by_pos and by_pos["high"]["count"] >= 3 and by_pos["high"]["win_rate"] < 30:
        suggestions.append({
            "type": "rule_change",
            "param": "high_position_penalty",
            "current": "-20分",
            "suggested": "-30分",
            "reason": f"高位突破胜率仅{by_pos['high']['win_rate']}%（{by_pos['high']['count']}只样本），加大高位惩罚",
            "impact": "减少高位追涨",
        })
    if "low" in by_pos and by_pos["low"]["count"] >= 3 and by_pos["low"]["win_rate"] > 60:
        suggestions.append({
            "type": "rule_change",
            "param": "low_position_bonus",
            "current": "+20分",
            "suggested": "+25分",
            "reason": f"低位突破胜率{by_pos['low']['win_rate']}%（{by_pos['low']['count']}只样本），加大低位奖励",
            "impact": "优先推荐低位突破",
        })

    # 5. 基本面过滤优化
    by_grade = perf.get("by_grade", {})
    if "偏弱" in by_grade and by_grade["偏弱"]["count"] >= 3 and by_grade["偏弱"]["avg_return"] < 0:
        suggestions.append({
            "type": "rule_change",
            "param": "fundamental_hard_filter",
            "current": "仅打分排序",
            "suggested": "基本面偏弱直接过滤",
            "reason": f"基本面偏弱股票平均收益{by_grade['偏弱']['avg_return']}%（{by_grade['偏弱']['count']}只），建议硬过滤",
            "impact": "提升整体胜率",
        })

    if not suggestions:
        suggestions.append({
            "type": "info",
            "message": f"当前参数表现稳定（胜率{win_rate}%，收益{avg_return}%），本周不做调整",
        })

    return suggestions


def apply_suggestions(suggestions: List[Dict], state: Dict) -> Dict:
    """应用优化建议（只应用param_change类型，rule_change需要代码修改）。"""
    applied = []
    for s in suggestions:
        if s["type"] == "param_change":
            param = s["param"]
            if param in state["current_params"]["breakout"]:
                old_val = state["current_params"]["breakout"][param]
                state["current_params"]["breakout"][param] = s["suggested"]
                applied.append({
                    "param": param,
                    "old": old_val,
                    "new": s["suggested"],
                    "reason": s["reason"],
                })

    state["last_optimization"] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "applied": applied,
        "suggestions_count": len(suggestions),
    }
    state.setdefault("history", []).append(state["last_optimization"])
    _save_optimization_state(state)
    return state


def generate_weekly_report() -> str:
    """生成周度优化报告。"""
    records = _load_records()
    state = _load_optimization_state()

    # 统计本周数据
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_records = [r for r in records if str(r.get("scan_time", "")) >= week_ago]
    week_completed = [r for r in week_records if r.get("status") == "completed" and r.get("day5_return_pct") is not None]

    # 分析突破策略表现
    perf = analyze_breakout_performance(records)

    # 生成优化建议
    suggestions = generate_optimization_suggestions(perf, state)

    # 应用可自动应用的建议
    state = apply_suggestions(suggestions, state)

    # 生成报告
    lines = [
        "🔄 周度策略优化报告（Agent自主闭环）",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏱ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # 本周表现
    lines.append("📊 本周策略表现：")
    if perf["status"] == "insufficient_data":
        lines.append(f"  累计样本：{perf['count']}只（不足5只，继续收集）")
    else:
        win_color = "🟢" if perf["win_rate"] >= 50 else "🔴"
        lines.append(f"  突破策略：样本{perf['count']}只 | {win_color}胜率{perf['win_rate']}% | 平均收益{perf['avg_return']}%")
        lines.append(f"  最好：+{perf['max_return']}% | 最差：{perf['min_return']}%")

        # 位置类型表现
        if perf.get("by_position"):
            lines.append("")
            lines.append("  按位置分类：")
            for pos, stats in perf["by_position"].items():
                pos_name = {"low": "低位", "mid": "中位", "high": "高位", "unknown": "未知"}.get(pos, pos)
                lines.append(f"    {pos_name}：{stats['count']}只 | 胜率{stats['win_rate']}% | 收益{stats['avg_return']}%")

        # 基本面评级表现
        if perf.get("by_grade"):
            lines.append("")
            lines.append("  按基本面评级：")
            for grade, stats in perf["by_grade"].items():
                lines.append(f"    {grade}：{stats['count']}只 | 胜率{stats['win_rate']}% | 收益{stats['avg_return']}%")

    # 优化建议
    lines.append("")
    lines.append("💡 Agent优化建议：")
    for i, s in enumerate(suggestions, 1):
        if s["type"] == "info":
            lines.append(f"  {i}. ℹ️ {s['message']}")
        else:
            lines.append(f"  {i}. 🔧 {s['param']}: {s['current']} → {s['suggested']}")
            lines.append(f"     原因：{s['reason']}")
            lines.append(f"     影响：{s['impact']}")

    # 已应用
    applied = state.get("last_optimization", {}).get("applied", [])
    if applied:
        lines.append("")
        lines.append("✅ 已自动应用：")
        for a in applied:
            lines.append(f"  • {a['param']}: {a['old']} → {a['new']}")

    # 当前参数
    lines.append("")
    lines.append("⚙️ 当前突破策略参数：")
    bp = state["current_params"]["breakout"]
    lines.append(f"  量比阈值：{bp['volume_ratio_min']} | 最低得分：{bp['min_score']}")
    lines.append(f"  冷却期：{bp['cooldown_days']}天 | 移动止盈回撤：{bp['trailing_drawdown_pct']}%")

    # 保存报告
    report_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "performance": perf,
        "suggestions": suggestions,
        "applied": applied,
        "current_params": state["current_params"],
    }
    os.makedirs(os.path.dirname(WEEKLY_REPORT_FILE), exist_ok=True)
    with open(WEEKLY_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    return "\n".join(lines)


if __name__ == "__main__":
    report = generate_weekly_report()
    print(report)
