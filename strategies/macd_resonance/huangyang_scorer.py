# -*- coding: utf-8 -*-
"""黄阳基本面五步法打分模块（融合黄阳价值投资体系）。

来源：@黄阳的学习分享 公司分析五步法
1. 商业模式：靠什么赚钱，是不是好生意
2. 竞争优势：有没有护城河
3. 财务质量：ROE、毛利率、负债率、现金流
4. 估值水平：PE、PB、PEG，是否便宜
5. 管理层：诚信、能力、分红、利润稳定性

设计原则：
- 基于可获取的公开财务数据（PE/PB/ROE/毛利率/负债率/增速）
- 不依赖付费LLM API，纯规则+模板，可在云端免费运行
- 每维0-20分，总分0-100分
- 60分以上=基本面良好，75分以上=基本面优秀
"""
from __future__ import annotations

import os
import json
from typing import Dict, Any, Optional, List, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============================================================
# 行业商业模式分类（黄阳视角：好生意 vs 一般生意）
# ============================================================
# 好生意：轻资产、高毛利、现金流好、客户粘性强
GOOD_BUSINESS_INDUSTRIES = {
    "食品饮料": {"model_score": 18, "reason": "消费刚需，品牌护城河，轻资产高毛利"},
    "医药": {"model_score": 17, "reason": "刚需+研发壁垒，高毛利"},
    "美容护理": {"model_score": 17, "reason": "高毛利消费，品牌溢价"},
    "计算机": {"model_score": 16, "reason": "轻资产软件，边际成本低"},
    "电子": {"model_score": 14, "reason": "科技成长，但周期性较强"},
    "通信": {"model_score": 13, "reason": "基础设施，现金流稳定"},
    "电力设备": {"model_score": 13, "reason": "新能源成长，但竞争激烈"},
    "国防军工": {"model_score": 12, "reason": "计划经济，订单稳定但毛利率一般"},
}

# 一般生意：重资产、低毛利、周期性强
NORMAL_BUSINESS_INDUSTRIES = {
    "银行": {"model_score": 12, "reason": "高杠杆经营，息差收入，稳健但增长慢"},
    "证券": {"model_score": 10, "reason": "强周期，靠天吃饭"},
    "保险": {"model_score": 11, "reason": "负债经营，投资收益波动大"},
    "房地产": {"model_score": 6, "reason": "重资产高杠杆，政策敏感"},
    "钢铁": {"model_score": 5, "reason": "重资产强周期，低毛利"},
    "煤炭": {"model_score": 8, "reason": "资源型，周期波动大"},
    "有色金属": {"model_score": 8, "reason": "资源型，价格周期"},
    "化工": {"model_score": 9, "reason": "重资产，周期波动"},
    "建筑装饰": {"model_score": 7, "reason": "重资产低毛利，垫资经营"},
    "交通运输": {"model_score": 10, "reason": "重资产，现金流稳定但增长慢"},
    "公用事业": {"model_score": 11, "reason": "稳定现金流，但增长有限"},
    "农林牧渔": {"model_score": 8, "reason": "靠天吃饭，周期波动"},
    "纺织服装": {"model_score": 9, "reason": "竞争激烈，低毛利"},
    "轻工制造": {"model_score": 9, "reason": "制造业，毛利一般"},
    "商贸零售": {"model_score": 8, "reason": "低毛利，竞争激烈"},
    "社会服务": {"model_score": 10, "reason": "消费服务，受经济周期影响"},
    "传媒": {"model_score": 11, "reason": "内容消费，但政策风险大"},
    "汽车": {"model_score": 10, "reason": "重资产，周期+竞争"},
    "机械设备": {"model_score": 10, "reason": "制造业，周期波动"},
}


class HuangYangScorer:
    """黄阳基本面五步法打分器。"""

    def __init__(self):
        self.industry_keywords = self._build_industry_keywords()

    def _build_industry_keywords(self) -> Dict[str, List[str]]:
        """构建行业关键词映射（用于从股票名称推断行业）。"""
        return {
            "银行": ["银行"],
            "证券": ["证券", "券商"],
            "保险": ["保险", "人寿", "平安"],
            "房地产": ["地产", "置业", "建设", "城建", "蛇口"],
            "医药": ["医药", "生物", "制药", "医疗", "健康", "药明", "恒瑞"],
            "电子": ["电子", "科技", "半导体", "芯片", "光电", "通富", "华天"],
            "计算机": ["软件", "信息", "网络", "数据", "智能", "科大", "用友"],
            "电力设备": ["电气", "电力", "新能源", "光伏", "电池", "宁德", "阳光"],
            "机械设备": ["机械", "设备", "重工", "精密", "三一", "汇川"],
            "汽车": ["汽车", "车业", "零部件", "轮胎", "比亚迪", "长城"],
            "食品饮料": ["食品", "饮料", "酒业", "乳业", "调味", "茅台", "伊利"],
            "化工": ["化工", "化学", "新材", "材料", "万华", "荣盛"],
            "有色金属": ["有色", "金属", "黄金", "铜业", "铝业", "紫金"],
            "钢铁": ["钢铁", "特钢", "宝钢"],
            "煤炭": ["煤业", "煤炭", "能源", "神华"],
            "公用事业": ["电力", "水务", "燃气", "环保", "长江电力"],
            "交通运输": ["运输", "物流", "航空", "港口", "航运"],
            "建筑装饰": ["建筑", "装饰", "工程", "中建"],
            "农林牧渔": ["农业", "牧业", "渔业", "种业", "养殖", "牧原"],
            "纺织服装": ["纺织", "服装", "服饰", "家纺"],
            "轻工制造": ["造纸", "包装", "家具"],
            "商贸零售": ["商业", "零售", "百货", "超市", "永辉"],
            "社会服务": ["旅游", "酒店", "餐饮", "教育", "中青旅"],
            "传媒": ["传媒", "文化", "影视", "游戏", "出版", "芒果", "分众"],
            "通信": ["通信", "通讯", "电信", "中兴", "烽火", "亨通", "中天"],
            "国防军工": ["军工", "航天", "航空", "兵器", "船舶", "中船", "中航"],
            "美容护理": ["美妆", "护理", "日化", "珀莱雅"],
        }

    def infer_industry(self, name: str) -> str:
        """从股票名称推断行业。"""
        for industry, keywords in self.industry_keywords.items():
            if any(kw in name for kw in keywords):
                return industry
        return "综合"

    # ============================================================
    # 第一维：商业模式（0-20分）
    # ============================================================
    def score_business_model(self, name: str, gross_margin: float = 0) -> Dict[str, Any]:
        """商业模式打分。

        黄阳观点：好生意=轻资产+高毛利+现金流好+客户粘性
        评分逻辑：
        - 行业属性决定基础分（好生意15-18分，一般生意5-12分）
        - 毛利率>40%加2分（高毛利=好生意特征）
        - 毛利率20-40%加1分
        - 毛利率<10%减2分
        """
        industry = self.infer_industry(name)

        if industry in GOOD_BUSINESS_INDUSTRIES:
            base = GOOD_BUSINESS_INDUSTRIES[industry]["model_score"]
            reason = GOOD_BUSINESS_INDUSTRIES[industry]["reason"]
        elif industry in NORMAL_BUSINESS_INDUSTRIES:
            base = NORMAL_BUSINESS_INDUSTRIES[industry]["model_score"]
            reason = NORMAL_BUSINESS_INDUSTRIES[industry]["reason"]
        else:
            base = 10
            reason = "综合行业，商业模式一般"

        # 毛利率调整
        margin_adjust = 0
        if gross_margin > 40:
            margin_adjust = 2
        elif gross_margin > 20:
            margin_adjust = 1
        elif gross_margin > 0 and gross_margin < 10:
            margin_adjust = -2

        score = max(0, min(20, base + margin_adjust))
        return {
            "score": score,
            "industry": industry,
            "base_score": base,
            "margin_adjust": margin_adjust,
            "reason": reason,
        }

    # ============================================================
    # 第二维：竞争优势/护城河（0-20分）
    # ============================================================
    def score_competitive_advantage(self, roe: float = 0,
                                     gross_margin: float = 0,
                                     name: str = "") -> Dict[str, Any]:
        """竞争优势打分。

        黄阳观点：护城河=品牌/技术/成本/网络效应
        可量化指标：
        - ROE持续>15% = 有护城河（高资本回报）
        - 毛利率>30%且稳定 = 定价权
        - 行业龙头 = 规模优势
        """
        score = 8  # 基础分
        reasons = []

        # ROE是护城河最直接的量化指标
        if roe >= 20:
            score += 8
            reasons.append(f"ROE {roe:.1f}%≥20%，强护城河")
        elif roe >= 15:
            score += 6
            reasons.append(f"ROE {roe:.1f}%≥15%，有一定护城河")
        elif roe >= 10:
            score += 3
            reasons.append(f"ROE {roe:.1f}%≥10%，一般")
        elif roe > 0:
            reasons.append(f"ROE {roe:.1f}%<10%，竞争优势弱")
        else:
            score -= 2
            reasons.append("ROE为负，无竞争优势")

        # 毛利率=定价权
        if gross_margin >= 40:
            score += 4
            reasons.append(f"毛利率{gross_margin:.1f}%≥40%，强定价权")
        elif gross_margin >= 30:
            score += 2
            reasons.append(f"毛利率{gross_margin:.1f}%≥30%，有定价权")
        elif gross_margin > 0 and gross_margin < 15:
            score -= 2
            reasons.append(f"毛利率{gross_margin:.1f}%<15%，无定价权")

        score = max(0, min(20, score))
        return {
            "score": score,
            "roe": roe,
            "gross_margin": gross_margin,
            "reasons": reasons,
        }

    # ============================================================
    # 第三维：财务质量（0-20分）
    # ============================================================
    def score_financial_quality(self, roe: float = 0, gross_margin: float = 0,
                                 net_margin: float = 0, debt_ratio: float = 0,
                                 revenue_growth: float = 0,
                                 profit_growth: float = 0) -> Dict[str, Any]:
        """财务质量打分。

        黄阳观点：好公司=高ROE+稳增长+低负债+健康现金流
        评分维度：
        - ROE水平（5分）
        - 毛利率/净利率（4分）
        - 负债率（4分）
        - 营收/利润增速（7分）
        """
        score = 0
        reasons = []

        # ROE（5分）
        if roe >= 20:
            score += 5
            reasons.append(f"ROE {roe:.1f}%优秀")
        elif roe >= 15:
            score += 4
            reasons.append(f"ROE {roe:.1f}%良好")
        elif roe >= 10:
            score += 3
            reasons.append(f"ROE {roe:.1f}%一般")
        elif roe >= 5:
            score += 1
            reasons.append(f"ROE {roe:.1f}%偏弱")
        else:
            reasons.append(f"ROE {roe:.1f}%差")

        # 毛利率+净利率（4分）
        if gross_margin >= 30 and net_margin >= 10:
            score += 4
            reasons.append("高毛利+高净利率")
        elif gross_margin >= 20:
            score += 2
            reasons.append("毛利率尚可")
        elif gross_margin > 0:
            score += 1
            reasons.append("毛利率偏低")

        # 负债率（4分）
        if 0 < debt_ratio <= 30:
            score += 4
            reasons.append(f"负债率{debt_ratio:.1f}%健康")
        elif debt_ratio <= 50:
            score += 3
            reasons.append(f"负债率{debt_ratio:.1f}%尚可")
        elif debt_ratio <= 70:
            score += 1
            reasons.append(f"负债率{debt_ratio:.1f}%偏高")
        elif debt_ratio > 70:
            reasons.append(f"负债率{debt_ratio:.1f}%过高")

        # 营收+利润增速（7分）
        growth_score = 0
        if revenue_growth >= 20:
            growth_score += 3
            reasons.append(f"营收增速{revenue_growth:.1f}%高增长")
        elif revenue_growth >= 10:
            growth_score += 2
            reasons.append(f"营收增速{revenue_growth:.1f}%稳健")
        elif revenue_growth >= 0:
            growth_score += 1
            reasons.append(f"营收增速{revenue_growth:.1f}%微增")
        else:
            reasons.append(f"营收增速{revenue_growth:.1f}%下滑")

        if profit_growth >= 20:
            growth_score += 4
            reasons.append(f"利润增速{profit_growth:.1f}%高增长")
        elif profit_growth >= 10:
            growth_score += 3
            reasons.append(f"利润增速{profit_growth:.1f}%稳健")
        elif profit_growth >= 0:
            growth_score += 1
            reasons.append(f"利润增速{profit_growth:.1f}%微增")
        else:
            reasons.append(f"利润增速{profit_growth:.1f}%下滑")

        score += min(7, growth_score)
        score = max(0, min(20, score))
        return {
            "score": score,
            "reasons": reasons,
        }

    # ============================================================
    # 第四维：估值水平（0-20分）
    # ============================================================
    def score_valuation(self, pe: float = 0, pb: float = 0,
                         profit_growth: float = 0) -> Dict[str, Any]:
        """估值打分。

        黄阳观点：好公司+好价格=好投资
        评分逻辑：越便宜分越高
        - PE<15 = 低估（满分附近）
        - PE 15-25 = 合理
        - PE 25-40 = 偏高
        - PE>40 = 高估
        - PB<3 = 加分
        - PEG<1 = 加分（增长消化估值）
        """
        score = 10  # 基础分
        reasons = []

        # PE评分
        if pe <= 0:
            score -= 3
            reasons.append("PE为负（亏损），无法估值")
        elif pe <= 15:
            score += 6
            reasons.append(f"PE {pe:.1f}<15，低估")
        elif pe <= 25:
            score += 3
            reasons.append(f"PE {pe:.1f} 15-25，合理")
        elif pe <= 40:
            score -= 1
            reasons.append(f"PE {pe:.1f} 25-40，偏高")
        elif pe <= 80:
            score -= 4
            reasons.append(f"PE {pe:.1f} 40-80，高估")
        else:
            score -= 6
            reasons.append(f"PE {pe:.1f}>80，严重高估")

        # PB评分
        if 0 < pb <= 2:
            score += 3
            reasons.append(f"PB {pb:.1f}<2，低估")
        elif pb <= 4:
            score += 1
            reasons.append(f"PB {pb:.1f} 2-4，合理")
        elif pb > 8:
            score -= 2
            reasons.append(f"PB {pb:.1f}>8，偏高")

        # PEG（增长消化估值）
        if pe > 0 and profit_growth > 0:
            peg = pe / profit_growth
            if peg < 1:
                score += 2
                reasons.append(f"PEG {peg:.2f}<1，增长可消化估值")
            elif peg > 2:
                score -= 1
                reasons.append(f"PEG {peg:.2f}>2，估值偏贵")

        score = max(0, min(20, score))
        return {
            "score": score,
            "pe": pe,
            "pb": pb,
            "reasons": reasons,
        }

    # ============================================================
    # 第五维：管理层/经营稳定性（0-20分）
    # ============================================================
    def score_management(self, revenue_growth: float = 0,
                          profit_growth: float = 0,
                          debt_ratio: float = 0,
                          name: str = "") -> Dict[str, Any]:
        """管理层打分（间接量化）。

        黄阳观点：好管理层=诚信+能力+股东回报
        可量化间接指标：
        - 利润持续正增长 = 管理层执行力强
        - 营收和利润同步增长 = 经营健康（不是靠压缩成本）
        - 负债率稳定 = 财务稳健
        - 行业龙头 = 管理层能力证明
        """
        score = 10  # 基础分
        reasons = []

        # 利润增长稳定性
        if profit_growth >= 15:
            score += 4
            reasons.append(f"利润增速{profit_growth:.1f}%，管理层执行力强")
        elif profit_growth >= 5:
            score += 2
            reasons.append(f"利润增速{profit_growth:.1f}%，经营稳健")
        elif profit_growth >= 0:
            reasons.append(f"利润增速{profit_growth:.1f}%，增长乏力")
        else:
            score -= 3
            reasons.append(f"利润下滑{profit_growth:.1f}%，管理层需观察")

        # 营收利润同步性（健康增长 vs 压缩成本）
        if revenue_growth > 0 and profit_growth > 0:
            if abs(revenue_growth - profit_growth) < 10:
                score += 3
                reasons.append("营收利润同步增长，经营健康")
            else:
                score += 1
                reasons.append("营收利润均增长但不同步")
        elif revenue_growth > 0 > profit_growth:
            score -= 2
            reasons.append("增收不增利，可能靠压缩成本")

        # 负债率稳定性（间接反映管理层财务风格）
        if 0 < debt_ratio <= 40:
            score += 2
            reasons.append(f"负债率{debt_ratio:.1f}%，财务风格稳健")
        elif debt_ratio > 70:
            score -= 2
            reasons.append(f"负债率{debt_ratio:.1f}%，财务风格激进")

        score = max(0, min(20, score))
        return {
            "score": score,
            "reasons": reasons,
        }

    # ============================================================
    # 综合五维打分
    # ============================================================
    def score(self, name: str, fundamental: Dict[str, Any] = None) -> Dict[str, Any]:
        """黄阳五步法综合打分。

        Args:
            name: 股票名称
            fundamental: 基本面数据 {pe, pb, roe, gross_margin, net_margin,
                         debt_ratio, revenue_growth, profit_growth}

        Returns:
            {total_score, grade, dimensions: {business_model, competitive_advantage,
             financial_quality, valuation, management}, summary}
        """
        if fundamental is None:
            fundamental = {}

        pe = float(fundamental.get("pe", 0) or 0)
        pb = float(fundamental.get("pb", 0) or 0)
        roe = float(fundamental.get("roe", 0) or 0)
        gross_margin = float(fundamental.get("gross_margin", 0) or 0)
        net_margin = float(fundamental.get("net_margin", 0) or 0)
        debt_ratio = float(fundamental.get("debt_ratio", 0) or 0)
        revenue_growth = float(fundamental.get("revenue_growth", 0) or 0)
        profit_growth = float(fundamental.get("profit_growth", 0) or 0)

        # 数据质量修复（PE异常高时标记）
        if pe > 1000:
            pe = pe / 100  # 东财API单位问题修复

        # 五维打分
        d1 = self.score_business_model(name, gross_margin)
        d2 = self.score_competitive_advantage(roe, gross_margin, name)
        d3 = self.score_financial_quality(roe, gross_margin, net_margin,
                                           debt_ratio, revenue_growth, profit_growth)
        d4 = self.score_valuation(pe, pb, profit_growth)
        d5 = self.score_management(revenue_growth, profit_growth, debt_ratio, name)

        total = d1["score"] + d2["score"] + d3["score"] + d4["score"] + d5["score"]

        # 评级
        if total >= 80:
            grade = "优秀"
        elif total >= 65:
            grade = "良好"
        elif total >= 50:
            grade = "一般"
        elif total >= 35:
            grade = "偏弱"
        else:
            grade = "差"

        # 核心结论
        strengths = []
        weaknesses = []
        if d1["score"] >= 15:
            strengths.append(f"商业模式好（{d1['industry']}）")
        if d2["score"] >= 14:
            strengths.append("有竞争优势")
        if d3["score"] >= 14:
            strengths.append("财务质量好")
        if d4["score"] >= 14:
            strengths.append("估值便宜")
        if d5["score"] >= 14:
            strengths.append("管理层靠谱")

        if d1["score"] <= 8:
            weaknesses.append("商业模式一般")
        if d2["score"] <= 8:
            weaknesses.append("竞争优势弱")
        if d3["score"] <= 8:
            weaknesses.append("财务质量差")
        if d4["score"] <= 6:
            weaknesses.append("估值过高")
        if d5["score"] <= 8:
            weaknesses.append("管理层需观察")

        summary_parts = []
        if strengths:
            summary_parts.append(f"优势：{'、'.join(strengths[:3])}")
        if weaknesses:
            summary_parts.append(f"风险：{'、'.join(weaknesses[:3])}")
        summary = "；".join(summary_parts) if summary_parts else "基本面中性"

        return {
            "total_score": total,
            "grade": grade,
            "dimensions": {
                "business_model": d1,
                "competitive_advantage": d2,
                "financial_quality": d3,
                "valuation": d4,
                "management": d5,
            },
            "strengths": strengths,
            "weaknesses": weaknesses,
            "summary": summary,
        }

    def build_score_line(self, name: str, fundamental: Dict = None) -> str:
        """生成一行打分摘要（用于推送）。"""
        result = self.score(name, fundamental)
        d = result["dimensions"]
        return (
            f"黄阳五维：{result['total_score']}分({result['grade']}) "
            f"[模式{d['business_model']['score']}/护城河{d['competitive_advantage']['score']}"
            f"/财务{d['financial_quality']['score']}/估值{d['valuation']['score']}"
            f"/管理{d['management']['score']}]"
        )


# 全局单例
_scorer = None

def get_huangyang_scorer() -> HuangYangScorer:
    global _scorer
    if _scorer is None:
        _scorer = HuangYangScorer()
    return _scorer
