# -*- coding: utf-8 -*-
"""趋势突破策略。

策略逻辑：
- 股价突破20日新高（前20日最高）
- 当日放量（量比>1.5）
- 均线多头排列（MA5>MA10>MA20）
- 适合：震荡市中的局部热点和突破行情

风控：
- 止损-4%（更严，假突破多）
- 止盈+8%（更快，突破行情短期爆发力强）
- 单票仓位25%
"""
from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from . import data_source as ds
from .config import HARD_FILTERS
from .trading_calendar import now_bjt
from .filters import pass_hard_filters

import logging
LOG = logging.getLogger("scanner")


class BreakoutScanner:
    """趋势突破扫描器。"""

    def __init__(self):
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.quality_pool = self._load_quality_pool()

    def _load_quality_pool(self) -> set:
        pool_file = ds.os.path.join(self.base_dir, "data", "quality_pool.json")
        try:
            import json
            with open(pool_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {item["code"] for item in data if "code" in item}
        except Exception:
            return set()

    def _calc_breakout_metrics(self, stock: dict) -> dict:
        """计算突破指标。"""
        df = ds.get_kline_daily(stock["code"], count=30)
        if df.empty or len(df) < 25:
            stock["breakout"] = False
            return stock

        closes = df["close"].astype(float)
        highs = df["high"].astype(float)
        volumes = df["volume"].astype(float)

        # 突破20日新高（前20日最高，不含当日）
        recent_high = float(highs.iloc[-21:-1].max())
        current_price = float(closes.iloc[-1])
        stock["breakout_high"] = recent_high
        stock["is_breakout"] = current_price > recent_high

        # 放量
        if len(volumes) >= 6:
            avg_vol_5d = float(volumes.iloc[-6:-1].mean())
            today_vol = float(volumes.iloc[-1])
            stock["volume_ratio"] = today_vol / avg_vol_5d if avg_vol_5d > 0 else 0
        else:
            stock["volume_ratio"] = 0

        # 均线多头
        ma5 = float(closes.iloc[-5:].mean())
        ma10 = float(closes.iloc[-10:].mean())
        ma20 = float(closes.iloc[-20:].mean())
        stock["ma_bullish"] = ma5 > ma10 > ma20
        stock["ma5"] = ma5
        stock["ma10"] = ma10
        stock["ma20"] = ma20

        # 当日涨幅
        if len(closes) >= 2:
            stock["today_gain_pct"] = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100
        else:
            stock["today_gain_pct"] = 0

        return stock

    def run(self, max_stocks: int = 1200, need_push: bool = False) -> Dict:
        """执行趋势突破扫描。"""
        t0 = time.time()
        result = {
            "scan_time": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "breakout",
            "entries": [],
            "scanned_count": 0,
            "passed_count": 0,
            "recommend_count": 0,
            "summary": "",
            "diagnosis": "",
            "scan_elapsed": 0.0,
        }

        # 1. 获取股票池
        from .data_validator import get_cached_pool, set_cached_pool
        try:
            cached = get_cached_pool()
            if cached and len(cached) >= 100:
                all_stocks = cached[:max_stocks]
            else:
                all_stocks = ds.get_mainboard_stocks(limit=max_stocks)
                if len(all_stocks) >= 100:
                    set_cached_pool(all_stocks)
        except Exception:
            all_stocks = ds.get_mainboard_stocks(limit=max_stocks)

        result["scanned_count"] = len(all_stocks)

        # 2. 初筛（价格、市值、非ST、主板、优质池）
        candidates = []
        for s in all_stocks:
            name = str(s.get("name", ""))
            code = str(s.get("code", ""))
            if "ST" in name.upper() or "退" in name:
                continue
            if not code.startswith(("60", "00")):
                continue
            if self.quality_pool and code not in self.quality_pool:
                continue
            price = float(s.get("price", 0) or 0)
            cap = float(s.get("float_cap_yi", 0) or 0)
            if price < HARD_FILTERS["price_min"] or price > HARD_FILTERS["price_max"]:
                continue
            if cap < HARD_FILTERS["cap_min_yi"] or cap > HARD_FILTERS["cap_max_yi"]:
                continue
            candidates.append(s)

        LOG.info(f"[趋势突破] 初筛通过 {len(candidates)} 只")

        # 3. 并发计算突破指标
        with ThreadPoolExecutor(max_workers=12) as pool:
            enriched = list(pool.map(self._calc_breakout_metrics, candidates))

        # 4. 突破条件过滤
        breakout_list = []
        reject_reasons = Counter()
        for s in enriched:
            if not s.get("is_breakout"):
                reject_reasons["未突破20日新高"] += 1
                continue
            if s.get("volume_ratio", 0) < 1.5:
                reject_reasons[f"量比{s.get('volume_ratio', 0):.1f}<1.5"] += 1
                continue
            if not s.get("ma_bullish"):
                reject_reasons["均线非多头排列"] += 1
                continue
            breakout_list.append(s)

        LOG.info(f"[趋势突破] 突破条件通过 {len(breakout_list)} 只")
        result["passed_count"] = len(breakout_list)
        top_rejects = [r for r, _ in reject_reasons.most_common(3)]

        # 5. 按涨幅排序，取前5
        breakout_list.sort(key=lambda x: x.get("today_gain_pct", 0), reverse=True)
        top = breakout_list[:5]

        # 6. 生成推荐条目
        entries = []
        for s in top:
            entries.append({
                "code": s["code"],
                "name": s["name"],
                "price": s["price"],
                "score": round(min(s.get("today_gain_pct", 0) * 5 + s.get("volume_ratio", 0) * 10, 100), 1),
                "today_gain_pct": round(s.get("today_gain_pct", 0), 1),
                "volume_ratio": round(s.get("volume_ratio", 0), 2),
                "breakout_high": round(s.get("breakout_high", 0), 2),
                "reason": (
                    f"突破20日新高({s.get('breakout_high', 0):.2f}元)，"
                    f"量比{s.get('volume_ratio', 0):.1f}放量，均线多头排列"
                ),
            })

        result["entries"] = entries
        result["recommend_count"] = len(entries)
        result["summary"] = (
            f"趋势突破：扫描{len(all_stocks)}只 → 初筛{len(candidates)}只 → "
            f"突破条件{len(breakout_list)}只 → 推荐{len(entries)}只"
        )
        result["diagnosis"] = (
            f"扫描{len(all_stocks)}只 → 突破条件{len(breakout_list)}只 → 推荐{len(entries)}只"
            f" | 主要拒因：{'、'.join(top_rejects) if top_rejects else '无'}"
        )
        result["scan_elapsed"] = round(time.time() - t0, 1)
        LOG.info(f"[趋势突破] {result['summary']}，耗时{result['scan_elapsed']}s")
        return result


def build_breakout_message(result: Dict) -> str:
    """趋势突破策略飞书消息。"""
    now = now_bjt().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"🚀 趋势突破策略 盘中实时 {now}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "【趋势突破推荐】",
    ]

    entries = result.get("entries", [])
    if entries:
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. {e['name']}({e['code']}) | 现价{e['price']}元 | 今日+{e['today_gain_pct']}%")
            lines.append(f"   突破20日新高{e['breakout_high']}元 | 量比{e['volume_ratio']} | 得分{e['score']}")
            lines.append(f"   {e['reason']}")
            lines.append("")
        lines.append("💼 仓位建议（5000元本金）")
        lines.append("  单票≤1250元（25%），最多2只")
        lines.append("  止盈：+8%清仓 | 止损：-4%（突破策略假突破多，止损更严）")
    else:
        lines.append("  当前无符合趋势突破的标的，继续观望")

    lines.append("")
    lines.append(f"📈 诊断：{result.get('diagnosis', '')}")
    lines.append("⚠️ 仅为策略信号，不构成投资建议，最终操作请自行判断")
    lines.append(f"⏱ 触发时间：北京时间{now} | 扫描耗时{result.get('scan_elapsed', 0)}s")
    return "\n".join(lines)
