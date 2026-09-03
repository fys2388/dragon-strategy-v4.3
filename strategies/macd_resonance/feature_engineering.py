# -*- coding: utf-8 -*-
"""特征工程模块。

为AI预测模型计算20+技术特征：
1. 价格特征：收益率、波动率、振幅
2. 均线特征：MA偏离度、均线斜率
3. MACD特征：DIF、DEA、柱状图、金叉
4. RSI特征：RSI6/12/24
5. 布林带特征：位置、带宽
6. 成交量特征：量比、成交量变化率
7. 资金流特征：主力净流入、连续流入
8. 趋势特征：新高/新低、连涨连跌

标签：未来5日涨幅>3%为正样本
"""
from __future__ import annotations

import os
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def calc_ma(series: pd.Series, period: int) -> pd.Series:
    """计算移动平均线。"""
    return series.rolling(window=period, min_periods=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """计算指数移动平均线。"""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """计算RSI。"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """计算MACD。"""
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = (dif - dea) * 2
    return dif, dea, macd_hist


def calc_bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """计算布林带。"""
    mid = calc_ma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def build_features(df: pd.DataFrame, moneyflow_df: pd.DataFrame = None) -> pd.DataFrame:
    """从K线数据构建特征。

    Args:
        df: K线数据，需含 open/high/low/close/volume
        moneyflow_df: 资金流数据（可选）

    Returns:
        含特征的DataFrame
    """
    if df.empty or len(df) < 30:
        return pd.DataFrame()

    data = df.copy()
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    features = pd.DataFrame(index=data.index)

    # ===== 1. 价格特征 =====
    features["return_1d"] = close.pct_change(1) * 100
    features["return_3d"] = close.pct_change(3) * 100
    features["return_5d"] = close.pct_change(5) * 100
    features["return_10d"] = close.pct_change(10) * 100
    features["volatility_5d"] = close.pct_change().rolling(5).std() * 100
    features["volatility_10d"] = close.pct_change().rolling(10).std() * 100
    features["amplitude_5d"] = ((high.rolling(5).max() - low.rolling(5).min()) / close.rolling(5).mean() * 100)
    features["amplitude_20d"] = ((high.rolling(20).max() - low.rolling(20).min()) / close.rolling(20).mean() * 100)

    # ===== 2. 均线特征 =====
    ma5 = calc_ma(close, 5)
    ma10 = calc_ma(close, 10)
    ma20 = calc_ma(close, 20)
    features["ma5_deviation"] = (close - ma5) / ma5 * 100
    features["ma10_deviation"] = (close - ma10) / ma10 * 100
    features["ma20_deviation"] = (close - ma20) / ma20 * 100
    features["ma5_slope"] = (ma5 - ma5.shift(3)) / ma5.shift(3) * 100
    features["ma10_slope"] = (ma10 - ma10.shift(3)) / ma10.shift(3) * 100
    features["ma_bullish"] = ((ma5 > ma10) & (ma10 > ma20)).astype(int)

    # ===== 3. MACD特征 =====
    dif, dea, macd_hist = calc_macd(close)
    features["macd_dif"] = dif
    features["macd_dea"] = dea
    features["macd_hist"] = macd_hist
    features["macd_golden_cross"] = ((dif > dea) & (dif.shift(1) <= dea.shift(1))).astype(int)
    features["macd_above_zero"] = (dif > 0).astype(int)

    # ===== 4. RSI特征 =====
    features["rsi_6"] = calc_rsi(close, 6)
    features["rsi_12"] = calc_rsi(close, 12)
    features["rsi_24"] = calc_rsi(close, 24)
    features["rsi_overbought"] = (features["rsi_6"] > 80).astype(int)
    features["rsi_oversold"] = (features["rsi_6"] < 20).astype(int)

    # ===== 5. 布林带特征 =====
    boll_upper, boll_mid, boll_lower = calc_bollinger(close)
    features["boll_position"] = (close - boll_lower) / (boll_upper - boll_lower).replace(0, np.nan)
    features["boll_width"] = (boll_upper - boll_lower) / boll_mid * 100
    features["boll_break_upper"] = (close > boll_upper).astype(int)
    features["boll_break_lower"] = (close < boll_lower).astype(int)

    # ===== 6. 成交量特征 =====
    features["volume_ratio_5d"] = volume / volume.rolling(5).mean()
    features["volume_change_1d"] = volume.pct_change(1) * 100
    features["volume_trend"] = (volume.rolling(5).mean() - volume.rolling(10).mean()) / volume.rolling(10).mean() * 100
    features["price_volume_divergence"] = ((close.pct_change(5) > 0) & (volume.pct_change(5) < 0)).astype(int)

    # ===== 7. 趋势特征 =====
    features["new_high_20d"] = (close >= close.rolling(20).max()).astype(int)
    features["new_low_20d"] = (close <= close.rolling(20).min()).astype(int)
    features["consecutive_up"] = close.groupby((close < close.shift()).cumsum()).cumcount() + 1
    features["consecutive_down"] = close.groupby((close > close.shift()).cumsum()).cumcount() + 1

    # ===== 8. 资金流特征（如果有） =====
    if moneyflow_df is not None and not moneyflow_df.empty:
        try:
            mf = moneyflow_df.set_index("date")
            features["main_net_inflow"] = mf["main_net_inflow"].reindex(features.index).fillna(0)
            features["main_net_inflow_pct"] = mf["main_net_inflow_pct"].reindex(features.index).fillna(0)
            # 连续流入天数
            inflow_positive = (features["main_net_inflow"] > 0).astype(int)
            features["consecutive_inflow"] = inflow_positive.groupby((inflow_positive == 0).cumsum()).cumcount()
        except Exception:
            pass

    # 清理inf和nan
    features = features.replace([np.inf, -np.inf], np.nan)

    return features


def build_label(df: pd.DataFrame, forward_days: int = 5, threshold: float = 3.0) -> pd.Series:
    """构建标签：未来forward_days日涨幅>threshold%为1，否则为0。

    Args:
        df: K线数据
        forward_days: 预测未来几天
        threshold: 涨幅阈值（%）

    Returns:
        标签Series（1=上涨，0=不涨）
    """
    close = df["close"].astype(float)
    future_return = close.shift(-forward_days) / close - 1
    label = (future_return * 100 > threshold).astype(int)
    # 最后forward_days天没有未来数据，设为NaN
    label.iloc[-forward_days:] = np.nan
    return label


def prepare_training_data(stock_code: str, days: int = 250) -> Tuple[pd.DataFrame, pd.Series]:
    """准备单只股票的训练数据。

    Returns:
        (features, labels)
    """
    from . import data_source as ds
    try:
        df = ds.get_kline_daily(stock_code, count=days + 30)
        if df.empty or len(df) < 60:
            return pd.DataFrame(), pd.Series()

        features = build_features(df)
        labels = build_label(df)

        # 对齐，去掉NaN
        valid = features.notna().all(axis=1) & labels.notna()
        return features[valid], labels[valid]

    except Exception as e:
        print(f"[特征工程] {stock_code} 准备失败: {e}")
        return pd.DataFrame(), pd.Series()


def get_feature_names() -> List[str]:
    """获取特征名称列表。"""
    return [
        "return_1d", "return_3d", "return_5d", "return_10d",
        "volatility_5d", "volatility_10d", "amplitude_5d", "amplitude_20d",
        "ma5_deviation", "ma10_deviation", "ma20_deviation",
        "ma5_slope", "ma10_slope", "ma_bullish",
        "macd_dif", "macd_dea", "macd_hist", "macd_golden_cross", "macd_above_zero",
        "rsi_6", "rsi_12", "rsi_24", "rsi_overbought", "rsi_oversold",
        "boll_position", "boll_width", "boll_break_upper", "boll_break_lower",
        "volume_ratio_5d", "volume_change_1d", "volume_trend", "price_volume_divergence",
        "new_high_20d", "new_low_20d", "consecutive_up", "consecutive_down",
    ]


def init_feature_engine():
    """初始化特征工程模块。"""
    return {"feature_count": len(get_feature_names()), "feature_names": get_feature_names()}
