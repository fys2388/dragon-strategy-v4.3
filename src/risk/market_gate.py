"""
大盘闸门

评估大盘环境，决定总仓位上限。
0-10 分制：
  ≥7 强市 → 标准仓位
  ≥5 正常 → 半仓
  ≥3 弱市 → 轻仓 30%
  <3 极弱 → 空仓观望
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional

from config.settings import MARKET_GATE, DATA_SOURCE
from src.data.source import data_source
from src.data.cache import cache

logger = logging.getLogger(__name__)


class MarketGate:
    """大盘闸门"""

    def __init__(self):
        self.thresholds = MARKET_GATE["gate_thresholds"]
        self.benchmark_code = MARKET_GATE["benchmark_code"]

    def evaluate(self) -> Dict:
        """
        评估大盘环境

        Returns:
            dict with:
            - score: 总分 (0-10)
            - level: strong/normal/weak/closed
            - max_position_pct: 建议最大总仓位
            - indicators: 各维度评分明细
        """
        score = 0.0
        indicators = {}

        # 1. 基准趋势（30%）
        trend_score = self._check_benchmark_trend()
        score += 3.0 * trend_score
        indicators["benchmark_trend"] = {
            "score": round(trend_score, 2),
            "weight": 0.30,
            "desc": "基准指数在60日线上方且60日线向上",
        }

        # 2. 成交量（25%）
        volume_score = self._check_volume_situation()
        score += 2.5 * volume_score
        indicators["volume_situation"] = {
            "score": round(volume_score, 2),
            "weight": 0.25,
            "desc": "市场成交额放大",
        }

        # 3. 市场宽度（20%）
        breadth_score = self._check_breadth()
        score += 2.0 * breadth_score
        indicators["breadth"] = {
            "score": round(breadth_score, 2),
            "weight": 0.20,
            "desc": "上涨家数占比>50%",
        }

        # 4. 北向资金（15%）
        north_score = self._check_northbound()
        score += 1.5 * north_score
        indicators["northbound_flow"] = {
            "score": round(north_score, 2),
            "weight": 0.15,
            "desc": "北向资金净流入",
        }

        # 5. 情绪面（10%）
        sentiment_score = self._check_sentiment()
        score += 1.0 * sentiment_score
        indicators["sentiment"] = {
            "score": round(sentiment_score, 2),
            "weight": 0.10,
            "desc": "涨停家数>跌停家数",
        }

        # 确定级别
        if score >= self.thresholds["strong"]:
            level = "strong"
            max_position_pct = 0.80
        elif score >= self.thresholds["normal"]:
            level = "normal"
            max_position_pct = 0.50
        elif score >= self.thresholds["weak"]:
            level = "weak"
            max_position_pct = 0.30
        else:
            level = "closed"
            max_position_pct = 0.0

        result = {
            "score": round(score, 2),
            "level": level,
            "max_position_pct": max_position_pct,
            "max_position_desc": f"建议最大仓位 {max_position_pct*100:.0f}%",
            "indicators": indicators,
            "summary": self._build_summary(score, level, max_position_pct),
        }

        logger.info(f"大盘评估: {score:.1f}分 → {level} ({max_position_pct*100:.0f}%)")
        return result

    def _check_benchmark_trend(self) -> float:
        """检查基准指数趋势"""
        try:
            cache_key = "benchmark_kline"
            cached = cache.get(cache_key, ttl=3600)
            if cached is not None:
                kline = cached
            else:
                kline = data_source.get_index_kline(self.benchmark_code, days=250)
                if kline is not None and not kline.empty:
                    cache.set(cache_key, kline)

            if kline is None or kline.empty or len(kline) < 60:
                return 0.3  # 无数据，给中性分

            latest = kline.iloc[-1]
            ma60 = kline["close"].rolling(60).mean()
            latest_ma60 = ma60.iloc[-1]

            # 均线方向
            ma60_recent = ma60.tail(5).mean()
            ma60_prev = ma60.iloc[-10:-5].mean()
            ma60_up = ma60_recent > ma60_prev

            # 价格在均线上方
            above_ma60 = latest["close"] > latest_ma60

            score = 0.0
            if above_ma60:
                score += 0.5
            if ma60_up:
                score += 0.5

            # 额外加分：5日线 > 20日线
            ma5 = kline["close"].rolling(5).mean()
            ma20 = kline["close"].rolling(20).mean()
            if ma5.iloc[-1] > ma20.iloc[-1]:
                score += 0.2

            return min(score, 1.0)
        except Exception as e:
            logger.warning(f"基准趋势检查失败: {e}")
            return 0.3

    def _check_volume_situation(self) -> float:
        """检查成交量情况"""
        try:
            # 用沪深300成交量
            cache_key = "benchmark_kline"
            cached = cache.get(cache_key, ttl=3600)
            if cached is not None:
                kline = cached
            else:
                kline = data_source.get_index_kline(self.benchmark_code, days=250)

            if kline is None or kline.empty:
                return 0.3

            vol_5d = kline["volume"].tail(5).mean()
            vol_20d = kline["volume"].tail(20).mean()

            if vol_20d <= 0:
                return 0.3

            ratio = vol_5d / vol_20d
            if ratio > 1.2:
                return 1.0
            elif ratio > 1.0:
                return 0.7
            elif ratio > 0.8:
                return 0.4
            else:
                return 0.2
        except Exception as e:
            logger.warning(f"成交量检查失败: {e}")
            return 0.3

    def _check_breadth(self) -> float:
        """检查市场宽度（涨跌家数比）"""
        try:
            spot = cache.get("spot_all", ttl=3600)
            if spot is None:
                spot = data_source.get_spot_all()
                cache.set("spot_all", spot)

            if spot is None or spot.empty:
                return 0.3

            up_count = len(spot[spot["change_pct"] > 0])
            down_count = len(spot[spot["change_pct"] < 0])
            total = up_count + down_count

            if total == 0:
                return 0.3

            up_ratio = up_count / total
            if up_ratio > 0.6:
                return 1.0
            elif up_ratio > 0.5:
                return 0.7
            elif up_ratio > 0.4:
                return 0.4
            else:
                return 0.2
        except Exception as e:
            logger.warning(f"市场宽度检查失败: {e}")
            return 0.3

    def _check_northbound(self) -> float:
        """检查北向资金"""
        try:
            flow = data_source.get_northbound_flow()
            if not flow:
                return 0.3

            net_inflow = flow.get("net_inflow", 0)
            if net_inflow > 50e8:  # 净流入 > 50亿
                return 1.0
            elif net_inflow > 0:
                return 0.7
            elif net_inflow > -50e8:
                return 0.4
            else:
                return 0.2
        except Exception as e:
            logger.warning(f"北向资金检查失败: {e}")
            return 0.3

    def _check_sentiment(self) -> float:
        """检查市场情绪"""
        try:
            spot = cache.get("spot_all", ttl=3600)
            if spot is None:
                spot = data_source.get_spot_all()
                cache.set("spot_all", spot)

            if spot is None or spot.empty:
                return 0.3

            # 涨停家数（涨幅 > 9.8%）
            limit_up = len(spot[spot["change_pct"] > 9.8])
            # 跌停家数（跌幅 < -9.8%）
            limit_down = len(spot[spot["change_pct"] < -9.8])

            if limit_up > limit_down * 3:
                return 1.0
            elif limit_up > limit_down:
                return 0.7
            elif limit_up > limit_down * 0.5:
                return 0.4
            else:
                return 0.2
        except Exception as e:
            logger.warning(f"情绪面检查失败: {e}")
            return 0.3

    def _build_summary(self, score: float, level: str, max_pct: float) -> str:
        """生成文字摘要"""
        level_desc = {
            "strong": "强势",
            "normal": "正常",
            "weak": "偏弱",
            "closed": "极弱",
        }
        return f"大盘环境：{level_desc.get(level, '未知')}（{score:.1f}分），建议仓位≤{max_pct*100:.0f}%"


# 全局实例
market_gate = MarketGate()
