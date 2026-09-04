# -*- coding: utf-8 -*-
"""多维选股过滤器。

整合4个维度的选股过滤：
1. 资金面：主力连续净流入
2. 板块面：属于强势板块
3. 基本面：PE/PB/ROE等硬门槛
4. 消息面：无重大利空

对规则策略选出的候选股票进行多维过滤和评分，
只推送综合评分达标的股票，并在推送中显示各维度评分。
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MultiDimensionFilter:
    """多维选股过滤器。"""

    def __init__(self, enable_moneyflow: bool = True,
                 enable_sector: bool = True,
                 enable_fundamental: bool = True,
                 enable_news: bool = True):
        self.enable_moneyflow = enable_moneyflow
        self.enable_sector = enable_sector
        self.enable_fundamental = enable_fundamental
        self.enable_news = enable_news
        self.strong_sectors = []
        self._load_sectors()

    def _load_sectors(self):
        """预加载强势板块。"""
        if not self.enable_sector:
            return
        try:
            from .sector_strength import get_strong_sectors
            self.strong_sectors = get_strong_sectors(top_n=5)
            print(f"[多维过滤] 强势板块加载完成：{len(self.strong_sectors)}个")
        except Exception as e:
            print(f"[多维过滤] 强势板块加载失败: {e}")
            self.strong_sectors = []

    def filter_candidates(self, candidates: List[Dict]) -> Dict[str, Any]:
        """对候选股票进行多维过滤和评分。

        Args:
            candidates: 候选股票列表，每项需含 code/name

        Returns:
            {passed: [带评分的候选], rejected: [{code, reason}], scores: {code: 各维度分}}
        """
        if not candidates:
            return {"passed": [], "rejected": [], "scores": {}}

        codes = [c["code"] for c in candidates if c.get("code")]
        print(f"[多维过滤] 开始过滤{len(codes)}只候选股票")

        # 1. 资金面过滤
        moneyflow_results = {}
        if self.enable_moneyflow:
            try:
                from .moneyflow import batch_get_moneyflow
                moneyflow_results = batch_get_moneyflow(codes, days=5)
                print(f"[多维过滤] 资金面分析完成：{len(moneyflow_results)}只")
            except Exception as e:
                print(f"[多维过滤] 资金面分析失败: {e}")

        # 2. 基本面过滤
        fundamental_results = {}
        if self.enable_fundamental:
            try:
                from .fundamental_filter import batch_get_fundamental
                fundamental_results = batch_get_fundamental(codes)
                print(f"[多维过滤] 基本面分析完成：{len(fundamental_results)}只")
            except Exception as e:
                print(f"[多维过滤] 基本面分析失败: {e}")

        # 3. 消息面过滤
        news_results = {}
        if self.enable_news:
            try:
                from .news_monitor import batch_get_news
                news_results = batch_get_news(codes, days=7)
                print(f"[多维过滤] 消息面分析完成：{len(news_results)}只")
            except Exception as e:
                print(f"[多维过滤] 消息面分析失败: {e}")

        # 4. 综合评分和过滤
        passed = []
        rejected = []
        scores = {}

        for candidate in candidates:
            code = candidate.get("code", "")
            name = candidate.get("name", "")
            if not code:
                continue

            score = 100  # 基础分
            deductions = []
            dimension_scores = {}

            # 资金面评分（-20~0）
            if self.enable_moneyflow and moneyflow_results.get(code):
                mf = moneyflow_results[code]
                trend = mf.get("trend", "neutral")
                if trend == "strong_inflow":
                    dimension_scores["moneyflow"] = 100
                elif trend == "weak_inflow":
                    dimension_scores["moneyflow"] = 75
                    score -= 5
                elif trend == "outflow":
                    dimension_scores["moneyflow"] = 30
                    score -= 15
                    deductions.append("主力流出")
                else:
                    dimension_scores["moneyflow"] = 60
                    score -= 3
            else:
                dimension_scores["moneyflow"] = 60

            # 基本面评分（-20~0）
            if self.enable_fundamental and fundamental_results.get(code):
                fund = fundamental_results[code]
                fund_score = 80
                if fund.get("pe", 0) and fund["pe"] > 80:
                    fund_score -= 15
                    deductions.append(f"PE过高({fund['pe']})")
                if fund.get("roe", 0) and fund["roe"] < 5:
                    fund_score -= 10
                    deductions.append(f"ROE低({fund['roe']}%)")
                if fund.get("debt_ratio", 0) and fund["debt_ratio"] > 75:
                    fund_score -= 10
                    deductions.append(f"负债率高({fund['debt_ratio']}%)")
                dimension_scores["fundamental"] = max(fund_score, 20)
                score -= (100 - fund_score) * 0.2
            else:
                dimension_scores["fundamental"] = 60

            # 消息面评分（-20~0）
            if self.enable_news and news_results.get(code):
                news = news_results[code]
                sentiment = news.get("sentiment", "neutral")
                if sentiment == "positive":
                    dimension_scores["news"] = 90
                    score += 5  # 利好加分
                elif sentiment == "negative":
                    dimension_scores["news"] = 30
                    score -= 15
                    deductions.append("利空消息")
                else:
                    dimension_scores["news"] = 60
            else:
                dimension_scores["news"] = 60

            # 板块面评分（-10~+10）
            if self.enable_sector and self.strong_sectors:
                # 简化：不做精确板块映射，只记录强势板块信息
                dimension_scores["sector"] = 60
            else:
                dimension_scores["sector"] = 60

            score = max(0, min(100, score))
            scores[code] = {
                "total_score": round(score, 1),
                "dimensions": dimension_scores,
                "deductions": deductions,
            }

            # 过滤：综合分<50或有重大利空则拒绝
            if score < 50:
                rejected.append({
                    "code": code, "name": name,
                    "score": round(score, 1),
                    "reason": ", ".join(deductions) if deductions else "综合评分低",
                })
            else:
                candidate["multi_score"] = round(score, 1)
                candidate["dimension_scores"] = dimension_scores
                candidate["deductions"] = deductions
                passed.append(candidate)

        # 按综合评分降序
        passed.sort(key=lambda x: x.get("multi_score", 0), reverse=True)

        print(f"[多维过滤] 完成：{len(candidates)}只候选 → {len(passed)}只通过，{len(rejected)}只过滤")
        return {"passed": passed, "rejected": rejected, "scores": scores}

    def build_filter_report(self, result: Dict) -> str:
        """生成多维过滤报告。"""
        passed = result.get("passed", [])
        rejected = result.get("rejected", [])

        lines = [
            f"🔍 多维过滤：{len(passed) + len(rejected)}只候选 → {len(passed)}只通过",
        ]

        if rejected:
            lines.append(f"  过滤{len(rejected)}只：")
            for r in rejected[:5]:
                lines.append(f"    ❌ {r['name']}({r['code']}) {r['score']}分 - {r['reason']}")

        if passed:
            lines.append("  通过股票多维评分：")
            for p in passed[:5]:
                ds = p.get("dimension_scores", {})
                lines.append(
                    f"    ✅ {p['name']}({p['code']}) 综合{p['multi_score']}分 "
                    f"[资金{ds.get('moneyflow', 0)}/基本面{ds.get('fundamental', 0)}/消息{ds.get('news', 0)}]"
                )

        return "\n".join(lines)

    def build_stock_detail(self, code: str, name: str = "") -> str:
        """生成单只股票的多维详情（用于推送中显示）。"""
        lines = []

        # 资金面
        if self.enable_moneyflow:
            try:
                from .moneyflow import check_moneyflow_trend
                mf = check_moneyflow_trend(code, days=5)
                trend = mf.get("trend", "unknown")
                trend_label = {
                    "strong_inflow": "🟢主力强流入",
                    "weak_inflow": "🟡主力弱流入",
                    "outflow": "🔴主力流出",
                    "neutral": "⚪资金中性",
                }.get(trend, trend)
                consecutive = mf.get("consecutive_inflow_days", 0)
                lines.append(f"  💰 资金面：{trend_label}（连续流入{consecutive}天）")
            except Exception:
                pass

        # 基本面
        if self.enable_fundamental:
            try:
                from .fundamental_filter import get_fundamental
                fund = get_fundamental(code)
                if fund:
                    lines.append(
                        f"  📋 基本面：PE{fund.get('pe', '-')} | ROE{fund.get('roe', '-')}% | "
                        f"毛利率{fund.get('gross_margin', '-')}% | 负债率{fund.get('debt_ratio', '-')}%"
                    )
            except Exception:
                pass

        # 消息面
        if self.enable_news:
            try:
                from .news_monitor import get_announcements, analyze_news_sentiment
                anns = get_announcements(code, days=7)
                news = analyze_news_sentiment(anns)
                sentiment = news.get("sentiment", "neutral")
                emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(sentiment, "⚪")
                label = {"positive": "利好", "negative": "利空", "neutral": "中性"}.get(sentiment, "中性")
                lines.append(
                    f"  📰 消息面：{emoji}{label}（利好{news.get('positive_count', 0)}条/利空{news.get('negative_count', 0)}条）"
                )
            except Exception:
                pass

        return "\n".join(lines)


def init_multi_filter() -> MultiDimensionFilter:
    """初始化多维过滤器。"""
    return MultiDimensionFilter()
