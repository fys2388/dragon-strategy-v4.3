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
MACD_PARAMS = {
    "bull_market": {
        "name": "牛市配置",
        "daily_dif_floor": -0.02,       # 日线DIF下限（放宽，允许零轴附近）
        "require_tf15_cross_zero": False,  # 不强制15min上穿零轴
        "require_tf30_golden": True,     # 30min金叉
        "require_tf60_golden": True,     # 60min金叉
        "amplitude_20d_max": 50.0,       # 20日振幅上限放宽到50%
        "min_score": 50,                 # 最低得分降低
        "max_recommendations": 5,
        "position_pct": 0.35,            # 单票仓位35%
        "max_positions": 3,
        "take_profit_1_pct": 0.12,       # 止盈1 12%
        "take_profit_2_pct": 0.20,       # 止盈2 20%
        "stop_loss_pct": 0.06,           # 止损6%
    },
    "bear_market": {
        "name": "熊市配置",
        "daily_dif_floor": 0.05,         # 日线DIF必须在零轴上方
        "require_tf15_cross_zero": True,  # 强制15min上穿零轴
        "require_tf30_golden": True,
        "require_tf60_golden": True,
        "amplitude_20d_max": 35.0,       # 20日振幅收紧到35%
        "min_score": 70,                 # 最低得分提高
        "max_recommendations": 3,
        "position_pct": 0.20,            # 单票仓位20%
        "max_positions": 2,
        "take_profit_1_pct": 0.08,       # 止盈1 8%
        "take_profit_2_pct": 0.12,       # 止盈2 12%
        "stop_loss_pct": 0.04,           # 止损4%
    },
    "strong_rebound": {
        "name": "强反弹配置",
        "daily_dif_floor": -0.05,
        "require_tf15_cross_zero": False,
        "require_tf30_golden": True,
        "require_tf60_golden": True,
        "amplitude_20d_max": 45.0,
        "min_score": 55,
        "max_recommendations": 5,
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
        "min_score": 60,
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
        "min_score": 80,
        "max_recommendations": 2,
        "position_pct": 0.15,
        "max_positions": 1,
        "take_profit_1_pct": 0.06,
        "take_profit_2_pct": 0.10,
        "stop_loss_pct": 0.03,
    },
}

# 超跌反弹参数
OVERSOLD_PARAMS = {
    "bull_market": {
        "name": "牛市超跌配置",
        "drop_20d_min": 20.0,            # 超跌要求降低（牛市跌20%就算超跌）
        "today_gain_min": 3.0,           # 启动涨幅降低
        "volume_ratio_min": 1.5,         # 量比要求降低
        "daily_dif_floor": -1.0,         # DIF下限放宽
        "max_recommendations": 5,
        "position_pct": 0.35,
        "take_profit_pct": 0.15,
        "stop_loss_pct": 0.06,
    },
    "bear_market": {
        "name": "熊市超跌配置",
        "drop_20d_min": 35.0,            # 超跌要求提高（熊市要跌更多）
        "today_gain_min": 5.0,           # 启动涨幅提高
        "volume_ratio_min": 2.5,         # 量比要求提高
        "daily_dif_floor": -0.5,         # DIF下限收紧
        "max_recommendations": 3,
        "position_pct": 0.20,
        "take_profit_pct": 0.10,
        "stop_loss_pct": 0.04,
    },
    "strong_rebound": {
        "name": "强反弹超跌配置",
        "drop_20d_min": 25.0,
        "today_gain_min": 3.5,
        "volume_ratio_min": 1.8,
        "daily_dif_floor": -0.8,
        "max_recommendations": 5,
        "position_pct": 0.30,
        "take_profit_pct": 0.12,
        "stop_loss_pct": 0.05,
    },
    "sideways": {
        "name": "震荡市超跌配置",
        "drop_20d_min": 30.0,
        "today_gain_min": 4.0,
        "volume_ratio_min": 2.0,
        "daily_dif_floor": -0.6,
        "max_recommendations": 3,
        "position_pct": 0.25,
        "take_profit_pct": 0.10,
        "stop_loss_pct": 0.05,
    },
    "extreme": {
        "name": "极端行情超跌配置",
        "drop_20d_min": 40.0,
        "today_gain_min": 6.0,
        "volume_ratio_min": 3.0,
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
