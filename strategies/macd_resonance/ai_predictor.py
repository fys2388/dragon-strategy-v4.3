# -*- coding: utf-8 -*-
"""AI预测模型模块（LightGBM）。

核心能力：
1. 训练：用多只股票历史数据训练LightGBM分类模型
2. 预测：预测个股未来5日上涨概率
3. 批量预测：给股票池批量打分
4. 特征重要性：输出哪些特征最有预测力
5. 模型版本管理：记录训练时间、样本数、准确率

模型目标：预测未来5日涨幅>3%的概率
标签：1=上涨>3%，0=不涨
"""
from __future__ import annotations

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(BASE_DIR, "data", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

MODEL_FILE = os.path.join(MODEL_DIR, "lgbm_model.pkl")
MODEL_META_FILE = os.path.join(MODEL_DIR, "model_meta.json")

# 尝试导入LightGBM，失败则用降级方案
try:
    import lightgbm as lgb
    LGBM_AVAILABLE = True
except ImportError:
    LGBM_AVAILABLE = False
    print("⚠️ LightGBM未安装，将使用简单逻辑回归降级方案")


class AIPredictor:
    """AI预测模型。"""

    def __init__(self):
        self.model = None
        self.feature_names = []
        self.meta = {}
        self._load_model()

    def _load_model(self):
        """加载已训练模型。"""
        try:
            if os.path.exists(MODEL_FILE) and LGBM_AVAILABLE:
                import pickle
                with open(MODEL_FILE, "rb") as f:
                    self.model = pickle.load(f)
                if os.path.exists(MODEL_META_FILE):
                    with open(MODEL_META_FILE, "r", encoding="utf-8") as f:
                        self.meta = json.load(f)
                self.feature_names = self.meta.get("feature_names", [])
                print(f"[AI模型] 加载成功，训练时间：{self.meta.get('trained_at', '未知')}，准确率：{self.meta.get('accuracy', 0)}%")
            else:
                print("[AI模型] 未找到已训练模型，将使用规则打分降级方案")
        except Exception as e:
            print(f"[AI模型] 加载失败: {e}，将使用规则打分降级方案")
            self.model = None

    def train(self, stock_codes: List[str], days: int = 250) -> Dict[str, Any]:
        """训练模型。

        Args:
            stock_codes: 训练用股票代码列表
            days: 每只股票取多少天数据

        Returns:
            训练结果元信息
        """
        from .feature_engineering import prepare_training_data, get_feature_names

        if not LGBM_AVAILABLE:
            return {"status": "error", "message": "LightGBM未安装"}

        print(f"[AI模型] 开始训练，股票数：{len(stock_codes)}，每只{days}天")

        all_features = []
        all_labels = []

        for code in stock_codes:
            try:
                features, labels = prepare_training_data(code, days)
                if not features.empty and len(labels) > 0:
                    all_features.append(features)
                    all_labels.append(labels)
                    print(f"  {code}: {len(features)}条样本")
            except Exception as e:
                print(f"  {code}: 准备失败 - {e}")

        if not all_features:
            return {"status": "error", "message": "没有可用的训练数据"}

        # 合并所有股票的数据
        X = pd.concat(all_features, ignore_index=True)
        y = pd.concat(all_labels, ignore_index=True)

        print(f"[AI模型] 总样本数：{len(X)}，正样本：{int(y.sum())}，负样本：{int(len(y) - y.sum())}")

        # 划分训练集和验证集（80/20，不随机打乱，保持时间顺序）
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

        # 训练LightGBM
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
            "min_data_in_leaf": 20,
            "max_depth": 6,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
        }

        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=200,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)],
        )

        # 计算验证集准确率
        y_pred = (self.model.predict(X_val) > 0.5).astype(int)
        accuracy = (y_pred == y_val).mean() * 100

        # 计算AUC
        try:
            from sklearn.metrics import roc_auc_score
            y_prob = self.model.predict(X_val)
            auc = roc_auc_score(y_val, y_prob)
        except Exception:
            auc = 0

        # 特征重要性
        importance = self.model.feature_importance(importance_type="gain")
        feature_importance = dict(zip(X.columns.tolist(), importance.tolist()))
        top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]

        # 保存模型
        import pickle
        with open(MODEL_FILE, "wb") as f:
            pickle.dump(self.model, f)

        # 保存元信息
        self.meta = {
            "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sample_count": len(X),
            "positive_count": int(y.sum()),
            "negative_count": int(len(y) - y.sum()),
            "accuracy": round(accuracy, 2),
            "auc": round(auc, 4),
            "stock_count": len(stock_codes),
            "days": days,
            "feature_names": X.columns.tolist(),
            "top_features": [{"feature": f, "importance": round(v, 2)} for f, v in top_features],
            "params": params,
        }
        with open(MODEL_META_FILE, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

        self.feature_names = X.columns.tolist()

        print(f"[AI模型] 训练完成，准确率：{accuracy:.2f}%，AUC：{auc:.4f}")
        print(f"[AI模型] Top10特征：{[f for f, _ in top_features]}")

        return self.meta

    def predict(self, stock_code: str) -> Dict[str, Any]:
        """预测单只股票未来5日上涨概率。

        Returns:
            {probability, prediction, features, model_used}
        """
        from .feature_engineering import build_features, get_feature_names
        from . import data_source as ds

        try:
            df = ds.get_kline_daily(stock_code, count=60)
            if df.empty or len(df) < 30:
                return {"probability": 0.5, "prediction": 0, "model_used": "no_data"}

            features = build_features(df)
            if features.empty:
                return {"probability": 0.5, "prediction": 0, "model_used": "no_features"}

            # 取最后一行（最新数据）
            latest_features = features.iloc[[-1]].dropna(axis=1)

            if self.model is not None and LGBM_AVAILABLE:
                # 确保特征顺序一致
                model_features = self.feature_names
                available_features = [f for f in model_features if f in latest_features.columns]
                X_pred = latest_features[available_features]
                # 补全缺失特征为0
                for f in model_features:
                    if f not in X_pred.columns:
                        X_pred[f] = 0
                X_pred = X_pred[model_features]

                prob = float(self.model.predict(X_pred)[0])
                return {
                    "probability": round(prob, 4),
                    "prediction": 1 if prob > 0.5 else 0,
                    "model_used": "lightgbm",
                    "features_used": len(available_features),
                }
            else:
                # 降级方案：规则打分
                return self._rule_based_predict(latest_features.iloc[0])

        except Exception as e:
            print(f"[AI模型] {stock_code} 预测失败: {e}")
            return {"probability": 0.5, "prediction": 0, "model_used": "error", "error": str(e)}

    def _rule_based_predict(self, features: pd.Series) -> Dict[str, Any]:
        """规则打分降级方案（无LightGBM时使用）。"""
        score = 50  # 基础分50

        # MACD金叉 +10
        if features.get("macd_golden_cross", 0) == 1:
            score += 10
        # MACD在零轴上方 +5
        if features.get("macd_above_zero", 0) == 1:
            score += 5
        # 均线多头 +10
        if features.get("ma_bullish", 0) == 1:
            score += 10
        # RSI在30-70之间（不超买超卖）+5
        rsi = features.get("rsi_6", 50)
        if 30 < rsi < 70:
            score += 5
        # 突破20日新高 +10
        if features.get("new_high_20d", 0) == 1:
            score += 10
        # 放量 +5
        if features.get("volume_ratio_5d", 1) > 1.5:
            score += 5
        # 5日涨幅为正 +5
        if features.get("return_5d", 0) > 0:
            score += 5
        # 布林带中轨上方 +5
        if features.get("boll_position", 0.5) > 0.5:
            score += 5

        prob = min(max(score / 100, 0), 1)
        return {
            "probability": round(prob, 4),
            "prediction": 1 if prob > 0.5 else 0,
            "model_used": "rule_based",
            "score": score,
        }

    def batch_predict(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """批量预测。

        Returns:
            {code: prediction_result}
        """
        results = {}
        for code in stock_codes:
            results[code] = self.predict(code)
            time.sleep(0.1)
        return results

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息。"""
        if self.model is None:
            return {"status": "no_model", "message": "未训练模型，使用规则打分"}
        return {
            "status": "loaded",
            "trained_at": self.meta.get("trained_at"),
            "accuracy": self.meta.get("accuracy"),
            "auc": self.meta.get("auc"),
            "sample_count": self.meta.get("sample_count"),
            "top_features": self.meta.get("top_features", []),
        }

    def build_model_report(self) -> str:
        """生成模型报告。"""
        info = self.get_model_info()
        lines = [
            "🤖 AI预测模型状态",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        if info["status"] == "no_model":
            lines.append("⚠️ 未训练模型，当前使用规则打分降级方案")
            lines.append("运行每周模型训练workflow后将启用LightGBM")
        else:
            lines.append(f"✅ 模型已加载")
            lines.append(f"训练时间：{info['trained_at']}")
            lines.append(f"准确率：{info['accuracy']}% | AUC：{info['auc']}")
            lines.append(f"训练样本：{info['sample_count']}条")
            lines.append("")
            lines.append("Top10重要特征：")
            for i, f in enumerate(info.get("top_features", [])[:10], 1):
                lines.append(f"  {i}. {f['feature']}（重要性{f['importance']}）")
        return "\n".join(lines)


def init_ai_predictor() -> AIPredictor:
    """初始化AI预测器。"""
    return AIPredictor()
