# -*- coding: utf-8 -*-
"""每周策略绩效报告脚本。

每周日运行，生成本周策略绩效总结，推送到飞书。
包含：本周推荐统计、胜率、平均收益、最佳/最差个股、策略对比。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.tracking import _load_records, get_performance_summary, build_performance_message  # noqa: E402
from strategies.macd_resonance.trading_calendar import now_bjt  # noqa: E402


def send_feishu(text: str):
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL")
        return
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
        print(f"✅ 飞书推送完成 HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


def build_weekly_report() -> str:
    """生成每周绩效报告。"""
    now = now_bjt()
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")

    records = _load_records()
    summary = get_performance_summary()

    # 本周推荐
    week_records = [r for r in records if r.get("recommend_date", "") >= week_start]

    lines = [
        f"📊 策略周绩效报告 ({week_start} ~ {week_end})",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 本周推荐：{len(week_records)}只",
        f"📊 累计跟踪：{summary.get('total', 0)}只 | 已完成：{summary.get('completed', 0)}只",
        "",
    ]

    # 按策略统计本周
    strategy_names = {"resonance": "MACD多周期共振", "oversold": "超跌反弹"}
    for strategy, name in strategy_names.items():
        week_subset = [r for r in week_records if r.get("strategy") == strategy]
        if not week_subset:
            continue
        lines.append(f"【{name}】本周推荐{len(week_subset)}只")
        # 列出推荐股
        for r in week_subset[:5]:
            ret = r.get("current_return_pct", 0)
            ret_str = f"+{ret}%" if ret >= 0 else f"{ret}%"
            ret_color = "🟢" if ret >= 0 else "🔴"
            lines.append(f"  {r['name']}({r['code']}) 推荐价{r['recommend_price']}元 | 当前{ret_color}{ret_str}")
        if len(week_subset) > 5:
            lines.append(f"  ...等{len(week_subset)}只")
        lines.append("")

    # 总体绩效
    overall = summary.get("overall", {})
    if overall:
        lines.append("【累计绩效】")
        for period, label in [("day1", "1日"), ("day3", "3日"), ("day5", "5日"), ("day10", "10日"), ("day20", "20日")]:
            s = overall.get(period, {})
            if s.get("count", 0) > 0:
                win_color = "🟢" if s["win_rate"] >= 50 else "🔴"
                lines.append(
                    f"  {label}：样本{s['count']}只 | 胜率{win_color}{s['win_rate']}% | "
                    f"平均收益{s['avg_return']}% | 最大回撤{s.get('avg_max_drawdown', 0)}%"
                )
        lines.append("")

    # 最佳/最差
    completed = [r for r in records if r.get("status") == "completed" and r.get("day5_return_pct") is not None]
    if completed:
        best = max(completed, key=lambda x: x.get("day5_return_pct", -999))
        worst = min(completed, key=lambda x: x.get("day5_return_pct", 999))
        lines.append("【历史最佳/最差（5日收益）】")
        lines.append(f"  🏆 最佳：{best['name']}({best['code']}) +{best['day5_return_pct']}%")
        lines.append(f"  💩 最差：{worst['name']}({worst['code']}) {worst['day5_return_pct']}%")
        lines.append("")

    lines.append("⚠️ 样本较少时仅供参考，持续积累数据中")
    lines.append(f"⏱ 生成时间：北京时间{now.strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def main():
    print("=" * 50)
    print("📊 生成每周策略绩效报告...")
    print("=" * 50)

    msg = build_weekly_report()
    print("\n" + msg)

    # 推送飞书
    if os.environ.get("PUSH_FEISHU", "true").lower() == "true":
        send_feishu(msg)


if __name__ == "__main__":
    main()
