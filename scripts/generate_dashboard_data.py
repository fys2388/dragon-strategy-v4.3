# -*- coding: utf-8 -*-
"""策略看板数据生成脚本。

读取 data/strategy_history.jsonl（scanner 每次扫描追加），统计：
- 近7/30天：扫描次数、推荐次数、日均推荐
- 推荐表现：最新价 vs 推荐价 → 平均收益率 / 胜率 / 5日样本收益率
输出 data/dashboard_data.json，供复盘推送与人工查看。

用法：
    python scripts/generate_dashboard_data.py            # 同时生成 7/30 天
    python scripts/generate_dashboard_data.py --days 30  # 仅 30 天
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import data_source as ds  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "strategy_history.jsonl")
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "dashboard_data.json")


def _naive(dt: datetime) -> datetime:
    """去掉时区信息，统一与历史记录的 naive 时间戳比较。"""
    if dt is None:
        return dt
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def load_history() -> List[Dict]:
    """读取全部历史扫描记录。"""
    if not os.path.exists(HISTORY_FILE):
        return []
    records = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def entries_in_window(records: List[Dict], days: int, now: datetime) -> List[Dict]:
    """窗口内的推荐记录（按 code 去重，保留窗口内最早一次）。"""
    now = _naive(now)
    cutoff = now - timedelta(days=days)
    seen: Dict[str, Dict] = {}
    for rec in records:
        try:
            ts = datetime.strptime(rec.get("ts", ""), "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        for e in rec.get("entries", []):
            code = str(e.get("code", ""))
            if not code or code in seen:
                continue
            e = dict(e)
            e["ts"] = ts
            seen[code] = e
    return list(seen.values())


def compute_performance(entries: List[Dict], quotes: Dict[str, Dict]) -> Dict:
    """计算窗口内推荐的收益率/胜率（最新价 vs 推荐价）。"""
    if not entries:
        return {"count": 0, "avg_return_pct": 0.0, "win_rate_pct": 0.0,
                "pos_count": 0, "neg_count": 0, "no_price": 0, "returns": []}

    returns = []
    no_price = 0
    for e in entries:
        code = str(e.get("code", ""))
        entry_price = float(e.get("price") or 0)
        latest = float(quotes.get(code, {}).get("price") or 0)
        if entry_price <= 0:
            continue
        if latest <= 0:
            no_price += 1
            continue
        returns.append(round((latest - entry_price) / entry_price * 100, 2))

    if not returns:
        return {"count": len(entries), "avg_return_pct": 0.0, "win_rate_pct": 0.0,
                "pos_count": 0, "neg_count": 0, "no_price": no_price, "returns": []}
    pos = sum(1 for r in returns if r > 0)
    return {
        "count": len(entries),
        "avg_return_pct": round(sum(returns) / len(returns), 2),
        "win_rate_pct": round(pos / len(returns) * 100, 1),
        "pos_count": pos,
        "neg_count": len(returns) - pos,
        "no_price": no_price,
        "returns": returns,
    }


def build_dashboard(days: int, now: datetime, quotes: Dict[str, Dict]) -> Dict:
    """生成指定窗口的看板统计。"""
    records = load_history()
    entries = entries_in_window(records, days, now)
    perf = compute_performance(entries, quotes)
    scan_records = [r for r in records if _ts_within(r, days, now)]
    scans = len(scan_records)
    reso_counts = defaultdict(int)
    for r in scan_records:
        for e in r.get("entries", []):
            reso_counts["共振推荐"] += 1
    daily = round(len(entries) / max(days, 1), 2)
    return {
        "days": days,
        "scans": scans,
        "rec_count": len(entries),
        "daily_avg": daily,
        "perf": perf,
        "top_recommendations": sorted(entries, key=lambda e: float(e.get("score") or 0), reverse=True)[:10],
    }


def _ts_within(rec: Dict, days: int, now: datetime) -> bool:
    now = _naive(now)
    try:
        ts = datetime.strptime(rec.get("ts", ""), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return False
    return now - timedelta(days=days) <= ts <= now


def fmt_summary(d: Dict) -> str:
    perf = d["perf"]
    lines = [
        f"📊 近{d['days']}天策略表现",
        f"扫描{d['scans']}次 | 推荐{perf['count']}只（日均{d['daily_avg']}只）",
        f"平均收益率：{perf['avg_return_pct']:+.2f}% | 胜率：{perf['win_rate_pct']:.1f}%",
        f"盈利{perf['pos_count']}只 / 亏损{perf['neg_count']}只"
        + (f" / 无最新价{perf['no_price']}只" if perf["no_price"] else ""),
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="生成策略看板数据")
    parser.add_argument("--days", type=int, default=0, help="0=7与30天都生成")
    args = parser.parse_args()

    now = datetime.now()
    windows = [7, 30] if args.days == 0 else [args.days]

    # 一次性拉取窗口内全部推荐标的的最新价
    records = load_history()
    all_entries = []
    for w in windows:
        all_entries += entries_in_window(records, w, now)
    codes = sorted({str(e["code"]) for e in all_entries if e.get("code")})
    quotes = ds.get_realtime_quotes(codes) if codes else {}
    if codes:
        print(f"[DASHBOARD] 拉取 {len(codes)} 只标的最新行情，成功 {len(quotes)} 只")

    out = {"generated_at": now.strftime("%Y-%m-%d %H:%M:%S"), "windows": {}}
    for w in windows:
        d = build_dashboard(w, now, quotes)
        out["windows"][str(w)] = d
        print()
        print(fmt_summary(d))

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[DASHBOARD] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
