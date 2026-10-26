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
from .adaptive_config import get_oversold_params, get_current_regime, REGIME_LABELS
from .signal_engine import SignalEngine
from .trading_calendar import now_bjt

LOG = logging.getLogger("scanner")


class OversoldReboundScanner:
    """超跌反弹扫描器。"""

    def __init__(self, use_full_market: bool = False):
        self.engine = SignalEngine()
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.cache_file = ds.os.path.join(self.base_dir, "data", "oversold_cache.json")
        self.cache = self._load_cache()
        self.quality_pool = self._load_quality_pool()
        # 全市场开关：health_monitor Level 3 降级时置 True
        self.use_full_market = use_full_market

    def _load_quality_pool(self) -> set:
        pool_file = ds.os.path.join(self.base_dir, "data", "quality_pool.json")
        try:
            import json
            with open(pool_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            codes = {item["code"] for item in data if "code" in item}
            LOG.info(f"[超跌反弹] 优质股票池加载成功：{len(codes)}只")
            return codes
        except Exception as e:
            LOG.warning(f"[超跌反弹] 优质股票池加载失败，使用全市场扫描: {e}")
            return set()

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
        """计算超跌/回调指标。

        兼容两种口径（由 adaptive_params 决定）：
        - 真超跌（熊市）：drop_20d_pct = (20 日前收盘 - 最新收盘) / 20 日前收盘 * 100
        - 趋势回调（牛市）：drop_from_20d_high_pct = (20 日高点 - 最新收盘) / 20 日高点 * 100

        两者都算，下游按 cfg 决定用哪一个作为过滤条件。
        """
        df = ds.get_kline_daily(stock["code"], count=30)
        if df.empty or len(df) < 25:
            stock["drop_20d_pct"] = 0.0
            stock["drop_from_20d_high_pct"] = 0.0
            stock["consolidate_amp_pct"] = 999.0
            stock["today_gain_pct"] = 0.0
            stock["volume_ratio"] = 0.0
            stock["pullback_days"] = 0
            stock["pullback_vol_ratio"] = 0.0
            return stock

        closes = df["close"].astype(float)
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        volumes = df["volume"].astype(float)

        # 20日跌幅（真超跌口径）
        if len(closes) >= 21:
            base_20d = float(closes.iloc[-21])
            latest = float(closes.iloc[-1])
            if base_20d > 0:
                stock["drop_20d_pct"] = (base_20d - latest) / base_20d * 100.0
            else:
                stock["drop_20d_pct"] = 0.0
        else:
            stock["drop_20d_pct"] = 0.0

        # 20日高点回调（趋势回调口径）：从 20 日最高价回落的百分比
        high_20d = float(highs.iloc[-20:].max())
        latest = float(closes.iloc[-1])
        if high_20d > 0:
            stock["drop_from_20d_high_pct"] = (high_20d - latest) / high_20d * 100.0
        else:
            stock["drop_from_20d_high_pct"] = 0.0

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

        # 回调天数：从 20 日高点到今天的连续下跌/横盘天数
        # 定义：从 20 日最高点当日开始，close 连续 ≤ 高点 * (1 - 0.02) 的天数
        stock["pullback_days"] = self._calc_pullback_days(closes, high_20d)

        # 回调期平均量比：从回调起点到今天（不含今日）的平均量 / 今日前的 5 日均量
        # 简化：用回调期成交量均值 / 前 20 日成交量均值
        stock["pullback_vol_ratio"] = self._calc_pullback_vol_ratio(
            volumes, stock.get("pullback_days", 0))

        return stock

    @staticmethod
    def _calc_pullback_days(closes, high_20d: float) -> int:
        """从 20 日高点当日开始，计算 close 持续低于高点 -2% 的天数。"""
        if high_20d <= 0 or len(closes) < 3:
            return 0
        threshold = high_20d * 0.98
        days = 0
        for i in range(len(closes) - 1, max(-1, len(closes) - 21), -1):
            if float(closes.iloc[i]) <= threshold:
                days += 1
            else:
                break
        return days

    @staticmethod
    def _calc_pullback_vol_ratio(volumes, pullback_days: int) -> float:
        """回调期平均量 / 前 20 日均量。回调期定义为最近 pullback_days 天（不含今日）。"""
        if pullback_days <= 0 or len(volumes) < 6:
            return 0.0
        # 回调期：今天之前 pullback_days 天的平均量
        pb_start = max(-1 - pullback_days, -len(volumes) - 1)
        pb_slice = volumes.iloc[pb_start:-1] if pullback_days < len(volumes) else volumes.iloc[:-1]
        if len(pb_slice) == 0:
            return 0.0
        pb_avg = float(pb_slice.mean())
        # 基准：前 20 日（不含回调期与今日）的平均量
        ref_end = -1 - pullback_days if pullback_days < len(volumes) else -1
        ref_slice = volumes.iloc[max(-1, ref_end - 20):ref_end]
        if len(ref_slice) == 0 or float(ref_slice.mean()) <= 0:
            return 0.0
        return pb_avg / float(ref_slice.mean())

    def _quick_filter(self, stock: dict) -> bool:
        """初筛：价格、市值、非ST、主板、优质股票池。"""
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        code = str(stock.get("code", ""))
        if not code.startswith(("60", "00")):
            return False
        # 优质股票池过滤（基本面预筛选）；Level 3 降级时退回全市场
        if self.quality_pool and not self.use_full_market and code not in self.quality_pool:
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

    def run(self, max_stocks: int = 2000, need_push: bool = False,
            param_override: Optional[Dict] = None) -> Dict:
        """执行超跌反弹扫描。

        Args:
            param_override: health_monitor.get_current_params_override() 的返回值；
                其中的 ``oversold`` 覆盖会合并进 cfg，``general.use_full_market``
                会打开全市场扫描。Level 2 起把 20 日跌幅要求从 30% 放宽到 20%，
                这是让 Agent 在长期 0 推荐时能重新拿到学习素材的关键路径。
        """
        cfg = OVERSOLD_REBOUND.copy()
        # 自适应：获取当前市场环境和动态参数
        from .data_validator import get_data_with_fallback
        try:
            market_data, _ = get_data_with_fallback()
        except Exception:
            market_data = None
        regime = get_current_regime(market_data)
        adaptive_params = get_oversold_params(regime)
        # ⚠️ 覆盖字段必须与 adaptive_config.OVERSOLD_PARAMS 保持同步：
        # 新增字段（drop_from_20d_high_min/max、pullback_days/max、volume_shrink_min）
        # 如果不加入这个覆盖列表，牛市回调口径就不会生效，实测 bull_market 里 100% 被 drop_20d_min=0
        # 拒掉（因为 drop_20d_min 覆盖了原 OVERSOLD_REBOUND 里的 25.0）。
        for key in ['drop_20d_min', 'drop_from_20d_high_min', 'drop_from_20d_high_max',
                    'pullback_days', 'pullback_days_max', 'volume_shrink_min',
                    'today_gain_min', 'volume_ratio_min', 'daily_dif_floor',
                    'max_recommendations']:
            if key in adaptive_params:
                cfg[key] = adaptive_params[key]

        # 健康度降级覆盖（Level 2 起放宽超跌要求）
        degradation_level = 0
        if param_override:
            from .health_monitor import HealthMonitor
            cfg = HealthMonitor.merge_override(cfg, "oversold", param_override)
            self.use_full_market = bool(
                param_override.get("general", {}).get("use_full_market", False)
            )
            degradation_level = int(param_override.get("level", 0))
        LOG.info(f"[自适应] 市场环境={regime}({REGIME_LABELS.get(regime, '未知')}) 参数={adaptive_params['name']} 超跌要求={cfg['drop_20d_min']}% 启动涨幅={cfg['today_gain_min']}% 降级Level={degradation_level} 全市场={self.use_full_market}")
        result = {
            "scan_time": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "oversold_rebound",
            "degradation_level": degradation_level,
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

        # 4. 超跌/回调条件过滤
        # ⚠️ 2026-09-22 重设计：支持两种口径，由 adaptive_params 决定：
        #   - 熊市（drop_from_20d_high_min=0, high_max=100）：走「真超跌」口径，只看 drop_20d_min
        #   - 牛市（drop_20d_min=0, high_min=8, high_max=20）：走「趋势回调」口径，
        #     看 drop_from_20d_high_pct 是否在 [high_min, high_max] 区间
        oversold = []
        reject_reasons = Counter()
        high_min = float(cfg.get("drop_from_20d_high_min", 0))
        high_max = float(cfg.get("drop_from_20d_high_max", 100))
        pb_min = int(cfg.get("pullback_days", 0))
        pb_max = int(cfg.get("pullback_days_max", 999))
        vol_shrink_min = float(cfg.get("volume_shrink_min", 0))

        for s in enriched:
            drop = float(s.get("drop_20d_pct", 0))
            high_drop = float(s.get("drop_from_20d_high_pct", 0))
            amp = float(s.get("consolidate_amp_pct", 999))
            gain = float(s.get("today_gain_pct", 0))
            vr = float(s.get("volume_ratio", 0))
            pb_days = int(s.get("pullback_days", 0))
            pb_vol = float(s.get("pullback_vol_ratio", 0))

            # 20 日跌幅下限（熊市口径）
            if drop < cfg["drop_20d_min"]:
                reject_reasons[f"20日跌幅{drop:.1f}%<{cfg['drop_20d_min']}%"] += 1
                continue
            # 20 日高点回调区间（牛市回调口径）
            if high_min > 0 and (high_drop < high_min or high_drop > high_max):
                reject_reasons[f"20日高点回调{high_drop:.1f}%不在[{high_min},{high_max}]"] += 1
                continue
            # 回调天数（牛市：3-8 天，避免刚启动或已走坏）
            if pb_min > 0 and pb_days < pb_min:
                reject_reasons[f"回调仅{pb_days}天<{pb_min}"] += 1
                continue
            if pb_max < 999 and pb_days > pb_max:
                reject_reasons[f"回调{pb_days}天>{pb_max}"] += 1
                continue
            # 回调期缩量确认（牛市：回调期量比 ≥0.6 才算缩量筑底）
            if vol_shrink_min > 0 and pb_vol < vol_shrink_min:
                reject_reasons[f"回调期量比{pb_vol:.2f}<{vol_shrink_min}"] += 1
                continue
            # 振幅上限（牛市回调振幅可能较大，这里保持宽松）
            if amp > cfg["consolidate_amplitude_max"]:
                reject_reasons[f"5日振幅{amp:.1f}%>{cfg['consolidate_amplitude_max']}%"] += 1
                continue
            # 当日涨幅
            if gain < cfg["today_gain_min"]:
                reject_reasons[f"当日涨幅{gain:.1f}%<{cfg['today_gain_min']}%"] += 1
                continue
            # 量比
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
                    "drop_from_20d_high_pct": round(float(stock.get("drop_from_20d_high_pct", 0)), 1),
                    "pullback_days": int(stock.get("pullback_days", 0)),
                    "today_gain_pct": round(gain, 1),
                    "volume_ratio": round(vr, 2),
                    "consolidate_amp_pct": round(float(stock.get("consolidate_amp_pct", 0)), 1),
                    "daily_dif": round(daily_dif, 4) if daily_dif is not None else None,
                    "tf60_golden": tf_status.get("tf60_golden", False),
                    "tf30_golden": tf_status.get("tf30_golden", False),
                    "reason": (
                        f"20日跌{drop:.1f}%/从高点回调{float(stock.get('drop_from_20d_high_pct', 0)):.1f}%，"
                        f"今日涨{gain:.1f}%放量启动，量比{vr:.1f}，60min金叉确认"
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
        result["regime"] = regime
        result["regime_label"] = REGIME_LABELS.get(regime, "未知")
        result["adaptive_params"] = adaptive_params
        LOG.info(f"[超跌反弹] {result['summary']}，耗时{result['scan_elapsed']}s")
        return result


def build_oversold_message(result: Dict) -> str:
    """超跌反弹策略飞书消息（极简版）。"""
    entries = result.get("entries", [])
    if not entries:
        return "🚀 超跌反弹：无推荐"
    lines = ["🚀 超跌反弹："]
    for i, e in enumerate(entries, 1):
        lines.append(f"  {i}. {e['name']}({e['code']}) {e['price']}元 +{e['today_gain_pct']}% 得分{e['score']}")
    return "\n".join(lines)

