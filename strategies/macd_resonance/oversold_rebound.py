# -*- coding: utf-8 -*-
"""超跌反弹模式扫描器。

捕捉类似天通股份2026年8月的暴利机会：
- 前期超跌（20日跌幅≥25%）
- 底部横盘筑底（近5日振幅≤12%）
- 放量启动（当日涨幅≥4%，量比≥1.8）
- 技术确认（60分钟MACD金叉，日线DIF>-0.8）
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from . import data_source as ds
from .config import OVERSOLD_REBOUND, HARD_FILTERS
from .signal_engine import SignalEngine
from .trading_calendar import now_bjt

LOG = logging.getLogger("scanner")


class OversoldReboundScanner:
    """超跌反弹扫描器。"""

    def __init__(self):
        self.engine = SignalEngine()
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.cache_file = ds.os.path.join(self.base_dir, "data", "oversold_cache.json")
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        try:
            import json
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"pushed": {}}

    def _save_cache(self):
        import json
        import os
        os.makedirs(ds.os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def _is_in_cooldown(self, code: str) -> bool:
        from datetime import datetime
        last = self.cache.get("pushed", {}).get(code)
        if not last:
            return False
        try:
            last_ts = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
        now = now_bjt().replace(tzinfo=None)
        hours = (now - last_ts).total_seconds() / 3600
        return hours < OVERSOLD_REBOUND["cooldown_hours"]

    def _mark_pushed(self, code: str):
        self.cache.setdefault("pushed", {})[code] = now_bjt().strftime("%Y-%m-%d %H:%M:%S")
        self._save_cache()

    def _calc_oversold_metrics(self, stock: dict) -> dict:
        """计算超跌指标：20日跌幅、近5日振幅、当日涨幅、量比。"""
        df = ds.get_kline_daily(stock["code"], count=30)
        if df.empty or len(df) < 25:
            stock["drop_20d_pct"] = 0.0
            stock["consolidate_amp_pct"] = 999.0
            stock["today_gain_pct"] = 0.0
            stock["volume_ratio"] = 0.0
            return stock

        closes = df["close"].astype(float)
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        volumes = df["volume"].astype(float)

        # 20日跌幅：(20日前收盘 - 最新收盘) / 20日前收盘 * 100
        if len(closes) >= 21:
            base_20d = float(closes.iloc[-21])
            latest = float(closes.iloc[-1])
            if base_20d > 0:
                stock["drop_20d_pct"] = (base_20d - latest) / base_20d * 100.0
            else:
                stock["drop_20d_pct"] = 0.0
        else:
            stock["drop_20d_pct"] = 0.0

        # 近5日振幅（筑底确认）
        n = OVERSOLD_REBOUND["consolidate_days"]
        if len(closes) >= n:
            recent_high = float(highs.iloc[-n:].max())
            recent_low = float(lows.iloc[-n:].min())
            base = float(closes.iloc[-n])
            if base > 0:
                stock["consolidate_amp_pct"] = (recent_high - recent_low) / base * 100.0
            else:
                stock["consolidate_amp_pct"] = 999.0
        else:
            stock["consolidate_amp_pct"] = 999.0

        # 当日涨幅
        if len(closes) >= 2:
            prev_close = float(closes.iloc[-2])
            today_close = float(closes.iloc[-1])
            if prev_close > 0:
                stock["today_gain_pct"] = (today_close - prev_close) / prev_close * 100.0
            else:
                stock["today_gain_pct"] = 0.0
        else:
            stock["today_gain_pct"] = 0.0

        # 量比：当日成交量 / 前5日均量
        if len(volumes) >= 6:
            today_vol = float(volumes.iloc[-1])
            avg_vol_5d = float(volumes.iloc[-6:-1].mean())
            if avg_vol_5d > 0:
                stock["volume_ratio"] = today_vol / avg_vol_5d
            else:
                stock["volume_ratio"] = 0.0
        else:
            stock["volume_ratio"] = 0.0

        return stock

    def _quick_filter(self, stock: dict) -> bool:
        """初筛：价格、市值、非ST、主板。"""
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        code = str(stock.get("code", ""))
        if not code.startswith(("60", "00")):
            return False
        price = float(stock.get("price", 0) or 0)
        cap = float(stock.get("float_cap_yi", 0) or 0)
        if price < HARD_FILTERS["price_min"] or price > HARD_FILTERS["price_max"]:
            return False
        if cap < HARD_FILTERS["cap_min_yi"] or cap > HARD_FILTERS["cap_max_yi"]:
            return False
        # 当日成交额预过滤
        amt = float(stock.get("amount_yi", 0) or 0)
        if amt > 0 and amt < 0.3:
            return False
        return True

    def run(self, max_stocks: int = 2000, need_push: bool = False) -> Dict:
        """执行超跌反弹扫描。"""
        cfg = OVERSOLD_REBOUND
        result = {
            "scan_time": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "oversold_rebound",
            "entries": [],
            "scanned_count": 0,
            "passed_count": 0,
            "recommend_count": 0,
            "summary": "",
            "diagnosis": "",
            "scan_elapsed": 0.0,
        }
        t0 = time.time()

        # 1. 获取股票池
        from .data_validator import get_cached_pool, set_cached_pool, MIN_POOL_SIZE
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
        LOG.info(f"[超跌反弹] 股票池 {len(all_stocks)} 只")

        # 2. 初筛
        candidates = [s for s in all_stocks if self._quick_filter(s)]
        LOG.info(f"[超跌反弹] 初筛通过 {len(candidates)} 只")

        # 3. 并发计算超跌指标
        with ThreadPoolExecutor(max_workers=12) as pool:
            enriched = list(pool.map(self._calc_oversold_metrics, candidates))

        # 4. 超跌条件过滤
        oversold = []
        reject_reasons = Counter()
        for s in enriched:
            drop = float(s.get("drop_20d_pct", 0))
            amp = float(s.get("consolidate_amp_pct", 999))
            gain = float(s.get("today_gain_pct", 0))
            vr = float(s.get("volume_ratio", 0))

            if drop < cfg["drop_20d_min"]:
                reject_reasons[f"20日跌幅{drop:.1f}%<{cfg['drop_20d_min']}%"] += 1
                continue
            if amp > cfg["consolidate_amplitude_max"]:
                reject_reasons[f"5日振幅{amp:.1f}%>{cfg['consolidate_amplitude_max']}%"] += 1
                continue
            if gain < cfg["today_gain_min"]:
                reject_reasons[f"当日涨幅{gain:.1f}%<{cfg['today_gain_min']}%"] += 1
                continue
            if vr < cfg["volume_ratio_min"]:
                reject_reasons[f"量比{vr:.1f}<{cfg['volume_ratio_min']}"] += 1
                continue
            oversold.append(s)

        LOG.info(f"[超跌反弹] 超跌条件通过 {len(oversold)} 只")
        result["passed_count"] = len(oversold)
        top_rejects = [r for r, _ in reject_reasons.most_common(3)]

        # 5. 技术确认（60分钟金叉 + 日线DIF下限），按成交额排序取前100只分析
        oversold_sorted = sorted(oversold, key=lambda s: float(s.get("amount_yi", 0) or 0), reverse=True)
        analyze_pool = oversold_sorted[:100]
        LOG.info(f"[超跌反弹] 技术分析标的 {len(analyze_pool)} 只")

        entries: List[Dict] = []
        delay_counter = {"n": 0}

        def analyze(stock: dict):
            delay_counter["n"] += 1
            if delay_counter["n"] % 3 == 0:
                time.sleep(0.2)
            try:
                sig = self.engine.analyze_stock(stock["code"], stock["name"], stock["price"])
                return stock, sig
            except Exception as e:
                return stock, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(analyze, s) for s in analyze_pool]
            for fut in as_completed(futs):
                stock, sig = fut.result()
                if sig is None:
                    continue
                # 日线DIF下限检查
                daily_dif = getattr(sig, "daily_dif", None)
                if daily_dif is not None and daily_dif < cfg["daily_dif_floor"]:
                    continue
                # 60分钟金叉检查
                tf_status = getattr(sig, "tf_status", {}) or {}
                if cfg["tf60_require_golden"] and not tf_status.get("tf60_golden"):
                    continue
                # 30分钟金叉（可选，加分项）
                tf30_golden = tf_status.get("tf30_golden", False) if cfg["tf30_require_golden"] else True
                if cfg["tf30_require_golden"] and not tf30_golden:
                    continue

                # 综合评分
                drop = float(stock.get("drop_20d_pct", 0))
                gain = float(stock.get("today_gain_pct", 0))
                vr = float(stock.get("volume_ratio", 0))
                score = (
                    min(drop / 50.0, 1.0) * 30 +  # 超跌程度（最高30分）
                    min(gain / 10.0, 1.0) * 25 +   # 启动强度（最高25分）
                    min(vr / 5.0, 1.0) * 20 +       # 放量程度（最高20分）
                    (15 if tf30_golden else 5) +    # 30min金叉加分
                    10                               # 基础分
                )
                entry = {
                    "code": stock["code"],
                    "name": stock["name"],
                    "price": stock["price"],
                    "score": round(score, 1),
                    "drop_20d_pct": round(drop, 1),
                    "today_gain_pct": round(gain, 1),
                    "volume_ratio": round(vr, 2),
                    "consolidate_amp_pct": round(float(stock.get("consolidate_amp_pct", 0)), 1),
                    "daily_dif": round(daily_dif, 4) if daily_dif is not None else None,
                    "tf60_golden": tf_status.get("tf60_golden", False),
                    "tf30_golden": tf_status.get("tf30_golden", False),
                    "reason": (
                        f"20日跌{drop:.1f}%超跌，今日涨{gain:.1f}%放量启动，"
                        f"量比{vr:.1f}，60min金叉确认"
                    ),
                }
                entries.append(entry)

        # 6. 排序，取前N
        entries.sort(key=lambda x: x["score"], reverse=True)
        top = entries[:cfg["max_recommendations"]]

        # 7. 去重冷却
        final = []
        for e in top:
            if not self._is_in_cooldown(e["code"]):
                final.append(e)
                if need_push:
                    self._mark_pushed(e["code"])

        result["entries"] = final
        result["recommend_count"] = len(final)
        result["summary"] = (
            f"超跌反弹：扫描{len(all_stocks)}只 → 初筛{len(candidates)}只 → "
            f"超跌条件{len(oversold)}只 → 技术确认{len(entries)}只 → 推荐{len(final)}只"
        )
        result["diagnosis"] = (
            f"扫描{len(all_stocks)}只 → 超跌条件{len(oversold)}只 → 技术确认{len(entries)}只"
            f" | 主要拒因：{'、'.join(top_rejects) if top_rejects else '无'}"
        )
        result["scan_elapsed"] = round(time.time() - t0, 1)
        LOG.info(f"[超跌反弹] {result['summary']}，耗时{result['scan_elapsed']}s")
        return result


def build_oversold_message(result: Dict) -> str:
    """超跌反弹模式飞书消息。"""
    now = now_bjt().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"🚀 超跌反弹策略 盘中实时 {now}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "【超跌反弹推荐】",
    ]
    entries = result.get("entries", [])
    if entries:
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. {e['name']}({e['code']}) | 现价{e['price']}元 | 今日+{e['today_gain_pct']}%")
            lines.append(f"   20日跌幅{e['drop_20d_pct']}% | 量比{e['volume_ratio']} | 得分{e['score']}")
            lines.append(f"   {e['reason']}")
            lines.append("")
        lines.append("💼 仓位建议（5000元本金）")
        lines.append("  单票≤1500-2000元（30-40%），最多2-3只")
        lines.append("  止盈：+10%减半 / +15%清仓 | 止损：-5%")
    else:
        lines.append("  当前无符合超跌反弹的标的，继续观望")
    lines.append("")
    lines.append(f"📈 诊断：{result.get('diagnosis', '')}")
    lines.append("⚠️ 仅为策略信号，不构成投资建议，最终操作请自行判断")
    lines.append(f"⏱ 触发时间：北京时间{now} | 扫描耗时{result.get('scan_elapsed', 0)}s")
    return "\n".join(lines)
