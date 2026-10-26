# -*- coding: utf-8 -*-
"""市场状态聚类模块。

用无监督学习（KMeans）把市场环境细分为6种状态：
1. bull_trend      - 牛市趋势（上涨+低波动）
2. bear_trend      - 熊市趋势（下跌+高波动）
3. sideways_up     - 震荡上行（小幅上涨+中等波动）
4. sideways_down   - 震荡下行（小幅下跌+中等波动）
5. narrow_range    - 窄幅震荡（波动极小）
6. extreme         - 极端行情（暴涨暴跌）

比原来的5种环境（bull/bear/strong_rebound/sideways/extreme）更精细，
特别是把"震荡市"细分为3种子状态，不同子状态用不同策略参数。
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLUSTER_MODEL_FILE = os.path.join(BASE_DIR, "data", "models", "market_cluster.pkl")
CLUSTER_META_FILE = os.path.join(BASE_DIR, "data", "models", "market_cluster_meta.json")

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️ scikit-learn未安装，市场聚类将使用规则分类降级方案")


# 聚类中心标签（根据训练结果人工标注）
CLUSTER_LABELS = {
    0: "bull_trend",      # 牛市趋势
    1: "bear_trend",      # 熊市趋势
    2: "sideways_up",     # 震荡上行
    3: "sideways_down",   # 震荡下行
    4: "narrow_range",    # 窄幅震荡
    5: "extreme",         # 极端行情
}

CLUSTER_NAMES_CN = {
    "bull_trend": "牛市趋势",
    "bear_trend": "熊市趋势",
    "sideways_up": "震荡上行",
    "sideways_down": "震荡下行",
    "narrow_range": "窄幅震荡",
    "extreme": "极端行情",
}


class MarketCluster:
    """市场状态聚类器。"""

    def __init__(self):
        self.model = None
        self.scaler = None
        self.meta = {}
        self._load_model()

    def _load_model(self):
        """加载聚类模型。"""
        if not SKLEARN_AVAILABLE:
            return
        try:
            if os.path.exists(CLUSTER_MODEL_FILE):
                import pickle
                with open(CLUSTER_MODEL_FILE, "rb") as f:
                    data = pickle.load(f)
                    self.model = data.get("model")
                    self.scaler = data.get("scaler")
                if os.path.exists(CLUSTER_META_FILE):
                    with open(CLUSTER_META_FILE, "r", encoding="utf-8") as f:
                        self.meta = json.load(f)
                print(f"[市场聚类] 模型加载成功，聚类数：{self.meta.get('n_clusters', 6)}")
        except Exception as e:
            print(f"[市场聚类] 模型加载失败: {e}")

    def extract_market_features(self, index_df: pd.DataFrame,
                                 limit_up_count: int = 0,
                                 limit_down_count: int = 0,
                                 total_volume_yi: float = 0) -> np.ndarray:
        """从大盘指数数据提取市场特征。

        Args:
            index_df: 大盘指数K线（沪指）
            limit_up_count: 涨停家数
            limit_down_count: 跌停家数
            total_volume_yi: 两市成交额（亿）

        Returns:
            特征数组
        """
        if index_df.empty or len(index_df) < 20:
            return np.zeros(8)

        close = index_df["close"].astype(float)
        high = index_df["high"].astype(float)
        low = index_df["low"].astype(float)
        volume = index_df["volume"].astype(float)

        # 8个市场特征
        features = [
            # 1. 20日收益率（趋势方向）
            float(close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0,
            # 2. 5日收益率（短期方向）
            float(close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0,
            # 3. 20日波动率
            float(close.pct_change().rolling(20).std().iloc[-1] * 100) if len(close) >= 20 else 0,
            # 4. 20日振幅
            float((high.rolling(20).max().iloc[-1] - low.rolling(20).min().iloc[-1]) / close.rolling(20).mean().iloc[-1] * 100) if len(close) >= 20 else 0,
            # 5. 成交量变化率（5日均量/20日均量）
            float(volume.rolling(5).mean().iloc[-1] / volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else 1,
            # 6. 涨跌停比（市场情绪）
            float(limit_up_count / max(limit_down_count, 1)),
            # 7. 涨停家数（热度）
            float(limit_up_count),
            # 8. 成交额（活跃度，标准化到万亿）
            float(total_volume_yi / 10000),
        ]

        return np.array(features).reshape(1, -1)

    def train(self, index_df: pd.DataFrame, n_clusters: int = 6) -> Dict[str, Any]:
        """训练聚类模型。

        Args:
            index_df: 大盘指数历史K线
            n_clusters: 聚类数

        Returns:
            训练结果
        """
        if not SKLEARN_AVAILABLE:
            return {"status": "error", "message": "scikit-learn未安装"}

        if index_df.empty or len(index_df) < 60:
            return {"status": "error", "message": "数据不足"}

        print(f"[市场聚类] 开始训练，数据天数：{len(index_df)}，聚类数：{n_clusters}")

        # 构建历史特征序列（每天一个特征向量）
        features_list = []
        for i in range(20, len(index_df)):
            sub_df = index_df.iloc[:i+1]
            feat = self.extract_market_features(sub_df)
            features_list.append(feat.flatten())

        X = np.array(features_list)

        # 标准化
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # KMeans聚类
        self.model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = self.model.fit_predict(X_scaled)

        # 统计每个聚类的特征均值，用于标注
        cluster_stats = {}
        for c in range(n_clusters):
            mask = labels == c
            cluster_features = X[mask]
            if len(cluster_features) > 0:
                cluster_stats[c] = {
                    "count": int(mask.sum()),
                    "avg_return_20d": round(float(cluster_features[:, 0].mean()), 2),
                    "avg_volatility": round(float(cluster_features[:, 2].mean()), 2),
                    "avg_amplitude": round(float(cluster_features[:, 3].mean()), 2),
                }

        # 保存模型
        import pickle
        os.makedirs(os.path.dirname(CLUSTER_MODEL_FILE), exist_ok=True)
        with open(CLUSTER_MODEL_FILE, "wb") as f:
            pickle.dump({"model": self.model, "scaler": self.scaler}, f)

        self.meta = {
            "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "n_clusters": n_clusters,
            "sample_count": len(X),
            "cluster_stats": cluster_stats,
            "feature_names": ["return_20d", "return_5d", "volatility", "amplitude",
                              "volume_ratio", "limit_up_down_ratio", "limit_up_count", "volume_yi"],
        }
        with open(CLUSTER_META_FILE, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

        print(f"[市场聚类] 训练完成，各聚类样本数：{[cluster_stats[c]['count'] for c in range(n_clusters)]}")
        return self.meta

    def predict(self, index_df: pd.DataFrame, limit_up_count: int = 0,
                limit_down_count: int = 0, total_volume_yi: float = 0) -> Dict[str, Any]:
        """预测当前市场状态。

        Returns:
            {cluster_id, cluster_name, cluster_name_cn, features, confidence}
        """
        features = self.extract_market_features(index_df, limit_up_count, limit_down_count, total_volume_yi)

        if self.model is not None and self.scaler is not None and SKLEARN_AVAILABLE:
            X_scaled = self.scaler.transform(features)
            cluster_id = int(self.model.predict(X_scaled)[0])
            # 计算到各聚类中心的距离，作为置信度
            distances = self.model.transform(X_scaled)[0]
            confidence = float(1 - distances[cluster_id] / distances.sum())
            cluster_name = CLUSTER_LABELS.get(cluster_id, f"cluster_{cluster_id}")
        else:
            # 降级方案：规则分类
            cluster_id, cluster_name = self._rule_based_classify(features)
            confidence = 0.6

        return {
            "cluster_id": cluster_id,
            "cluster_name": cluster_name,
            "cluster_name_cn": CLUSTER_NAMES_CN.get(cluster_name, "未知"),
            "confidence": round(confidence, 4),
            "features": features.flatten().tolist(),
            "model_used": "kmeans" if self.model is not None else "rule_based",
        }

    def _rule_based_classify(self, features: np.ndarray) -> Tuple[int, str]:
        """规则分类降级方案。"""
        ret_20d = features[0][0]
        volatility = features[0][2]
        amplitude = features[0][3]

        if abs(ret_20d) > 15 or volatility > 3:
            return 5, "extreme"
        elif ret_20d > 8 and volatility < 2:
            return 0, "bull_trend"
        elif ret_20d < -8 and volatility > 2:
            return 1, "bear_trend"
        elif ret_20d > 0 and amplitude < 8:
            return 2, "sideways_up"
        elif ret_20d < 0 and amplitude < 8:
            return 3, "sideways_down"
        else:
            return 4, "narrow_range"

    def get_strategy_params(self, cluster_name: str) -> Dict[str, Any]:
        """根据市场状态获取策略参数。

        不同市场状态用不同的策略参数，这是自适应策略的核心。
        """
        params_map = {
            "bull_trend": {
                "macd_min_score": 50,
                "macd_amplitude_max": 50,
                "oversold_drop_min": 30,
                "breakout_enabled": True,
                "position_pct": 0.35,
                "stop_loss_pct": 0.06,
                "take_profit_pct": 0.12,
                "recommendation": "牛市趋势：MACD共振为主，可适当放宽条件，仓位可加到35%",
            },
            "bear_trend": {
                "macd_min_score": 70,
                "macd_amplitude_max": 35,
                "oversold_drop_min": 25,
                "breakout_enabled": False,
                "position_pct": 0.20,
                "stop_loss_pct": 0.04,
                "take_profit_pct": 0.08,
                "recommendation": "熊市趋势：超跌反弹为主，严格条件，仓位降到20%，止损更严",
            },
            "sideways_up": {
                "macd_min_score": 55,
                "macd_amplitude_max": 45,
                "oversold_drop_min": 25,
                "breakout_enabled": True,
                "position_pct": 0.30,
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.10,
                "recommendation": "震荡上行：MACD+突破双策略，标准仓位30%",
            },
            "sideways_down": {
                "macd_min_score": 65,
                "macd_amplitude_max": 40,
                "oversold_drop_min": 22,
                "breakout_enabled": False,
                "position_pct": 0.25,
                "stop_loss_pct": 0.045,
                "take_profit_pct": 0.08,
                "recommendation": "震荡下行：超跌反弹为主，谨慎开仓，仓位25%",
            },
            "narrow_range": {
                "macd_min_score": 60,
                "macd_amplitude_max": 30,
                "oversold_drop_min": 20,
                "breakout_enabled": True,
                "position_pct": 0.25,
                "stop_loss_pct": 0.04,
                "take_profit_pct": 0.07,
                "recommendation": "窄幅震荡：突破策略捕捉方向选择，快进快出，止盈7%",
            },
            "extreme": {
                "macd_min_score": 80,
                "macd_amplitude_max": 60,
                "oversold_drop_min": 35,
                "breakout_enabled": False,
                "position_pct": 0.15,
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.06,
                "recommendation": "极端行情：暂停或极小仓位，严格止损3%，观望为主",
            },
        }
        return params_map.get(cluster_name, params_map["narrow_range"])


def init_market_cluster() -> MarketCluster:
    """初始化市场聚类器。"""
    return MarketCluster()
