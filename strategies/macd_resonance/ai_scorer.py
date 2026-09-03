# -*- coding: utf-8 -*-
"""AI打分融合模块。

将规则策略选出的候选股票，用AI模型预测上涨概率，
只推送概率>阈值的股票，并在推送中显示AI打分。

流程：
规则策略选候选 → AI模型预测概率 → 过滤低概率 → 按概率排序 → 输出推荐

这是从"规则策略"走向"AI辅助决策"的关键一步。
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AIScorer:
    """AI打分融合器。"""

    def __init__(self, min_probability: float = 0.55):
        """
        Args:
            min_probability: 最低推送概率阈值
        """
        self.min_probability = min_probability
        self.predictor = None
        self._init_predictor()

    def _init_predictor(self):
        """初始化AI预测器。"""
        try:
            from .ai_predictor import init_ai_predictor
            self.predictor = init_ai_predictor()
        except Exception as e:
            print(f"[AI打分] 预测器初始化失败: {e}，将使用原始推荐")
            self.predictor = None

    def score_candidates(self, candidates: List[Dict], strategy_type: str = "") -> List[Dict]:
        """给候选股票打分并过滤。

        Args:
            candidates: 候选股票列表，每项需含 code/name/price
            strategy_type: 策略类型（用于日志）

        Returns:
            带AI打分的推荐列表，按概率降序排列
        """
        if not candidates:
            return []

        if self.predictor is None:
            # 无AI模型时，返回原始候选
            for c in candidates:
                c["ai_probability"] = 0.5
                c["ai_score"] = 50
                c["ai_model"] = "unavailable"
            return candidates

        print(f"[AI打分] 开始给{len(candidates)}只候选股票打分（策略={strategy_type}）")

        scored = []
        for candidate in candidates:
            code = candidate.get("code", "")
            if not code:
                continue

            try:
                result = self.predictor.predict(code)
                prob = result.get("probability", 0.5)
                candidate["ai_probability"] = prob
                candidate["ai_score"] = round(prob * 100, 1)
                candidate["ai_model"] = result.get("model_used", "unknown")
                candidate["ai_prediction"] = result.get("prediction", 0)

                if prob >= self.min_probability:
                    scored.append(candidate)
                    print(f"  ✅ {candidate.get('name', code)}({code}) AI概率{prob*100:.1f}%，通过")
                else:
                    print(f"  ❌ {candidate.get('name', code)}({code}) AI概率{prob*100:.1f}%，低于阈值{self.min_probability*100:.0f}%，过滤")

            except Exception as e:
                print(f"  ⚠️ {code} 打分失败: {e}，保留原始推荐")
                candidate["ai_probability"] = 0.5
                candidate["ai_score"] = 50
                candidate["ai_model"] = "error"
                scored.append(candidate)

            time.sleep(0.1)  # 限速

        # 按AI概率降序排列
        scored.sort(key=lambda x: x.get("ai_probability", 0), reverse=True)

        print(f"[AI打分] 完成：{len(candidates)}只候选 → {len(scored)}只通过（阈值{self.min_probability*100:.0f}%）")
        return scored

    def add_ai_info_to_message(self, message: str, entries: List[Dict]) -> str:
        """在推送消息中添加AI打分信息。"""
        if not entries:
            return message

        ai_lines = ["", "🤖 AI智能打分："]
        for e in entries:
            prob = e.get("ai_probability", 0)
            score = e.get("ai_score", 0)
            model = e.get("ai_model", "unknown")
            if prob >= 0.7:
                emoji = "🟢"
                label = "高概率"
            elif prob >= 0.55:
                emoji = "🟡"
                label = "中概率"
            else:
                emoji = "⚪"
                label = "低概率"

            ai_lines.append(f"  {emoji} {e.get('name', '')}({e.get('code', '')})：上涨概率{score}%（{label}，模型={model}）")

        return message + "\n".join(ai_lines)

    def get_scorer_info(self) -> Dict[str, Any]:
        """获取打分器信息。"""
        if self.predictor is None:
            return {"status": "unavailable", "min_probability": self.min_probability}
        return {
            "status": "active",
            "min_probability": self.min_probability,
            "model_info": self.predictor.get_model_info(),
        }


def init_ai_scorer(min_probability: float = 0.55) -> AIScorer:
    """初始化AI打分器。"""
    return AIScorer(min_probability=min_probability)
