# -*- coding: utf-8 -*-
"""趋势突破策略（融合熊猫有财投资体系）。

策略逻辑（融合后）：
- 股价突破20日新高（前20日最高）
- 当日放量（量比>1.5）
- 收盘价>20日均线（熊猫有财核心规则：确认多头趋势再进场）
- 均线多头排列（MA5>MA10>MA20）
- 位置判断：低位突破加分，高位突破减分（熊猫有财首板四重判断）
- 量价配合：放量上涨加分，缩量上涨减分（熊猫有财四句量价口诀）
- 板块龙头：强势板块龙头加分（熊猫有财板块地位判断）

适合：震荡市中的局部热点和突破行情

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
    """趋势突破扫描器（融合熊猫有财投资体系）。"""

    def __init__(self):
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.quality_pool = self._load_quality_pool()
        self.optimized_params = self._load_optimized_params()
        self.cooldown_codes = self._load_cooldown_codes()

    def _load_cooldown_codes(self) -> set:
        """加载冷却期股票（最近10天内被止损的股票不再推荐）。"""
        import json as _json
        from datetime import datetime, timedelta
        tracking_file = ds.os.path.join(self.base_dir, 'data', 'tracking.jsonl')
        cooldown = set()
        try:
            if ds.os.path.exists(tracking_file):
                cooldown_days = self.optimized_params.get('cooldown_days', 10)
                cutoff = (datetime.now() - timedelta(days=cooldown_days)).strftime('%Y-%m-%d')
                with open(tracking_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = _json.loads(line)
                            if rec.get('status') == 'completed':
                                day5 = rec.get('day5_return_pct')
                                day10 = rec.get('day10_return_pct')
                                if (day5 is not None and day5 < -3) or (day10 is not None and day10 < -3):
                                    scan_date = str(rec.get('scan_time', ''))[:10]
                                    if scan_date >= cutoff:
                                        cooldown.add(rec.get('code', ''))
                        except Exception:
                            continue
        except Exception:
            pass
        return cooldown

    def _load_optimized_params(self) -> dict:
        """加载Agent优化的参数（周度优化器自动调整）。"""
        import json as _json
        state_file = ds.os.path.join(self.base_dir, 'data', 'optimization_state.json')
        default_params = {
            'volume_ratio_min': 1.5,
            'min_score': 40,
            'cooldown_days': 10,
        }
        try:
            if ds.os.path.exists(state_file):
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = _json.load(f)
                optimized = state.get('current_params', {}).get('breakout', {})
                return {**default_params, **optimized}
        except Exception:
            pass
        return default_params

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
        """计算突破指标（融合位置判断、量价配合）。"""
        df = ds.get_kline_daily(stock["code"], count=60)
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

        # 放量（量比）
        if len(volumes) >= 6:
            avg_vol_5d = float(volumes.iloc[-6:-1].mean())
            today_vol = float(volumes.iloc[-1])
            stock["volume_ratio"] = today_vol / avg_vol_5d if avg_vol_5d > 0 else 0
        else:
            stock["volume_ratio"] = 0

        # 均线多头 + 20日均线（熊猫有财核心规则）
        ma5 = float(closes.iloc[-5:].mean())
        ma10 = float(closes.iloc[-10:].mean())
        ma20 = float(closes.iloc[-20:].mean())
        stock["ma_bullish"] = ma5 > ma10 > ma20
        stock["ma5"] = ma5
        stock["ma10"] = ma10
        stock["ma20"] = ma20
        # 熊猫有财：收盘价必须>20日均线才允许进场
        stock["above_ma20"] = current_price > ma20

        # 当日涨幅
        if len(closes) >= 2:
            stock["today_gain_pct"] = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100
        else:
            stock["today_gain_pct"] = 0

        # === 融合1：位置判断（熊猫有财首板四重判断）===
        if len(closes) >= 60:
            low_60d = float(closes.iloc[-60:].min())
            high_60d = float(closes.iloc[-60:].max())
            gain_from_low = (current_price - low_60d) / low_60d * 100 if low_60d > 0 else 0
            distance_from_high = (high_60d - current_price) / high_60d * 100 if high_60d > 0 else 0
            stock["gain_from_60d_low"] = gain_from_low
            stock["distance_from_60d_high"] = distance_from_high
            # 低位：距60日低点涨幅<30%，风险小上行空间足
            # 高位：距60日高点<10% 或 累计涨幅>50%，风险极高
            if gain_from_low < 30:
                stock["position_type"] = "low"
                stock["position_score"] = 20
            elif gain_from_low > 50 or distance_from_high < 10:
                stock["position_type"] = "high"
                stock["position_score"] = -20
            else:
                stock["position_type"] = "mid"
                stock["position_score"] = 0
        else:
            stock["position_type"] = "unknown"
            stock["position_score"] = 0

        # === 融合2：量价配合（熊猫有财四句量价口诀）===
        # 价涨量同步放大 = 上涨趋势健康（加分）
        # 价格上涨成交量持续萎缩 = 虚涨无资金支撑（减分）
        if len(volumes) >= 10 and stock["today_gain_pct"] > 0:
            # 近5日成交量 vs 前5日成交量，判断放量还是缩量趋势
            recent_5d_vol = float(volumes.iloc[-5:].mean())
            prev_5d_vol = float(volumes.iloc[-10:-5].mean())
            vol_trend = (recent_5d_vol - prev_5d_vol) / prev_5d_vol * 100 if prev_5d_vol > 0 else 0
            stock["vol_trend_pct"] = vol_trend
            if vol_trend > 10:
                # 放量上涨：健康
                stock["vol_price_health"] = "healthy"
                stock["vol_price_score"] = 15
            elif vol_trend < -10:
                # 缩量上涨：虚涨无支撑
                stock["vol_price_health"] = "weak"
                stock["vol_price_score"] = -10
            else:
                stock["vol_price_health"] = "normal"
                stock["vol_price_score"] = 0
        else:
            stock["vol_price_health"] = "unknown"
            stock["vol_price_score"] = 0

        return stock

    def _calc_composite_score(self, s: dict) -> float:
        """综合打分（融合熊猫有财体系）。

        打分构成：
        - 基础分：涨幅*3 + 量比*5
        - 量价配合：放量上涨+15，缩量上涨-10
        - 位置：低位+20，高位-20
        - 20日均线之上：+5
        """
        base = s.get("today_gain_pct", 0) * 3 + s.get("volume_ratio", 0) * 5
        vol_price = s.get("vol_price_score", 0)
        position = s.get("position_score", 0)
        ma20_bonus = 5 if s.get("above_ma20") else 0
        total = base + vol_price + position + ma20_bonus
        return round(max(0, min(total, 100)), 1)

    def run(self, max_stocks: int = 1200, need_push: bool = False) -> Dict:
        """执行趋势突破扫描（融合熊猫有财投资体系）。"""
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
            # 融合优化：同股冷却期（最近10天止损过的股票不再推荐）
            if code in self.cooldown_codes:
                continue
            candidates.append(s)

        LOG.info(f"[趋势突破] 初筛通过 {len(candidates)} 只")

        # 3. 并发计算突破指标
        with ThreadPoolExecutor(max_workers=12) as pool:
            enriched = list(pool.map(self._calc_breakout_metrics, candidates))

        # 4. 突破条件过滤（融合熊猫有财规则）
        breakout_list = []
        reject_reasons = Counter()
        for s in enriched:
            if not s.get("is_breakout"):
                reject_reasons["未突破20日新高"] += 1
                continue
            vr_min = self.optimized_params.get('volume_ratio_min', 1.5)
            if s.get("volume_ratio", 0) < vr_min:
                reject_reasons[f"量比{s.get('volume_ratio', 0):.1f}<{vr_min}"] += 1
                continue
            # 融合：熊猫有财核心规则 - 收盘价必须>20日均线
            if not s.get("above_ma20"):
                reject_reasons["收盘价低于20日均线"] += 1
                continue
            if not s.get("ma_bullish"):
                reject_reasons["均线非多头排列"] += 1
                continue
            # 融合：高位突破大幅减分但不过滤（让打分决定）
            breakout_list.append(s)

        LOG.info(f"[趋势突破] 突破条件通过 {len(breakout_list)} 只")
        result["passed_count"] = len(breakout_list)
        top_rejects = [r for r, _ in reject_reasons.most_common(3)]

        # 5. 黄阳五维基本面打分（融合黄阳价值投资体系）
        # 只对突破条件通过的股票获取基本面，控制耗时
        try:
            from .fundamental_filter import batch_get_fundamental
            from .huangyang_scorer import get_huangyang_scorer
            hy_scorer = get_huangyang_scorer()
            breakout_codes = [s["code"] for s in breakout_list]
            fundamentals = batch_get_fundamental(breakout_codes)
            for s in breakout_list:
                fund = fundamentals.get(s["code"], {})
                if fund:
                    hy_result = hy_scorer.score(s["name"], fund)
                    s["huangyang_score"] = hy_result["total_score"]
                    s["huangyang_grade"] = hy_result["grade"]
                    s["huangyang_summary"] = hy_result["summary"]
                    s["fundamental_data"] = fund
                else:
                    s["huangyang_score"] = 50  # 无数据时中性分
                    s["huangyang_grade"] = "未知"
                    s["huangyang_summary"] = "基本面数据缺失"
        except Exception as e:
            LOG.warning(f"[趋势突破] 黄阳五维打分失败: {e}，使用中性分")
            for s in breakout_list:
                s["huangyang_score"] = 50
                s["huangyang_grade"] = "未知"
                s["huangyang_summary"] = ""

        # 6. 基本面硬过滤（黄阳价值投资核心理念：好生意+好公司+好价格）
        # 第一档：过滤掉偏弱(<50分)和差，只保留一般及以上
        fundamental_filtered = [s for s in breakout_list if s.get("huangyang_score", 50) >= 50]
        if not fundamental_filtered:
            # 降级：只过滤差(<40分)，保留偏弱
            fundamental_filtered = [s for s in breakout_list if s.get("huangyang_score", 50) >= 40]
            LOG.info("[趋势突破] 基本面硬过滤降级：一般及以上无标的，放宽到偏弱及以上")
        if not fundamental_filtered:
            # 再降级：不过滤，但全部标记基本面风险
            fundamental_filtered = breakout_list
            LOG.info("[趋势突破] 基本面硬过滤再次降级：无标的满足基本面要求，全部保留但标记风险")
        filtered_count = len(breakout_list) - len(fundamental_filtered)
        if filtered_count > 0:
            LOG.info(f"[趋势突破] 基本面硬过滤：{filtered_count}只基本面不达标被过滤")

        # 7. 综合打分排序（融合熊猫有财技术面 + 黄阳基本面）
        for s in fundamental_filtered:
            tech_score = self._calc_composite_score(s)
            # 技术面60% + 黄阳基本面40%
            s["composite_score"] = round(tech_score * 0.6 + s.get("huangyang_score", 50) * 0.4, 1)
        fundamental_filtered.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        top = fundamental_filtered[:5]

        # 7. 生成推荐条目
        entries = []
        for s in top:
            # 构建推荐理由（融合位置和量价信息）
            reason_parts = [
                f"突破20日新高({s.get('breakout_high', 0):.2f}元)",
                f"量比{s.get('volume_ratio', 0):.1f}",
            ]
            if s.get("position_type") == "low":
                reason_parts.append("低位突破")
            elif s.get("position_type") == "high":
                reason_parts.append("高位突破⚠️")
            if s.get("vol_price_health") == "healthy":
                reason_parts.append("放量健康")
            elif s.get("vol_price_health") == "weak":
                reason_parts.append("缩量虚涨⚠️")
            reason_parts.append("均线多头")

            entries.append({
                "code": s["code"],
                "name": s["name"],
                "price": s["price"],
                "score": s["composite_score"],
                "today_gain_pct": round(s.get("today_gain_pct", 0), 1),
                "volume_ratio": round(s.get("volume_ratio", 0), 2),
                "breakout_high": round(s.get("breakout_high", 0), 2),
                "position_type": s.get("position_type", "unknown"),
                "vol_price_health": s.get("vol_price_health", "unknown"),
                "huangyang_score": s.get("huangyang_score", 50),
                "huangyang_grade": s.get("huangyang_grade", "未知"),
                "reason": "，".join(reason_parts),
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
    """趋势突破策略飞书消息（极简版，融合黄阳基本面评级）。"""
    entries = result.get("entries", [])
    if not entries:
        return "🚀 趋势突破：无推荐"

    lines = ["🚀 趋势突破："]
    for i, e in enumerate(entries, 1):
        # 位置标记
        pos_tag = ""
        if e.get("position_type") == "low":
            pos_tag = "低位"
        elif e.get("position_type") == "high":
            pos_tag = "高位⚠️"
        # 量价标记
        vp_tag = ""
        if e.get("vol_price_health") == "healthy":
            vp_tag = "放量"
        elif e.get("vol_price_health") == "weak":
            vp_tag = "缩量⚠️"
        tags = f"[{pos_tag}{vp_tag}]" if pos_tag or vp_tag else ""
        # 黄阳基本面评级
        hy_grade = e.get("huangyang_grade", "")
        hy_tag = f"基本面{hy_grade}" if hy_grade and hy_grade != "未知" else ""
        all_tags = f"{tags}{hy_tag}" if hy_tag else tags
        lines.append(f"  {i}. {e['name']}({e['code']}) {e['price']}元 +{e['today_gain_pct']}% 得分{e['score']}{all_tags}")
    return "\n".join(lines)
