# -*- coding: utf-8 -*-
"""用户反馈记录模块。

用户在豆包对话中给出的反馈会被记录，Agent每周优化时参考。
反馈类型：
- positive: 推荐不错/股票涨了/策略有效
- negative: 推荐不行/股票跌了/错过机会
- preference: 偏好调整（推荐太多/太少、想要某类股票等）
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FEEDBACK_FILE = os.path.join(BASE_DIR, "data", "user_feedback.jsonl")


def record_feedback(feedback_type: str, content: str, stock_code: str = "", stock_name: str = "") -> Dict:
    """记录一条用户反馈。

    Args:
        feedback_type: positive / negative / preference
        content: 反馈内容
        stock_code: 相关股票代码（可选）
        stock_name: 相关股票名称（可选）

    Returns:
        记录的反馈对象
    """
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": feedback_type,
        "content": content,
        "stock_code": stock_code,
        "stock_name": stock_name,
    }
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_feedback(days: int = 30) -> List[Dict]:
    """加载最近N天的用户反馈。"""
    if not os.path.exists(FEEDBACK_FILE):
        return []
    cutoff = (datetime.now() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    records = []
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    if str(rec.get("timestamp", "")) >= cutoff:
                        records.append(rec)
                except json.JSONDecodeError:
                    continue
    return records


def analyze_feedback(days: int = 30) -> Dict:
    """分析用户反馈，生成优化建议。"""
    records = load_feedback(days)
    if not records:
        return {"status": "no_feedback", "count": 0, "message": "暂无用户反馈"}

    positive = [r for r in records if r["type"] == "positive"]
    negative = [r for r in records if r["type"] == "negative"]
    preference = [r for r in records if r["type"] == "preference"]

    # 统计被负面反馈的股票
    neg_stocks = {}
    for r in negative:
        code = r.get("stock_code", "")
        if code:
            neg_stocks[code] = neg_stocks.get(code, 0) + 1

    # 统计偏好关键词
    pref_keywords = {}
    for r in preference:
        content = r.get("content", "")
        for kw in ["太多", "太少", "高位", "低位", "基本面", "技术面", "短线", "长线"]:
            if kw in content:
                pref_keywords[kw] = pref_keywords.get(kw, 0) + 1

    suggestions = []
    if len(negative) > len(positive) * 1.5:
        suggestions.append("负面反馈明显多于正面，建议收紧选股条件，提高最低得分阈值")
    if neg_stocks:
        worst = max(neg_stocks.items(), key=lambda x: x[1])
        suggestions.append(f"股票{worst[0]}被负面反馈{worst[1]}次，建议加入冷却期或降低权重")
    if "太多" in pref_keywords:
        suggestions.append("用户反馈推荐太多，建议减少每日推荐数量到3只")
    if "太少" in pref_keywords:
        suggestions.append("用户反馈推荐太少，建议放宽选股条件")

    return {
        "status": "ok",
        "total": len(records),
        "positive": len(positive),
        "negative": len(negative),
        "preference": len(preference),
        "negative_stocks": neg_stocks,
        "preference_keywords": pref_keywords,
        "suggestions": suggestions,
    }


if __name__ == "__main__":
    result = analyze_feedback()
    print(json.dumps(result, ensure_ascii=False, indent=2))
