# -*- coding: utf-8 -*-
"""选股结果绩效跟踪模块。

记录每次推荐的股票，自动跟踪后续3/5/10/20日表现，
为策略优化和自适应参数提供数据基础。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import data_source as ds
from .trading_calendar import now_bjt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRACKING_FILE = os.path.join(BASE_DIR, "data", "tracking.jsonl")
PERFORMANCE_FILE = os.path.join(BASE_DIR, "data", "performance_summary.json")


def _load_records() -> List[Dict]:
    """加载所有跟踪记录。"""
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


def _save_records(records: List[Dict]):
    """保存所有跟踪记录（全量覆盖，用于更新）。"""
    os.makedirs(os.path.dirname(TRACKING_FILE), exist_ok=True)
    with open(TRACKING_FILE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _append_record(record: Dict):
    """追加一条新记录。"""
    os.makedirs(os.path.dirname(TRACKING_FILE), exist_ok=True)
    with open(TRACKING_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def record_recommendations(entries: List[Dict], strategy_type: str, scan_time: str):
    """记录一次扫描的推荐股票。

    Args:
        entries: 推荐股票列表，每项需含 code/name/price
        strategy_type: 策略类型 resonance / oversold
        scan_time: 扫描时间字符串
    """
    if not entries:
        return 0

    existing = _load_records()
    existing_codes = {(r["code"], r["recommend_time"][:10]) for r in existing}

    new_count = 0
    for e in entries:
        code = str(e.get("code", ""))
        name = str(e.get("name", ""))
        price = float(e.get("price", 0) or 0)
        if not code or price <= 0:
            continue
        # 同一天同一只股票不重复记录
        date_key = scan_time[:10]
        if (code, date_key) in existing_codes:
            continue

        record = {
            "code": code,
            "name": name,
            "strategy": strategy_type,
            "recommend_price": price,
            "recommend_time": scan_time,
            "recommend_date": date_key,
            "score": e.get("score", 0),
            "reason": e.get("reason", ""),
            "status": "tracking",
            "track_days": 0,
            "current_price": price,
            "current_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "day1_close": None,
            "day1_return_pct": None,
            "day3_close": None,
            "day3_return_pct": None,
            "day5_close": None,
            "day5_return_pct": None,
            "day10_close": None,
            "day10_return_pct": None,
            "day20_close": None,
            "day20_return_pct": None,
            "price_history": [],  # 每日收盘价记录
            "updated_at": scan_time,
        }
        _append_record(record)
        new_count += 1

    print(f"[跟踪] 新记录 {new_count} 只推荐股（策略={strategy_type}）")
    return new_count


def _is_trading_day(date: datetime) -> bool:
    """简单判断是否为交易日（周一到周五，节假日后续优化）。"""
    return date.weekday() < 5


def _get_trading_days(start_date: str, count: int) -> List[str]:
    """获取从start_date开始的count个交易日日期列表。"""
    days = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    while len(days) < count:
        current += timedelta(days=1)
        if _is_trading_day(current):
            days.append(current.strftime("%Y-%m-%d"))
    return days


def update_performance() -> Dict:
    """更新所有跟踪中股票的表现。

    Returns:
        更新统计：{updated, completed, tracking}
    """
    records = _load_records()
    now = now_bjt()
    today_str = now.strftime("%Y-%m-%d")

    updated = 0
    completed = 0
    still_tracking = 0

    for r in records:
        if r.get("status") == "completed":
            continue

        code = r["code"]
        recommend_date = r["recommend_date"]
        recommend_price = r["recommend_price"]

        # 获取从推荐日到今天的日K线
        try:
            df = ds.get_kline_daily(code, count=30)
            if df.empty:
                continue
        except Exception as e:
            print(f"[跟踪] {code} 获取K线失败: {e}")
            continue

        # 构建日期->收盘价映射
        df["date_str"] = df["date"].astype(str).str[:10]
        price_map = dict(zip(df["date_str"], df["close"].astype(float)))
        high_map = dict(zip(df["date_str"], df["high"].astype(float)))
        low_map = dict(zip(df["date_str"], df["low"].astype(float)))

        # 获取交易日序列
        trading_days = _get_trading_days(recommend_date, 21)

        # 更新各周期收益
        price_history = r.get("price_history", [])
        max_price = recommend_price
        min_price_after = recommend_price

        for i, day in enumerate(trading_days, 1):
            if day not in price_map:
                break
            close = price_map[day]
            high = high_map.get(day, close)
            low = low_map.get(day, close)

            # 记录价格历史
            if not any(p.get("date") == day for p in price_history):
                price_history.append({"date": day, "close": close, "high": high, "low": low})

            # 计算最大回撤（从推荐后的最高点到后续最低点）
            if high > max_price:
                max_price = high
            drawdown = (max_price - low) / max_price * 100 if max_price > 0 else 0
            if drawdown > r.get("max_drawdown_pct", 0):
                r["max_drawdown_pct"] = round(drawdown, 2)

            # 更新各周期收盘价和收益率
            ret = round((close - recommend_price) / recommend_price * 100, 2)
            if i == 1:
                r["day1_close"] = close
                r["day1_return_pct"] = ret
            elif i == 3:
                r["day3_close"] = close
                r["day3_return_pct"] = ret
            elif i == 5:
                r["day5_close"] = close
                r["day5_return_pct"] = ret
            elif i == 10:
                r["day10_close"] = close
                r["day10_return_pct"] = ret
            elif i == 20:
                r["day20_close"] = close
                r["day20_return_pct"] = ret
                r["status"] = "completed"
                completed += 1
                break

            r["track_days"] = i

        # 更新当前价格和收益
        latest_date = trading_days[min(len(trading_days) - 1, len(price_history) - 1)] if price_history else None
        if latest_date and latest_date in price_map:
            current_price = price_map[latest_date]
            r["current_price"] = current_price
            r["current_return_pct"] = round((current_price - recommend_price) / recommend_price * 100, 2)

        r["price_history"] = price_history[-25:]  # 只保留最近25条
        r["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

        if r["status"] == "tracking":
            still_tracking += 1
        updated += 1

    _save_records(records)

    stats = {"updated": updated, "completed": completed, "tracking": still_tracking, "total": len(records)}
    print(f"[跟踪] 更新完成：总计{stats['total']}只，更新{updated}只，已完成{completed}只，跟踪中{still_tracking}只")
    return stats


def get_performance_summary() -> Dict:
    """生成策略绩效汇总。"""
    records = _load_records()
    if not records:
        return {"total": 0, "message": "暂无跟踪数据"}

    def calc_stats(records_subset: List[Dict], day_key: str) -> Dict:
        """计算某周期的统计指标。"""
        valid = [r for r in records_subset if r.get(day_key) is not None]
        if not valid:
            return {"count": 0, "win_rate": 0, "avg_return": 0, "max_return": 0, "min_return": 0}
        returns = [r[day_key] for r in valid]
        wins = [r for r in returns if r > 0]
        return {
            "count": len(valid),
            "win_rate": round(len(wins) / len(valid) * 100, 1),
            "avg_return": round(sum(returns) / len(valid), 2),
            "max_return": round(max(returns), 2),
            "min_return": round(min(returns), 2),
            "avg_max_drawdown": round(sum(r.get("max_drawdown_pct", 0) for r in valid) / len(valid), 2),
        }

    summary = {
        "total": len(records),
        "tracking": len([r for r in records if r["status"] == "tracking"]),
        "completed": len([r for r in records if r["status"] == "completed"]),
        "by_strategy": {},
    }

    for strategy in ["resonance", "oversold"]:
        subset = [r for r in records if r.get("strategy") == strategy]
        if not subset:
            continue
        strategy_stats = {
            "total": len(subset),
            "tracking": len([r for r in subset if r["status"] == "tracking"]),
            "completed": len([r for r in subset if r["status"] == "completed"]),
            "day1": calc_stats(subset, "day1_return_pct"),
            "day3": calc_stats(subset, "day3_return_pct"),
            "day5": calc_stats(subset, "day5_return_pct"),
            "day10": calc_stats(subset, "day10_return_pct"),
            "day20": calc_stats(subset, "day20_return_pct"),
        }
        summary["by_strategy"][strategy] = strategy_stats

    # 总体
    summary["overall"] = {
        "day1": calc_stats(records, "day1_return_pct"),
        "day3": calc_stats(records, "day3_return_pct"),
        "day5": calc_stats(records, "day5_return_pct"),
        "day10": calc_stats(records, "day10_return_pct"),
        "day20": calc_stats(records, "day20_return_pct"),
    }

    # 保存汇总
    os.makedirs(os.path.dirname(PERFORMANCE_FILE), exist_ok=True)
    with open(PERFORMANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


def build_performance_message(summary: Dict) -> str:
    """生成绩效报告飞书消息。"""
    now = now_bjt().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"📊 策略绩效跟踪报告 {now}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 总跟踪：{summary.get('total', 0)}只 | 跟踪中：{summary.get('tracking', 0)}只 | 已完成：{summary.get('completed', 0)}只",
        "",
    ]

    strategy_names = {"resonance": "MACD多周期共振", "oversold": "超跌反弹"}
    for strategy, name in strategy_names.items():
        stats = summary.get("by_strategy", {}).get(strategy)
        if not stats:
            continue
        lines.append(f"【{name}】")
        lines.append(f"  样本：{stats['total']}只（完成{stats['completed']}只）")
        for period, label in [("day1", "1日"), ("day3", "3日"), ("day5", "5日"), ("day10", "10日"), ("day20", "20日")]:
            s = stats.get(period, {})
            if s.get("count", 0) > 0:
                win_emoji = "🟢" if s["win_rate"] >= 50 else "🔴"
                lines.append(
                    f"  {label}：样本{s['count']}只 | 胜率{win_emoji}{s['win_rate']}% | "
                    f"平均收益{s['avg_return']}% | 最大{s['max_return']}% | 最小{s['min_return']}%"
                )
        lines.append("")

    # 总体
    overall = summary.get("overall", {})
    if overall:
        lines.append("【总体表现】")
        for period, label in [("day5", "5日"), ("day10", "10日"), ("day20", "20日")]:
            s = overall.get(period, {})
            if s.get("count", 0) > 0:
                lines.append(
                    f"  {label}：胜率{s['win_rate']}% | 平均收益{s['avg_return']}% | "
                    f"平均最大回撤{s.get('avg_max_drawdown', 0)}%"
                )
        lines.append("")

    lines.append("⚠️ 数据基于策略历史推荐自动跟踪，样本较少时仅供参考")
    lines.append(f"⏱ 生成时间：北京时间{now}")
    return "\n".join(lines)
