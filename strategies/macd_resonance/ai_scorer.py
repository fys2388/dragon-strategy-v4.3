# -*- coding: utf-8 -*-
"""AI打分融合模块。

将规则策略选出的候选股票，再经过一层打分排序，只推送高分的股票。

流程：
规则策略选候选 → 打分（LightGBM 概率，无模型时降级为规则打分）→ 过滤低分 → 按分排序 → 输出推荐

⚠️ 命名口径（2026-09-21 修正，属于诚实性修复）：
   当前仓库**没有训练好的模型文件**（data/models/lgbm_model.pkl 不存在），
   `AIPredictor` 实际走 `_rule_based_predict` 的规则加分（基础50分 + 各条件加分）。
   原实现把该分数除以100塞进 `ai_probability`，推送文案写成「上涨概率 XX%」，
   等于给规则打分贴了概率标签。
   现在统一以 `ai_score`（0~100）为主字段，并写入 `ai_score_basis`
   （"model" = 真实模型概率；"rule_based" = 规则打分），推送文案按 basis 分别措辞。
   `ai_probability` 仅在 basis=="model" 时写入，不再对规则打分伪造概率。
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 规则打分时推送里用的措辞，避免把规则分说成概率
RULE_SCORE_BASIS = "rule_based"
MODEL_SCORE_BASIS = "model"


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
            # 无打分器时，返回原始候选，标记为不可用（不伪造任何分数）
            for c in candidates:
                c["ai_score"] = 50
                c["ai_score_basis"] = "unavailable"
                c["ai_model"] = "unavailable"
            return candidates

        # 首次运行时如实告知当前打分依据
        try:
            info = self.predictor.get_model_info()
            if info.get("score_basis") == RULE_SCORE_BASIS or info.get("status") == "no_model":
                print(f"[AI打分] 注意：当前无训练好的模型，打分=规则打分（0~100），"
                      f"不是上涨概率。{info.get('message', '')}")
        except Exception:
            pass

        print(f"[AI打分] 开始给{len(candidates)}只候选股票打分（策略={strategy_type}）")

        scored = []
        for candidate in candidates:
            code = candidate.get("code", "")
            if not code:
                continue

            try:
                result = self.predictor.predict(code)
                basis = result.get("score_basis") or \
                    (MODEL_SCORE_BASIS if result.get("probability_is_actual_model") else RULE_SCORE_BASIS)
                prob = result.get("probability", 0.5)
                ai_score = float(result.get("rule_score", round(prob * 100, 1)))
                candidate["ai_score"] = round(ai_score, 1)
                candidate["ai_score_basis"] = basis
                candidate["ai_rule_score"] = round(ai_score, 1)
                candidate["ai_model"] = result.get("model_used", "unknown")
                candidate["ai_prediction"] = result.get("prediction", 0)
                if result.get("rule_hits"):
                    candidate["ai_score_hits"] = result["rule_hits"]
                # 只有真实模型概率才写 ai_probability，规则打分不再伪造概率
                if result.get("probability_is_actual_model", False):
                    candidate["ai_probability"] = prob

                threshold = self.min_probability
                if ai_score >= threshold * 100:
                    scored.append(candidate)
                    unit = "%" if basis == MODEL_SCORE_BASIS else "分"
                    print(f"  ✅ {candidate.get('name', code)}({code}) 打分{ai_score}{unit}"
                          f"（{basis}），通过")
                else:
                    unit = "%" if basis == MODEL_SCORE_BASIS else "分"
                    print(f"  ❌ {candidate.get('name', code)}({code}) 打分{ai_score}{unit}"
                          f"（{basis}），低于阈值{threshold*100:.0f}{unit}，过滤")

            except Exception as e:
                print(f"  ⚠️ {code} 打分失败: {e}，保留原始推荐")
                candidate["ai_score"] = 50
                candidate["ai_score_basis"] = "error"
                candidate["ai_rule_score"] = 50
                candidate["ai_model"] = "error"
                scored.append(candidate)

            time.sleep(0.1)  # 限速

        # 按打分降序排列（两种 basis 都是 0~100 量纲，可直接比）
        scored.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

        print(f"[AI打分] 完成：{len(candidates)}只候选 → {len(scored)}只通过"
              f"（阈值{self.min_probability*100:.0f}分）")
        return scored

    def add_ai_info_to_message(self, message: str, entries: List[Dict]) -> str:
        """在推送消息中添加打分信息。

        按 ``ai_score_basis`` 分别措辞：
        - "model"      → 真模型概率，写「上涨概率」
        - "rule_based" → 规则打分，写「规则打分」，绝不写「上涨概率」
        """
        if not entries:
            return message

        has_model = any(e.get("ai_score_basis") == MODEL_SCORE_BASIS for e in entries)
        basis = MODEL_SCORE_BASIS if has_model else RULE_SCORE_BASIS

        if basis == MODEL_SCORE_BASIS:
            header = "🤖 AI智能打分（LightGBM 概率）："
        else:
            header = ("🤖 打分排序（规则打分 0~100，非上涨概率；"
                      "仓库暂无训练好的模型）：")

        ai_lines = ["", header]
        for e in entries:
            score = e.get("ai_score", e.get("ai_probability", 0) * 100)
            basis = e.get("ai_score_basis", RULE_SCORE_BASIS)
            model = e.get("ai_model", "unknown")

            if basis == MODEL_SCORE_BASIS:
                emoji, label = ("🟢", "高概率") if score >= 70 else \
                               (("🟡", "中概率") if score >= 55 else ("⚪", "低概率"))
                line = f"  {emoji} {e.get('name', '')}({e.get('code', '')})：" \
                       f"上涨概率{score:.1f}%（{label}）"
            else:
                emoji, label = ("🟢", "强") if score >= 75 else \
                               (("🟡", "中") if score >= 60 else ("⚪", "弱"))
                hits = e.get("ai_score_hits") or []
                hit_txt = ("，命中：" + "、".join(hits[:3])) if hits else ""
                line = f"  {emoji} {e.get('name', '')}({e.get('code', '')})：" \
                       f"规则打分{score:.0f}{hit_txt}（{label}，依据={model}）"
            ai_lines.append(line)

        return message + "\n".join(ai_lines)

    def get_scorer_info(self) -> Dict[str, Any]:
        """获取打分器信息（含当前打分依据，便于如实标注是模型还是规则）。"""
        if self.predictor is None:
            return {"status": "unavailable", "score_basis": "unavailable",
                    "min_probability": self.min_probability}
        try:
            model_info = self.predictor.get_model_info()
        except Exception as e:
            model_info = {"status": "error", "error": str(e)}
        return {
            "status": "active",
            "score_basis": model_info.get("score_basis", MODEL_SCORE_BASIS),
            "model_trained": model_info.get("model_trained", True),
            "min_probability": self.min_probability,
            "model_info": model_info,
        }


def init_ai_scorer(min_probability: float = 0.55) -> AIScorer:
    """初始化AI打分器。"""
    return AIScorer(min_probability=min_probability)
