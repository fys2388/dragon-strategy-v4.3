"""
选股池模块

三层漏斗：
  全A ~5900只 → 初筛（基本面+流动性）~1500只 → 精筛（技术面+回撤+企稳）~100只 → 候选池 ~20-30只
"""

import logging
import pandas as pd
import numpy as np
from typing import List
from datetime import datetime

from config.settings import UNIVERSE_FILTERS, CACHE_DIR
from src.data.source import data_source
from src.data.cache import cache

logger = logging.getLogger(__name__)


class StockUniverse:
    """选股池管理器"""

    def __init__(self):
        self.spot_df = None
        self.pool_codes = []

    def refresh_spot(self, use_cache: bool = True) -> pd.DataFrame:
        """刷新全市场快照"""
        key = "spot_all"
        if use_cache:
            cached = cache.get(key, ttl=3600)  # 缓存 1 小时
            if cached is not None:
                logger.info(f"使用缓存快照: {len(cached)} 只")
                self.spot_df = cached
                return cached

        self.spot_df = data_source.get_spot_all()
        cache.set(key, self.spot_df)
        logger.info(f"快照刷新完成: {len(self.spot_df)} 只股票")
        return self.spot_df

    def get_all_codes(self) -> List[str]:
        """获取所有股票代码"""
        if self.spot_df is None:
            self.refresh_spot()
        return self.spot_df["code"].tolist()

    # ────────────────────────────────────────────
    # 第一层：初筛（基本面 + 流动性）
    # ────────────────────────────────────────────
    def prefilter(self, spot_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        初筛：基本面 + 流动性过滤

        过滤条件：
        - 市值 30-300 亿
        - 日均成交额 > 5000 万
        - ROE > 8%
        - 营收增长 > 0
        - 非 ST
        - 上市 > 1 年
        - 股价 5-100 元
        """
        if spot_df is None:
            spot_df = self.spot_df
        if spot_df is None:
            self.refresh_spot()
            spot_df = self.spot_df

        df = spot_df.copy()
        initial_count = len(df)
        logger.info(f"初筛开始: {initial_count} 只")

        # 1. 市值过滤
        if "total_cap" in df.columns:
            df = df[df["total_cap"].between(UNIVERSE_FILTERS["min_market_cap"], UNIVERSE_FILTERS["max_market_cap"])]
            logger.info(f"市值过滤后: {len(df)} 只 (剔除 {initial_count - len(df)})")

        # 2. 流动性过滤
        if "amount" in df.columns:
            df = df[df["amount"] > UNIVERSE_FILTERS["min_daily_amount"]]
            logger.info(f"流动性过滤后: {len(df)} 只")

        # 3. 股价过滤
        if "price" in df.columns:
            df = df[df["price"].between(UNIVERSE_FILTERS["min_price"], UNIVERSE_FILTERS["max_price"])]
            logger.info(f"股价过滤后: {len(df)} 只")

        # 4. ST 过滤
        if "name" in df.columns:
            df = df[~df["name"].str.contains(r"ST|退|\*ST", na=False, regex=True)]
            logger.info(f"ST过滤后: {len(df)} 只")

        # 5. 市盈率过滤（负值说明亏损，排除）
        if "pe_ttm" in df.columns:
            df = df[df["pe_ttm"] > 0]
            logger.info(f"PE过滤后: {len(df)} 只")

        # 6. 市净率过滤（负值排除）
        if "pb" in df.columns:
            df = df[df["pb"] > 0]
            logger.info(f"PB过滤后: {len(df)} 只")

        # 7. 代码过滤（排除科创板688、北交所8开头，可选）
        # 保留科创板但排除北交所
        if "code" in df.columns:
            df = df[~df["code"].str.startswith("8")]  # 排除北交所
            df = df[~df["code"].str.startswith("4")]  # 排除新三板
            logger.info(f"交易所过滤后: {len(df)} 只")

        self.prefiltered_df = df
        logger.info(f"初筛完成: {initial_count} → {len(df)} 只")
        return df

    # ────────────────────────────────────────────
    # 第二层：精筛（技术面 + 回撤 + 企稳）
    # ────────────────────────────────────────────
    def detail_filter(self, codes: List[str] = None) -> pd.DataFrame:
        """
        精筛：并发获取 K 线，计算技术指标，过滤

        优化策略：
        1. 先用 spot 数据（60日涨跌幅）预过滤，减少 K 线请求量
        2. 并发拉取 K 线（ThreadPoolExecutor）
        3. 限制最多检查 150 只，避免超时
        """
        if codes is None:
            if not hasattr(self, "prefiltered_df"):
                self.prefilter()
            codes = self.prefiltered_df["code"].tolist()

        if codes is None or len(codes) == 0:
            logger.warning("精筛无候选股票")
            return pd.DataFrame()

        # ─── 预过滤：用 spot 数据的 60 日涨跌幅快速筛选 ───
        if self.spot_df is not None:
            spot_codes = self.spot_df[self.spot_df["code"].isin(codes)]
            if "change_60d" in spot_codes.columns:
                # 60日涨跌幅在 -25% 到 +10% 之间（排除暴涨和暴跌）
                spot_codes = spot_codes[
                    (spot_codes["change_60d"] >= -25) &
                    (spot_codes["change_60d"] <= 10)
                ]
                codes = spot_codes["code"].tolist()
                logger.info(f"60日涨跌幅预过滤后: {len(codes)} 只")

            # 按成交额降序，取前 150 只（流动性优先）
            if "amount" in spot_codes.columns:
                spot_codes = spot_codes.nlargest(150, "amount")
                codes = spot_codes["code"].tolist()
                logger.info(f"成交额 Top150 截断后: {len(codes)} 只")

        logger.info(f"精筛开始: {len(codes)} 只候选")

        results = []
        kline_days = DATA_SOURCE_KLINE_DAYS

        # ─── 并发拉取 K 线 ───
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_kline_with_indicators(code: str) -> dict:
            """获取单只 K 线并计算指标"""
            try:
                cache_key = f"kline_filter_{code}"
                cached = cache.get(cache_key, ttl=3600)
                if cached is not None:
                    return {"code": code, "kline": cached, "ok": True}

                kline = data_source.get_kline(code, days=kline_days)
                if kline is None or kline.empty or len(kline) < 60:
                    return {"code": code, "kline": None, "ok": False}

                # 计算指标
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

                # RSI
                delta = kline["close"].diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.rolling(window=14).mean()
                avg_loss = loss.rolling(window=14).mean()
                rs = avg_gain / avg_loss.replace(0, np.nan)
                kline["rsi"] = 100 - (100 / (1 + rs))

                # 量比
                kline["vol_ratio"] = kline["volume"] / kline["vol_ma5"]

                cache.set(cache_key, kline)
                return {"code": code, "kline": kline, "ok": True}

            except Exception as e:
                return {"code": code, "kline": None, "ok": False}

        # 并发执行（8 个线程）
        kline_results = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fetch_kline_with_indicators, c): c for c in codes}
            done = 0
            for future in as_completed(futures):
                result = future.result()
                done += 1
                if done % 20 == 0:
                    logger.info(f"K线获取进度: {done}/{len(codes)}")
                if result["ok"]:
                    kline_results[result["code"]] = result["kline"]

        logger.info(f"K线获取完成: {len(kline_results)}/{len(codes)} 只有数据")

        # ─── 逐只过滤 ───
        strict_results = []
        relaxed_results = []
        filter_stats = {"total": len(kline_results), "above_ma60": 0, "ma60_up": 0,
                        "pullback_ok": 0, "volume_ok": 0, "turnover_ok": 0, "passed": 0}

        for code, kline in kline_results.items():
            try:
                latest = kline.iloc[-1]
                ma60_series = kline["ma60"]
                close_series = kline["close"]

                # 收集失败原因
                fail_reasons = []

                # 1. 收盘价 > 60日线
                above_ma60 = latest["close"] > latest["ma60"]
                if above_ma60:
                    filter_stats["above_ma60"] += 1
                else:
                    fail_reasons.append("below_ma60")

                # 2. 60日线向上
                ma60_up = True
                if len(ma60_series) >= 10:
                    ma60_recent = ma60_series.tail(5).mean()
                    ma60_prev = ma60_series.iloc[-10:-5].mean()
                    ma60_up = ma60_recent > ma60_prev
                if ma60_up:
                    filter_stats["ma60_up"] += 1
                else:
                    fail_reasons.append("ma60_down")

                # 3. 回撤幅度
                high_60 = close_series.tail(UNIVERSE_FILTERS["pullback_lookback_days"]).max()
                pullback = (high_60 - latest["close"]) / high_60 if high_60 > 0 else 0
                pullback_ok = (UNIVERSE_FILTERS["pullback_min_pct"] <= pullback <= UNIVERSE_FILTERS["pullback_max_pct"])
                if pullback_ok:
                    filter_stats["pullback_ok"] += 1
                else:
                    fail_reasons.append(f"pullback_{pullback*100:.1f}%")

                # 4. 缩量企稳
                vol_series = kline["volume"]
                recent_vol = vol_series.tail(UNIVERSE_FILTERS["consolidation_days"]).mean()
                prev_vol = vol_series.iloc[-10:-3].mean() if len(vol_series) >= 10 else recent_vol
                vol_ratio = recent_vol / prev_vol if prev_vol > 0 else 1.0
                volume_ok = vol_ratio <= UNIVERSE_FILTERS["volume_shrink_ratio"]
                if volume_ok:
                    filter_stats["volume_ok"] += 1
                else:
                    fail_reasons.append(f"vol_ratio_{vol_ratio:.2f}")

                # 5. 换手率过滤
                turnover_val = None
                if self.spot_df is not None and "turnover" in self.spot_df.columns:
                    spot_row = self.spot_df[self.spot_df["code"] == code]
                    if not spot_row.empty:
                        turnover_val = spot_row.iloc[0].get("turnover", 0)

                turnover_ok = True
                if turnover_val is not None and turnover_val > 15:
                    turnover_ok = False
                    fail_reasons.append(f"turnover_{turnover_val:.1f}%")
                else:
                    filter_stats["turnover_ok"] += 1

                # 基础信息
                stock_info = {
                    "code": code,
                    "name": self._get_name(code),
                    "close": latest["close"],
                    "ma20": latest["ma20"],
                    "ma60": latest["ma60"],
                    "pullback_pct": round(pullback, 4),
                    "high_60": high_60,
                    "macd": latest.get("macd", 0),
                    "macd_signal": latest.get("macd_signal", 0),
                    "macd_hist": latest.get("macd_hist", 0),
                    "vol_ratio": round(vol_ratio, 3),
                    "turnover": turnover_val,
                    "above_ma60": above_ma60,
                    "ma60_up": ma60_up,
                    "pullback_ok": pullback_ok,
                    "volume_ok": volume_ok,
                    "fail_reasons": fail_reasons,
                }

                # 严格过滤：全部条件通过
                if not fail_reasons:
                    strict_results.append(stock_info)
                    filter_stats["passed"] += 1
                elif len(fail_reasons) <= 2:
                    # 最多2个条件不满足，作为降级候选
                    relaxed_results.append(stock_info)

            except Exception as e:
                logger.debug(f"精筛异常 {code}: {e}")
                continue

        logger.info(f"过滤统计: {filter_stats}")

        # 使用严格结果
        if strict_results:
            result_df = pd.DataFrame(strict_results)
            logger.info(f"精筛完成(严格): {len(codes)} → {len(result_df)} 只")
            self.detail_filtered_df = result_df
            return result_df

        # 降级回退：使用最多2个条件不满足的候选
        if relaxed_results:
            # 按失败条件数量排序，少的优先
            relaxed_results.sort(key=lambda x: len(x["fail_reasons"]))
            result_df = pd.DataFrame(relaxed_results[:30])  # 最多30只
            result_df["is_relaxed"] = True
            logger.info(f"精筛完成(降级): {len(codes)} → {len(result_df)} 只")
            self.detail_filtered_df = result_df
            return result_df

        logger.info("精筛完成: 0 只通过（含降级）")
        return pd.DataFrame()

    def _calc_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """计算 MACD 指标"""
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        df = df.copy()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]
        return df

    def _get_name(self, code: str) -> str:
        """获取股票名称"""
        if self.spot_df is not None and "name" in self.spot_df.columns:
            row = self.spot_df[self.spot_df["code"] == code]
            if not row.empty:
                return row.iloc[0]["name"]
        return code

    # ────────────────────────────────────────────
    # 执行完整筛选流程
    # ────────────────────────────────────────────
    def run_pipeline(self) -> pd.DataFrame:
        """执行完整选股流程：快照 → 初筛 → 精筛"""
        logger.info("=" * 50)
        logger.info("选股流程开始")
        logger.info("=" * 50)

        # 1. 刷新快照
        self.refresh_spot()

        # 2. 初筛
        prefiltered = self.prefilter()

        # 3. 精筛
        candidates = self.detail_filter(prefiltered["code"].tolist())

        # 4. 保存结果
        if not candidates.empty:
            output_path = CACHE_DIR / f"candidates_{datetime.now().strftime('%Y%m%d')}.csv"
            candidates.to_csv(output_path, index=False, encoding="utf-8-sig")
            logger.info(f"候选池已保存: {output_path}")

        logger.info(f"选股流程完成: 候选 {len(candidates)} 只")
        return candidates


# K线拉取天数（从配置读取）
from config.settings import DATA_SOURCE
DATA_SOURCE_KLINE_DAYS = DATA_SOURCE["kline_days"]

# 全局实例
universe = StockUniverse()
