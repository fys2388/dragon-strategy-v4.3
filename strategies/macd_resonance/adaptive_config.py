# -*- coding: utf-8 -*-
"""动态参数配置模块。

根据市场环境自动调整策略参数，实现自适应。
支持参数优化结果的持久化和加载。
"""
from __future__ import annotations

import json
import os
from typing import Dict, Any

from .market_regime import classify_regime, REGIME_LABELS
from .data_validator import MarketData

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OPTIMIZED_PARAMS_FILE = os.path.join(BASE_DIR, "data", "optimized_params.json")

# ============================================================
# 基础参数（各市场环境的默认配置）
# ============================================================

# MACD多周期共振参数
#
# ⚠️ min_score 的口径（2026-09-22 二次重写，量纲 1.0~3.05）：
#   2026-09-22 重设计：共振 = "趋势延续"，不再要求突破。
#   signal_engine.check_long_entry 的评分量纲改为 1.0~3.05（基础 1.0
#   + 60min 0.5 + 30min 0.4 + 15min 0.3 + 量比 0.3 + 无顶背离 0.1），
#   而 scanner.run() 用 adaptive_params["min_score"] 做过滤。
#   原配置把 min_score 写成 40~80（那是 breakout 的百分制口径），
#   导致信号永远 < 40，共振推荐被结构性清零——这是「共振长期 0 推荐」
#   的独立根因。现已改为 1.0~3.05 量纲，并按市场环境从宽到严排列：
#     牛市：min_score=2.0（日线多头 1.0 + 至少 60min 零轴上 0.5 + 30min 零轴上 0.4 = 1.9，
#                                       加量比健康 0.3 达到 2.2，正好在阈值上）
#     熊市：min_score=2.5（更严，要求更多周期零轴确认）
#     极端：min_score=2.8（近乎全套确认）
MACD_PARAMS = {
    "bull_market": {
        "name": "牛市配置",
        "daily_dif_floor": -0.02,
        "require_tf15_cross_zero": False,
        "require_tf30_golden": True,
        "require_tf60_golden": True,
        "amplitude_20d_max": 50.0,
        "min_score": 2.0,
        "max_recommendations": 3,
        "position_pct": 0.35,
        "max_positions": 3,
        "take_profit_1_pct": 0.12,
        "take_profit_2_pct": 0.20,
        "stop_loss_pct": 0.06,
    },
    "bear_market": {
        "name": "熊市配置",
        "daily_dif_floor": 0.05,
        "require_tf15_cross_zero": True,
        "require_tf30_golden": True,
        "require_tf60_golden": True,
        "amplitude_20d_max": 35.0,
        "min_score": 2.5,
        "max_recommendations": 3,
        "position_pct": 0.20,
        "max_positions": 2,
        "take_profit_1_pct": 0.08,
        "take_profit_2_pct": 0.12,
        "stop_loss_pct": 0.04,
    },
    "strong_rebound": {
        "name": "强反弹配置",
        "daily_dif_floor": -0.05,
        "require_tf15_cross_zero": False,
        "require_tf30_golden": True,
        "require_tf60_golden": True,
        "amplitude_20d_max": 45.0,
        "min_score": 2.0,
        "max_recommendations": 3,
        "position_pct": 0.30,
        "max_positions": 3,
        "take_profit_1_pct": 0.10,
        "take_profit_2_pct": 0.15,
        "stop_loss_pct": 0.05,
    },
    "sideways": {
        "name": "震荡市配置",
        "daily_dif_floor": 0.0,
        "require_tf15_cross_zero": True,
        "require_tf30_golden": True,
        "require_tf60_golden": True,
        "amplitude_20d_max": 40.0,
        "min_score": 2.2,
        "max_recommendations": 3,
        "position_pct": 0.25,
        "max_positions": 2,
        "take_profit_1_pct": 0.08,
        "take_profit_2_pct": 0.12,
        "stop_loss_pct": 0.05,
    },
    "extreme": {
        "name": "极端行情配置",
        "daily_dif_floor": 0.1,
        "require_tf15_cross_zero": True,
        "require_tf30_golden": True,
        "require_tf60_golden": True,
        "amplitude_20d_max": 30.0,
        "min_score": 2.8,
        "max_recommendations": 2,
        "position_pct": 0.15,
        "max_positions": 1,
        "take_profit_1_pct": 0.06,
        "take_profit_2_pct": 0.10,
        "stop_loss_pct": 0.03,
    },
}

# 超跌反弹参数（2026-09-22 拆两种口径）
#
# ⚠️ 2026-09-22 重设计：拆「真超跌」（熊市用）与「趋势回调」（牛市用）两套。
#   原设计在牛市强制要求 20 日跌幅 ≥20%（drop_20d_min=20），
#   但 bull_market 环境下结构性不存在——全市场都在涨，没有股票 20 日跌 20%。
#   实测 run 35696267711：初筛 120 只，超跌条件 0 只（100% 被 drop_20d_min 拒掉）。
#   现在 bull_market 改用「从 20 日高点回调 8%~15%」口径（趋势回调买入），
#   熊市仍走「20 日跌幅 ≥25%」的真超跌口径。
#   drop_20d_min 字段在牛市配为 0（不做跌幅下限过滤，改用 drop_from_20d_high_min/max 区间）。
OVERSOLD_PARAMS = {
    "bull_market": {
        "name": "牛市回调配置",
        # 牛市不做跌幅下限过滤（drop_20d_min=0 意味着任何跌幅都过）
        "drop_20d_min": 0.0,
        # 从 20 日高点回调 8%~15%（趋势回调买入，不是真超跌）
        "drop_from_20d_high_min": 8.0,
        "drop_from_20d_high_max": 20.0,
        "pullback_days": 3,          # 回调至少 3 天
        "pullback_days_max": 8,      # 回调不超过 8 天（避免趋势走坏）
        "volume_shrink_min": 0.6,    # 回调期量比 ≥0.6（缩量确认）
        "today_gain_min": 2.0,       # 今天重新放量反弹 +2%
        "volume_ratio_min": 1.5,     # 反弹日量比 ≥1.5
        "daily_dif_floor": -1.0,
        "max_recommendations": 3,
        "position_pct": 0.35,
        "take_profit_pct": 0.15,
        "stop_loss_pct": 0.06,
    },
    "bear_market": {
        "name": "熊市真超跌配置",
        "drop_20d_min": 25.0,        # 20 日跌幅 ≥25%（真超跌）
        "drop_from_20d_high_min": 0.0,
        "drop_from_20d_high_max": 100.0,  # 熊市不设高点回调区间限制
        "pullback_days": 5,
        "pullback_days_max": 999,
        "volume_shrink_min": 0.0,    # 熊市不做缩量要求
        "today_gain_min": 4.0,       # 启动涨幅更高（4%）
        "volume_ratio_min": 1.8,
        "daily_dif_floor": -0.5,
        "max_recommendations": 3,
        "position_pct": 0.20,
        "take_profit_pct": 0.10,
        "stop_loss_pct": 0.04,
    },
    "strong_rebound": {
        "name": "强反弹配置",
        "drop_20d_min": 15.0,
        "drop_from_20d_high_min": 6.0,
        "drop_from_20d_high_max": 18.0,
        "pullback_days": 3,
        "pullback_days_max": 8,
        "volume_shrink_min": 0.6,
        "today_gain_min": 3.0,
        "volume_ratio_min": 1.6,
        "daily_dif_floor": -0.8,
        "max_recommendations": 3,
        "position_pct": 0.30,
        "take_profit_pct": 0.12,
        "stop_loss_pct": 0.05,
    },
    "sideways": {
        "name": "震荡市配置",
        "drop_20d_min": 18.0,
        "drop_from_20d_high_min": 8.0,
        "drop_from_20d_high_max": 20.0,
        "pullback_days": 3,
        "pullback_days_max": 8,
        "volume_shrink_min": 0.6,
        "today_gain_min": 3.5,
        "volume_ratio_min": 1.8,
        "daily_dif_floor": -0.6,
        "max_recommendations": 3,
        "position_pct": 0.25,
        "take_profit_pct": 0.10,
        "stop_loss_pct": 0.05,
    },
    "extreme": {
        "name": "极端行情配置",
        "drop_20d_min": 30.0,
        "drop_from_20d_high_min": 0.0,
        "drop_from_20d_high_max": 100.0,
        "pullback_days": 5,
        "pullback_days_max": 999,
        "volume_shrink_min": 0.0,
        "today_gain_min": 5.0,
        "volume_ratio_min": 2.5,
        "daily_dif_floor": -0.3,
        "max_recommendations": 2,
        "position_pct": 0.15,
        "take_profit_pct": 0.08,
        "stop_loss_pct": 0.03,
    },
}


def get_current_regime(market_data: MarketData = None) -> str:
    """获取当前市场环境。"""
    return classify_regime(market_data)


def get_macd_params(regime: str = None, market_data: MarketData = None) -> Dict[str, Any]:
    """获取MACD共振策略参数。

    优先使用优化后的参数，其次使用默认参数。
    """
    if regime is None:
        regime = get_current_regime(market_data)

    # 加载优化参数
    optimized = _load_optimized_params()
    if regime in optimized.get("macd", {}):
        params = MACD_PARAMS.get(regime, MACD_PARAMS["sideways"]).copy()
        params.update(optimized["macd"][regime])
        params["_optimized"] = True
        return params

    params = MACD_PARAMS.get(regime, MACD_PARAMS["sideways"]).copy()
    params["_optimized"] = False
    return params


def get_oversold_params(regime: str = None, market_data: MarketData = None) -> Dict[str, Any]:
    """获取超跌反弹策略参数。"""
    if regime is None:
        regime = get_current_regime(market_data)

    optimized = _load_optimized_params()
    if regime in optimized.get("oversold", {}):
        params = OVERSOLD_PARAMS.get(regime, OVERSOLD_PARAMS["sideways"]).copy()
        params.update(optimized["oversold"][regime])
        params["_optimized"] = True
        return params

    params = OVERSOLD_PARAMS.get(regime, OVERSOLD_PARAMS["sideways"]).copy()
    params["_optimized"] = False
    return params


def get_risk_params(regime: str = None, market_data: MarketData = None) -> Dict[str, Any]:
    """获取风控参数（仓位、止盈止损）。"""
    macd_params = get_macd_params(regime, market_data)
    return {
        "position_pct": macd_params.get("position_pct", 0.25),
        "max_positions": macd_params.get("max_positions", 2),
        "take_profit_1_pct": macd_params.get("take_profit_1_pct", 0.10),
        "take_profit_2_pct": macd_params.get("take_profit_2_pct", 0.15),
        "stop_loss_pct": macd_params.get("stop_loss_pct", 0.05),
    }


def _load_optimized_params() -> Dict:
    """加载优化后的参数。"""
    try:
        if os.path.exists(OPTIMIZED_PARAMS_FILE):
            with open(OPTIMIZED_PARAMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_optimized_params(macd_params: Dict = None, oversold_params: Dict = None):
    """保存优化后的参数。"""
    data = _load_optimized_params()
    if macd_params:
        data.setdefault("macd", {}).update(macd_params)
    if oversold_params:
        data.setdefault("oversold", {}).update(oversold_params)
    data["last_optimized"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    os.makedirs(os.path.dirname(OPTIMIZED_PARAMS_FILE), exist_ok=True)
    with open(OPTIMIZED_PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[自适应] 优化参数已保存到 {OPTIMIZED_PARAMS_FILE}")


def get_regime_summary(market_data: MarketData = None) -> str:
    """获取市场环境摘要字符串。"""
    regime = get_current_regime(market_data)
    label = REGIME_LABELS.get(regime, "未知")
    params = get_macd_params(regime, market_data)
    optimized = "已优化" if params.get("_optimized") else "默认"
    return f"市场环境：{label}({regime}) | 参数配置：{params['name']} | {optimized}"
