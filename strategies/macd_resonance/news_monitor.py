# -*- coding: utf-8 -*-
"""消息面监控模块。

从东方财富获取个股公告和新闻，识别利好/利空消息：
- 业绩预告/快报（超预期=利好）
- 重大合同/订单
- 政策利好
- 股东增减持
- 分红送转
- 风险提示

消息面是重要的催化剂，但需要谨慎对待，避免追高。
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional
import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache", "news")
os.makedirs(CACHE_DIR, exist_ok=True)

# 东财公告API
ANNOUNCEMENT_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
PROXY_BASE = "https://macd-strategy-scheduler.fys2388.workers.dev"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}

# 利好关键词
POSITIVE_KEYWORDS = [
    "业绩预告", "业绩快报", "净利润增长", "营收增长", "超预期",
    "重大合同", "中标", "订单", "战略合作",
    "增持", "回购", "分红", "送转",
    "政策支持", "补贴", "税收优惠",
    "新产品", "新技术", "专利",
    "重组", "并购", "资产注入",
]

# 利空关键词
NEGATIVE_KEYWORDS = [
    "业绩下滑", "净利润下降", "亏损", "预亏",
    "减持", "清仓", "质押", "平仓",
    "立案", "调查", "处罚", "违规",
    "退市", "ST", "*ST",
    "诉讼", "仲裁", "担保",
    "停产", "安全事故", "环保处罚",
]


def get_announcements(stock_code: str, days: int = 7) -> List[Dict[str, Any]]:
    """获取个股最近N天的公告。

    Args:
        stock_code: 股票代码
        days: 最近天数

    Returns:
        公告列表，每项含标题、日期、类型
    """
    params = {
        "sr": -1,
        "page_size": 20,
        "page_index": 1,
        "ann_type": "A",
        "client_source": "web",
        "stock_list": stock_code,
        "f_node": 0,
        "s_node": 0,
    }

    # 优先使用Cloudflare Worker代理
    try:
        resp = requests.get(f"{PROXY_BASE}/proxy/news?code={stock_code}", headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data") and data["data"].get("list"):
            announcements = []
            for item in data["data"]["list"]:
                title = item.get("title", "")
                announcements.append({
                    "title": title,
                    "date": item.get("notice_date", ""),
                    "type": item.get("columns", [{}])[0].get("column_name", "") if item.get("columns") else "",
                    "sentiment": _classify_sentiment(title),
                })
            return announcements[:20]
    except Exception as e:
        print(f"[消息面] Worker代理获取{stock_code}失败: {e}")

    try:
        resp = requests.get(ANNOUNCEMENT_API, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        if data.get("data") and data["data"].get("list"):
            announcements = []
            for item in data["data"]["list"]:
                title = item.get("title", "")
                date = item.get("notice_date", "")[:10]
                announcements.append({
                    "title": title,
                    "date": date,
                    "type": item.get("columns", [{}])[0].get("column_name", ""),
                })
            return announcements
    except Exception as e:
        print(f"[消息面] {stock_code} 公告获取失败: {e}")
    return []


def analyze_news_sentiment(announcements: List[Dict]) -> Dict[str, Any]:
    """分析公告情感（利好/利空/中性）。

    Returns:
        {sentiment: positive/negative/neutral, positive_count, negative_count, details}
    """
    if not announcements:
        return {"sentiment": "neutral", "positive_count": 0, "negative_count": 0, "details": []}

    positive = []
    negative = []

    for ann in announcements:
        title = ann["title"]
        # 检查利好关键词
        for kw in POSITIVE_KEYWORDS:
            if kw in title:
                positive.append(ann)
                break
        # 检查利空关键词
        for kw in NEGATIVE_KEYWORDS:
            if kw in title:
                negative.append(ann)
                break

    if len(positive) > len(negative):
        sentiment = "positive"
    elif len(negative) > len(positive):
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "positive_titles": [a["title"] for a in positive[:3]],
        "negative_titles": [a["title"] for a in negative[:3]],
    }


def batch_get_news(stock_codes: List[str], days: int = 7) -> Dict[str, Dict]:
    """批量获取消息面分析。"""
    results = {}
    for code in stock_codes:
        announcements = get_announcements(code, days)
        results[code] = analyze_news_sentiment(announcements)
        time.sleep(0.1)
    return results


def filter_by_news(stock_codes: List[str],
                    allow_negative: bool = False) -> Dict[str, Any]:
    """消息面过滤。

    Args:
        stock_codes: 待过滤股票列表
        allow_negative: 是否允许有利空消息的股票

    Returns:
        {passed: [code], rejected: [{code, reason}], news: {code: analysis}}
    """
    news = batch_get_news(stock_codes)
    passed = []
    rejected = []

    for code in stock_codes:
        analysis = news.get(code, {})
        sentiment = analysis.get("sentiment", "neutral")

        if sentiment == "negative" and not allow_negative:
            rejected.append({
                "code": code,
                "reason": f"利空消息{analysis.get('negative_count', 0)}条",
                "details": analysis.get("negative_titles", []),
            })
        else:
            passed.append(code)

    return {"passed": passed, "rejected": rejected, "news": news}


def build_news_report(news: Dict[str, Dict], stock_code: str) -> str:
    """生成单只股票的消息面报告。"""
    analysis = news.get(stock_code, {})
    if not analysis:
        return ""

    sentiment = analysis.get("sentiment", "neutral")
    emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(sentiment, "⚪")
    label = {"positive": "利好", "negative": "利空", "neutral": "中性"}.get(sentiment, "中性")

    lines = [f"  📰 消息面：{emoji}{label}（利好{analysis.get('positive_count', 0)}条/利空{analysis.get('negative_count', 0)}条）"]
    if analysis.get("positive_titles"):
        for t in analysis["positive_titles"][:2]:
            lines.append(f"     🟢 {t[:30]}")
    if analysis.get("negative_titles"):
        for t in analysis["negative_titles"][:2]:
            lines.append(f"     🔴 {t[:30]}")
    return "\n".join(lines)
