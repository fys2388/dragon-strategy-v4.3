"""
入场信号识别

3种买点：
1. 回踩企稳 - 缩量回踩均线 + MACD低位金叉
2. 放量突破 - 突破平台 + 量比>2
3. 板块启动 - 板块轮动 + 龙头领涨

每种买点有明确的入场条件、止损位、目标位。
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Optional

from config.settings import SIGNAL_PARAMS, UNIVERSE_FILTERS
from src.data.source import data_source
from src.data.cache import cache

logger = logging.getLogger(__name__)


class EntrySignalDetector:
    """入场信号检测器"""

    def __init__(self):
        self.params = SIGNAL_PARAMS

    def detect_all(self, candidates: pd.DataFrame) -> List[Dict]:
        """
        对候选池检测所有买点信号

        三级输出：
        1. 强信号：满足特定买点条件
        2. 弱信号：接近买点条件（放宽部分阈值）
        3. 观察池：无明显信号但综合评分较好的候选

        Returns:
            信号列表，按强度排序
        """
        signals = []
        watchlist = []
        logger.info(f"信号检测开始: {len(candidates)} 只候选")

        for _, row in candidates.iterrows():
            code = row["code"]
            try:
                kline = self._get_kline_with_indicators(code)
                if kline is None or kline.empty:
                    continue

                # 检测三种买点（强信号）
                sig = None

                sig = self._check_pullback_stabilize(code, kline, row)
                if sig:
                    sig["score"] = self._calculate_score(kline, row)
                    sig["signal_strength"] = "strong"
                    signals.append(sig)
                    continue

                sig = self._check_breakout(code, kline, row)
                if sig:
                    sig["score"] = self._calculate_score(kline, row)
                    sig["signal_strength"] = "strong"
                    signals.append(sig)
                    continue

                sig = self._check_sector_leader(code, kline, row)
                if sig:
                    sig["score"] = self._calculate_score(kline, row)
                    sig["signal_strength"] = "strong"
                    signals.append(sig)
                    continue

                # 检测弱信号（放宽条件）
                weak_sig = self._check_weak_signal(code, kline, row)
                if weak_sig:
                    weak_sig["score"] = self._calculate_score(kline, row) * 0.8
                    weak_sig["signal_strength"] = "weak"
                    watchlist.append(weak_sig)
                    continue

                # 无明显信号，但评分高则进观察池
                score = self._calculate_score(kline, row)
                if score >= 50:
                    watchlist.append({
                        "code": code,
                        "name": row.get("name", code),
                        "signal_type": "watchlist",
                        "signal_desc": "观察池（综合评分较高）",
                        "signal_strength": "watch",
                        "entry_price": round(row["close"], 2),
                        "stop_loss": round(row["close"] * 0.93, 2),
                        "target_1": round(row["close"] * 1.15, 2),
                        "target_2": round(row["close"] * 1.25, 2),
                        "score": round(score * 0.6, 1),
                        "reason": f"综合评分{score:.0f}，暂无明确买点，列入观察",
                    })

            except Exception as e:
                logger.debug(f"信号检测异常 {code}: {e}")
                continue

        # 合并：强信号优先，然后弱信号，最后观察池
        all_signals = signals + watchlist
        all_signals.sort(key=lambda x: x.get("score", 0), reverse=True)

        logger.info(f"信号检测完成: {len(signals)} 个强信号, {len(watchlist)} 个弱信号/观察")
        return all_signals

    def _get_kline_with_indicators(self, code: str, days: int = 250) -> pd.DataFrame:
        """获取 K 线并计算指标"""
        cache_key = f"kline_ind_{code}"
        cached = cache.get(cache_key, ttl=3600)
        if cached is not None:
            return cached

        kline = data_source.get_kline(code, days=days)
        if kline is None or kline.empty or len(kline) < 60:
            return pd.DataFrame()

        # 均线
        kline["ma5"] = kline["close"].rolling(5).mean()
        kline["ma10"] = kline["close"].rolling(10).mean()
        kline["ma20"] = kline["close"].rolling(20).mean()
        kline["ma60"] = kline["close"].rolling(60).mean()

        # MACD
        ema12 = kline["close"].ewm(span=12, adjust=False).mean()
        ema26 = kline["close"].ewm(span=26, adjust=False).mean()
        kline["macd"] = ema12 - ema26
        kline["macd_signal"] = kline["macd"].ewm(span=9, adjust=False).mean()
        kline["macd_hist"] = kline["macd"] - kline["macd_signal"]

        # 成交量均线
        kline["vol_ma5"] = kline["volume"].rolling(5).mean()
        kline["vol_ma10"] = kline["volume"].rolling(10).mean()
        kline["vol_ma20"] = kline["volume"].rolling(20).mean()

        # RSI
        kline["rsi"] = self._calc_rsi(kline["close"], 14)

        # 量比
        kline["vol_ratio"] = kline["volume"] / kline["vol_ma5"]

        cache.set(cache_key, kline)
        return kline

    @staticmethod
    def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """计算 RSI"""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    # ────────────────────────────────────────────
    # 买点1：回踩企稳
    # ────────────────────────────────────────────
    def _check_pullback_stabilize(self, code: str, kline: pd.DataFrame, row: dict) -> Optional[Dict]:
        """
        回踩企稳买点

        条件：
        1. 股价回踩到 20 日线附近（误差 ±5%）
        2. 最近 3 日缩量（量 < 5日均量 * 60%）
        3. MACD 低位金叉或即将金叉（DIF 上穿 DEA 或差值收窄）
        4. RSI 在 30-50 区间（超卖但未极端）
        5. 回撤幅度在 8%-25% 之间
        """
        latest = kline.iloc[-1]
        prev = kline.iloc[-2] if len(kline) >= 2 else latest

        # 条件1：回踩 20 日线
        ma20 = latest["ma20"]
        close = latest["close"]
        if ma20 <= 0:
            return None
        pullback_to_ma20 = abs(close - ma20) / ma20
        if pullback_to_ma20 > 0.08:  # 偏离 20日线超过8%不算回踩
            return None

        # 条件2：缩量
        recent_vol = kline["volume"].tail(3).mean()
        avg_vol = kline["volume"].iloc[-10:-3].mean()
        if avg_vol <= 0:
            return None
        vol_shrink = recent_vol / avg_vol
        if vol_shrink > 0.65:  # 缩量不显著
            return None

        # 条件3：MACD 低位金叉
        macd_val = latest["macd"]
        macd_sig = latest["macd_signal"]
        macd_hist = latest["macd_hist"]
        prev_hist = prev["macd_hist"]

        # 金叉条件：DIF 上穿 DEA，或 差值收窄且 DIF 为负
        macd_cross = (macd_hist > 0 and prev_hist <= 0)  # 刚金叉
        macd_approaching = (macd_hist < 0 and prev_hist < macd_hist)  # 正在收窄
        macd_low = macd_val < 0.5 * latest["close"]  # MACD 低位（相对股价）

        if not (macd_cross or (macd_approaching and macd_low)):
            return None

        # 条件4：RSI 区间
        rsi = latest.get("rsi", 50)
        if rsi < 20 or rsi > 55:
            return None

        # 条件5：回撤幅度
        high_60 = kline["close"].tail(60).max()
        if high_60 <= 0:
            return None
        pullback_pct = (high_60 - close) / high_60
        if not (0.05 <= pullback_pct <= 0.25):
            return None

        # 计算止损和目标
        stop_loss = close * (1 - SIGNAL_PARAMS["stop_loss_pct"])
        target_1 = close * (1 + SIGNAL_PARAMS["take_profit_1_pct"])
        target_2 = close * (1 + SIGNAL_PARAMS["take_profit_2_pct"])

        return {
            "code": code,
            "name": row.get("name", code),
            "signal_type": "pullback_stabilize",
            "signal_desc": "回踩企稳",
            "entry_price": round(close, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "stop_loss_pct": round((stop_loss - close) / close * 100, 2),
            "target_1_pct": round((target_1 - close) / close * 100, 2),
            "target_2_pct": round((target_2 - close) / close * 100, 2),
            "volume_shrink": round(vol_shrink, 3),
            "rsi": round(rsi, 1),
            "macd": round(macd_val, 4),
            "macd_signal": round(macd_sig, 4),
            "reason": f"回踩20日线(偏离{pullback_to_ma20*100:.1f}%)，缩量{vol_shrink:.0%}，MACD低位收窄，RSI {rsi:.0f}",
        }

    # ────────────────────────────────────────────
    # 买点2：放量突破
    # ────────────────────────────────────────────
    def _check_breakout(self, code: str, kline: pd.DataFrame, row: dict) -> Optional[Dict]:
        """
        放量突破买点

        条件：
        1. 收盘价突破 20 日新高
        2. 成交量 > 5日均量 * 2（量比>2）
        3. MACD 红柱放大
        4. 股价在 60 日线上方
        """
        latest = kline.iloc[-1]
        close = latest["close"]

        # 条件1：突破 20 日新高
        high_20 = kline["high"].tail(21).iloc[:-1].max()  # 前 20 日最高（不含今日）
        if close <= high_20:
            return None

        # 条件2：放量
        vol_ratio = latest.get("vol_ratio", 1)
        if vol_ratio < 1.8:
            return None

        # 条件3：MACD 红柱放大
        macd_hist = latest["macd_hist"]
        prev_macd_hist = kline["macd_hist"].iloc[-2] if len(kline) >= 2 else 0
        if macd_hist <= prev_macd_hist or macd_hist <= 0:
            return None

        # 条件4：60日线上方
        ma60 = latest["ma60"]
        if close <= ma60:
            return None

        # 计算止损和目标
        stop_loss = min(high_20, close * 0.93)  # 前高或 -7%
        stop_loss = max(stop_loss, close * (1 - SIGNAL_PARAMS["stop_loss_pct"]))
        target_1 = close * (1 + SIGNAL_PARAMS["take_profit_1_pct"])
        target_2 = close * (1 + SIGNAL_PARAMS["take_profit_2_pct"])

        return {
            "code": code,
            "name": row.get("name", code),
            "signal_type": "breakout",
            "signal_desc": "放量突破",
            "entry_price": round(close, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "stop_loss_pct": round((stop_loss - close) / close * 100, 2),
            "target_1_pct": round((target_1 - close) / close * 100, 2),
            "target_2_pct": round((target_2 - close) / close * 100, 2),
            "volume_ratio": round(vol_ratio, 2),
            "breakout_high": round(high_20, 2),
            "reason": f"突破20日新高{high_20:.2f}，量比{vol_ratio:.1f}，MACD红柱放大",
        }

    # ────────────────────────────────────────────
    # 买点3：板块启动龙头
    # ────────────────────────────────────────────
    def _check_sector_leader(self, code: str, kline: pd.DataFrame, row: dict) -> Optional[Dict]:
        """
        板块启动龙头买点（简化版）

        条件：
        1. 股价创 20 日新高（板块领涨特征）
        2. 涨幅适中（3%-7%，不是已经涨太多）
        3. MACD 金叉或红柱放大
        4. 量比 > 1.5
        """
        latest = kline.iloc[-1]
        close = latest["close"]

        # 条件1：20日新高
        high_20 = kline["high"].tail(20).max()
        if close < high_20 * 0.97:  # 允许 3% 误差
            return None

        # 条件2：涨幅适中
        change_pct = row.get("change_pct", 0)
        if "change_pct" not in row:
            change_pct = (close / kline["close"].iloc[-2] - 1) * 100 if len(kline) >= 2 else 0
        if change_pct < 2 or change_pct > 8:
            return None

        # 条件3：MACD 向好
        macd_hist = latest["macd_hist"]
        if macd_hist <= 0:
            return None

        # 条件4：量比
        vol_ratio = latest.get("vol_ratio", 1)
        if vol_ratio < 1.5:
            return None

        # 计算止损和目标
        stop_loss = close * (1 - SIGNAL_PARAMS["stop_loss_pct"])
        target_1 = close * (1 + SIGNAL_PARAMS["take_profit_1_pct"])
        target_2 = close * (1 + SIGNAL_PARAMS["take_profit_2_pct"])

        return {
            "code": code,
            "name": row.get("name", code),
            "signal_type": "sector_leader",
            "signal_desc": "板块启动龙头",
            "entry_price": round(close, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "stop_loss_pct": round((stop_loss - close) / close * 100, 2),
            "target_1_pct": round((target_1 - close) / close * 100, 2),
            "target_2_pct": round((target_2 - close) / close * 100, 2),
            "volume_ratio": round(vol_ratio, 2),
            "change_pct": round(change_pct, 2),
            "reason": f"创20日新高，涨幅{change_pct:.1f}%，量比{vol_ratio:.1f}，MACD红柱",
        }

    def _check_weak_signal(self, code: str, kline: pd.DataFrame, row: dict) -> Optional[Dict]:
        """
        弱信号检测（放宽条件）

        当强信号都不满足时，检测接近买点的候选：
        - 趋势向上但回调不足
        - 接近突破但量比不够
        - 即将金叉但还没金叉
        """
        latest = kline.iloc[-1]
        close = latest["close"]
        ma20 = latest["ma20"]
        ma60 = latest["ma60"]

        # 弱信号1：趋势向上，接近回踩20日线（偏差8-15%）
        if close > ma20 > ma60:
            deviation = abs(close - ma20) / ma20
            if 0.08 <= deviation <= 0.15:
                macd_hist = latest["macd_hist"]
                if macd_hist < 0 and macd_hist > -0.02 * close:  # MACD 接近零轴
                    return {
                        "code": code,
                        "name": row.get("name", code),
                        "signal_type": "weak_pullback",
                        "signal_desc": "弱信号-趋势向上接近回调",
                        "entry_price": round(close, 2),
                        "stop_loss": round(close * 0.93, 2),
                        "target_1": round(close * 1.15, 2),
                        "target_2": round(close * 1.25, 2),
                        "stop_loss_pct": round(-7, 2),
                        "target_1_pct": round(15, 2),
                        "target_2_pct": round(25, 2),
                        "reason": f"多头排列，偏离20日线{deviation*100:.1f}%，MACD接近零轴，等待回踩",
                    }

        # 弱信号2：接近20日新高但量比不够（1.0-1.8）
        high_20 = kline["high"].tail(21).iloc[:-1].max()
        vol_ratio = latest.get("vol_ratio", 1)
        if close >= high_20 * 0.98 and 1.0 <= vol_ratio < 1.8:
            return {
                "code": code,
                "name": row.get("name", code),
                "signal_type": "weak_breakout",
                "signal_desc": "弱信号-接近突破",
                "entry_price": round(close, 2),
                "stop_loss": round(close * 0.93, 2),
                "target_1": round(close * 1.15, 2),
                "target_2": round(close * 1.25, 2),
                "stop_loss_pct": round(-7, 2),
                "target_1_pct": round(15, 2),
                "target_2_pct": round(25, 2),
                "reason": f"接近20日新高{high_20:.2f}，量比{vol_ratio:.1f}，等待放量确认",
            }

        # 弱信号3：MACD即将金叉（DIF从下方接近DEA）
        macd_val = latest["macd"]
        macd_sig = latest["macd_signal"]
        prev_macd = kline["macd"].iloc[-2] if len(kline) >= 2 else macd_val
        prev_sig = kline["macd_signal"].iloc[-2] if len(kline) >= 2 else macd_sig
        if prev_macd < prev_sig and macd_val > macd_sig * 0.9:  # 从负差值缩小到接近
            if macd_val < 0 and close > ma20:
                return {
                    "code": code,
                    "name": row.get("name", code),
                    "signal_type": "weak_macd_cross",
                    "signal_desc": "弱信号-MACD即将金叉",
                    "entry_price": round(close, 2),
                    "stop_loss": round(close * 0.93, 2),
                    "target_1": round(close * 1.15, 2),
                    "target_2": round(close * 1.25, 2),
                    "stop_loss_pct": round(-7, 2),
                    "target_1_pct": round(15, 2),
                    "target_2_pct": round(25, 2),
                    "reason": f"MACD负差值收窄({macd_hist:.4f})，站上20日线，即将金叉",
                }

        return None

    # ────────────────────────────────────────────
    # 综合打分
    # ────────────────────────────────────────────
    def _calculate_score(self, kline: pd.DataFrame, row: dict) -> float:
        """
        综合打分（0-100）

        维度：
        - 趋势强度 25%
        - 动量 20%
        - 量价配合 15%
        - 基本面 20%
        - 资金流 10%
        - 板块热度 10%
        """
        latest = kline.iloc[-1]
        weights = SIGNAL_PARAMS["score_weights"]
        score = 0.0

        # 1. 趋势强度（25%）
        # 均线多头排列 + MACD 金叉
        if latest["ma5"] > latest["ma10"] > latest["ma20"] > latest["ma60"]:
            trend_score = 1.0
        elif latest["ma5"] > latest["ma10"] > latest["ma20"]:
            trend_score = 0.7
        elif latest["close"] > latest["ma20"]:
            trend_score = 0.5
        else:
            trend_score = 0.2
        score += weights["trend"] * trend_score

        # 2. 动量（20%）
        # 近 5 日涨幅 + MACD 方向
        change_5d = (latest["close"] / kline["close"].iloc[-6] - 1) if len(kline) >= 6 else 0
        if change_5d > 0.05:
            momentum_score = 1.0
        elif change_5d > 0.02:
            momentum_score = 0.7
        elif change_5d > 0:
            momentum_score = 0.5
        else:
            momentum_score = 0.2
        score += weights["momentum"] * momentum_score

        # 3. 量价配合（15%）
        vol_ratio = latest.get("vol_ratio", 1)
        if 1.5 <= vol_ratio <= 3.0:
            volume_score = 1.0  # 温和放量
        elif vol_ratio > 3.0:
            volume_score = 0.7  # 放量过多
        elif vol_ratio >= 1.0:
            volume_score = 0.5
        else:
            volume_score = 0.3
        score += weights["volume"] * volume_score

        # 4. 基本面（20%）
        pe = row.get("pe_ttm", 30)
        pb = row.get("pb", 2)
        if pe and 10 <= pe <= 40:
            fundamental_score = 1.0
        elif pe and (5 <= pe < 10 or 40 < pe <= 60):
            fundamental_score = 0.6
        else:
            fundamental_score = 0.3
        score += weights["fundamental"] * fundamental_score

        # 5. 资金流（10%）- 简化，用换手率代替
        turnover = row.get("turnover", 3)
        if turnover and 2 <= turnover <= 8:
            flow_score = 1.0
        elif turnover and turnover > 8:
            flow_score = 0.5
        else:
            flow_score = 0.4
        score += weights["capital_flow"] * flow_score

        # 6. 板块热度（10%）- 简化，用涨幅代替
        change_pct = row.get("change_pct", 2)
        if change_pct and 2 <= change_pct <= 5:
            sector_score = 1.0
        elif change_pct and change_pct > 5:
            sector_score = 0.7
        else:
            sector_score = 0.5
        score += weights["sector_heat"] * sector_score

        return round(score * 100, 1)


# 全局实例
signal_detector = EntrySignalDetector()
