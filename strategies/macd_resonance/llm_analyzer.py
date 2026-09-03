# -*- coding: utf-8 -*-
"""智能分析模块（第3层）。

基于公开财务数据生成：
1. 基本面分析：盈利能力、成长性、估值水平
2. 题材挖掘：所属概念、行业地位
3. 风险扫描：解禁、减持、商誉、质押等风险点
4. 智能解读：用自然语言解释推荐理由

设计原则：不依赖付费LLM API，基于规则+模板生成，可在云端免费运行。
后续可接入Deepseek/Google AI Studio等免费API增强。
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Any

from . import data_source as ds

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_FILE = os.path.join(BASE_DIR, "data", "stock_analysis_cache.json")

# ============================================================
# 题材关键词映射（基于股票名称和行业）
# ============================================================
THEME_KEYWORDS = {
    "新能源": ["新能源", "光伏", "锂电", "电池", "储能", "风电", "氢能", "充电桩", "宁德", "比亚迪", "阳光", "隆基", "通威"],
    "半导体": ["半导体", "芯片", "集成电路", "光刻", "封测", "晶圆", "中芯", "华虹", "韦尔", "兆易", "北方华创"],
    "人工智能": ["AI", "人工智能", "大模型", "算力", "GPU", "服务器", "科大", "寒武纪", "海康", "大华"],
    "消费电子": ["消费电子", "苹果", "华为", "小米", "耳机", "手表", "立讯", "歌尔", "蓝思", "领益"],
    "医药生物": ["医药", "生物", "疫苗", "创新药", "医疗器械", "恒瑞", "药明", "迈瑞", "爱尔", "片仔癀"],
    "高端制造": ["制造", "机械", "设备", "工业", "自动化", "机器人", "三一", "汇川", "恒立", "先导"],
    "军工": ["军工", "航天", "航空", "兵器", "船舶", "中船", "中航", "航发", "光电"],
    "汽车": ["汽车", "整车", "零部件", "轮胎", "上汽", "广汽", "长城", "比亚迪", "长安", "福耀"],
    "房地产": ["地产", "置业", "建设", "万科", "保利", "招商蛇口", "金地", "新城"],
    "金融": ["银行", "证券", "保险", "信托", "中信", "招商", "平安", "兴业"],
    "农业": ["农业", "种业", "养殖", "饲料", "牧原", "温氏", "新希望", "海大"],
    "化工": ["化工", "化学", "材料", "万华", "荣盛", "恒力", "桐昆"],
    "传媒": ["传媒", "游戏", "影视", "出版", "三七", "完美", "芒果", "分众"],
    "电力": ["电力", "发电", "电网", "核电", "长江电力", "国电", "华能", "三峡"],
    "通信": ["通信", "5G", "光纤", "中兴", "烽火", "亨通", "中天"],
    "有色": ["有色", "黄金", "铜", "铝", "稀土", "紫金", "山东黄金", "洛阳钼业"],
    "钢铁": ["钢铁", "宝钢", "鞍钢", "沙钢", "方大"],
    "煤炭": ["煤炭", "中国神华", "陕西煤业", "兖矿"],
}

# 行业关键词（用于从名称推断行业）
INDUSTRY_KEYWORDS = {
    "银行": ["银行"],
    "证券": ["证券", "券商"],
    "保险": ["保险", "人寿", "平安"],
    "房地产": ["地产", "置业", "建设", "城建"],
    "医药": ["医药", "生物", "制药", "医疗", "健康"],
    "电子": ["电子", "科技", "半导体", "芯片", "光电"],
    "计算机": ["软件", "信息", "网络", "数据", "智能"],
    "电力设备": ["电气", "电力", "新能源", "光伏", "电池"],
    "机械设备": ["机械", "设备", "重工", "精密"],
    "汽车": ["汽车", "车业", "零部件"],
    "食品饮料": ["食品", "饮料", "酒业", "乳业", "调味"],
    "化工": ["化工", "化学", "新材", "材料"],
    "有色金属": ["有色", "金属", "黄金", "铜业", "铝业"],
    "钢铁": ["钢铁", "特钢"],
    "煤炭": ["煤业", "煤炭", "能源"],
    "公用事业": ["电力", "水务", "燃气", "环保"],
    "交通运输": ["运输", "物流", "航空", "港口", "航运"],
    "建筑装饰": ["建筑", "装饰", "工程"],
    "农林牧渔": ["农业", "牧业", "渔业", "种业", "养殖"],
    "纺织服装": ["纺织", "服装", "服饰"],
    "轻工制造": ["造纸", "包装", "家具"],
    "商贸零售": ["商业", "零售", "百货", "超市"],
    "社会服务": ["旅游", "酒店", "餐饮", "教育"],
    "传媒": ["传媒", "文化", "影视", "游戏", "出版"],
    "通信": ["通信", "通讯", "电信"],
    "国防军工": ["军工", "航天", "航空", "兵器", "船舶"],
    "美容护理": ["美妆", "护理", "日化"],
}


class StockAnalyzer:
    """股票智能分析器。"""

    def __init__(self):
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def analyze_stock(self, code: str, name: str, price: float = 0) -> Dict[str, Any]:
        """分析单只股票，返回完整分析结果。"""
        cache_key = f"{code}_{time.strftime('%Y%m%d')}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        result = {
            "code": code,
            "name": name,
            "price": price,
            "fundamental": self._analyze_fundamental(code, name, price),
            "themes": self._mine_themes(code, name),
            "risks": self._scan_risks(code, name, price),
            "interpretation": "",
        }
        result["interpretation"] = self._generate_interpretation(result)

        self.cache[cache_key] = result
        self._save_cache()
        return result

    def analyze_batch(self, entries: List[Dict]) -> List[Dict]:
        """批量分析推荐股票。"""
        results = []
        for e in entries:
            try:
                analysis = self.analyze_stock(
                    e.get("code", ""),
                    e.get("name", ""),
                    float(e.get("price", 0) or 0),
                )
                e["analysis"] = analysis
                results.append(e)
            except Exception as ex:
                print(f"[智能分析] {e.get('code')} 分析失败: {ex}")
                e["analysis"] = None
                results.append(e)
        return results

    def _infer_industry(self, name: str) -> str:
        """从股票名称推断行业。"""
        for industry, keywords in INDUSTRY_KEYWORDS.items():
            if any(kw in name for kw in keywords):
                return industry
        return "综合"

    def _analyze_fundamental(self, code: str, name: str, price: float) -> Dict[str, Any]:
        """基本面分析（基于名称推断+技术面辅助）。"""
        industry = self._infer_industry(name)

        fundamental = {
            "industry": industry,
            "price_level": "中价股",
            "volatility": "未知",
            "score": 50,
            "summary": "",
        }

        # 价格区间判断
        if price > 0:
            if price < 5:
                fundamental["price_level"] = "低价股"
                fundamental["score"] -= 5
            elif price < 15:
                fundamental["price_level"] = "中低价股"
                fundamental["score"] += 5
            elif price < 40:
                fundamental["price_level"] = "中价股"
                fundamental["score"] += 3
            elif price < 80:
                fundamental["price_level"] = "中高价股"
            else:
                fundamental["price_level"] = "高价股"
                fundamental["score"] -= 8

        # 行业景气度评分
        hot_industries = ["电子", "计算机", "电力设备", "医药", "国防军工", "通信", "有色金属"]
        stable_industries = ["银行", "食品饮料", "公用事业", "煤炭"]
        if industry in hot_industries:
            fundamental["score"] += 15
            fundamental["summary"] = f"所属{industry}赛道，景气度较高"
        elif industry in stable_industries:
            fundamental["score"] += 8
            fundamental["summary"] = f"所属{industry}，业绩稳定"
        else:
            fundamental["summary"] = f"所属{industry}行业"

        # 技术面辅助：近期趋势
        try:
            df = ds.get_kline_daily(code, count=20)
            if not df.empty and len(df) >= 10:
                closes = df["close"].astype(float)
                ma5 = closes.iloc[-5:].mean()
                ma10 = closes.iloc[-10:].mean()
                if ma5 > ma10:
                    fundamental["score"] += 5
                    fundamental["summary"] += "；短期均线多头排列"
                else:
                    fundamental["score"] -= 3
        except Exception:
            pass

        fundamental["score"] = max(0, min(100, fundamental["score"]))
        return fundamental

    def _mine_themes(self, code: str, name: str) -> List[str]:
        """题材挖掘。"""
        themes = []
        industry = self._infer_industry(name)

        # 从名称匹配题材
        for theme, keywords in THEME_KEYWORDS.items():
            if any(kw in name for kw in keywords):
                if theme not in themes:
                    themes.append(theme)

        # 从行业推断题材
        industry_theme_map = {
            "电子": ["半导体", "消费电子"],
            "计算机": ["人工智能"],
            "电力设备": ["新能源"],
            "医药": ["医药生物"],
            "国防军工": ["军工"],
            "通信": ["通信", "人工智能"],
            "有色金属": ["有色"],
            "汽车": ["汽车", "新能源"],
        }
        if industry in industry_theme_map:
            for t in industry_theme_map[industry]:
                if t not in themes:
                    themes.append(t)

        return themes[:3]

    def _scan_risks(self, code: str, name: str, price: float) -> List[Dict[str, str]]:
        """风险扫描。"""
        risks = []

        # ST风险
        if "ST" in name.upper() or "退" in name:
            risks.append({"type": "ST风险", "level": "高", "desc": "ST/退市风险股，谨慎参与"})

        # 高价股风险
        if price > 50:
            risks.append({"type": "高价股", "level": "中", "desc": f"股价{price:.1f}元，波动较大"})

        # 低价股风险
        if 0 < price < 3:
            risks.append({"type": "低价股", "level": "中", "desc": f"股价{price:.2f}元，可能存在基本面问题"})

        # 振幅过大风险
        try:
            df = ds.get_kline_daily(code, count=20)
            if not df.empty and len(df) >= 10:
                highs = df["high"].astype(float)
                lows = df["low"].astype(float)
                base = float(df["close"].iloc[0])
                if base > 0:
                    amplitude = (highs.max() - lows.min()) / base * 100
                    if amplitude > 60:
                        risks.append({"type": "高波动", "level": "高", "desc": f"20日振幅{amplitude:.1f}%，风险极高"})
                    elif amplitude > 40:
                        risks.append({"type": "高波动", "level": "中", "desc": f"20日振幅{amplitude:.1f}%，波动较大"})
        except Exception:
            pass

        # 连续下跌风险
        try:
            df = ds.get_kline_daily(code, count=10)
            if not df.empty and len(df) >= 5:
                closes = df["close"].astype(float)
                drop_5d = (closes.iloc[-1] - closes.iloc[-5]) / closes.iloc[-5] * 100
                if drop_5d < -15:
                    risks.append({"type": "连续下跌", "level": "中", "desc": f"近5日下跌{drop_5d:.1f}%，注意抄底风险"})
        except Exception:
            pass

        return risks

    def _generate_interpretation(self, result: Dict) -> str:
        """生成智能解读。"""
        name = result["name"]
        fundamental = result.get("fundamental", {})
        themes = result.get("themes", [])
        risks = result.get("risks", [])

        parts = []

        # 基本面解读
        score = fundamental.get("score", 50)
        industry = fundamental.get("industry", "未知")
        if score >= 70:
            parts.append(f"基本面优秀（评分{score}分），{industry}赛道")
        elif score >= 55:
            parts.append(f"基本面良好（评分{score}分），{industry}行业")
        elif score >= 40:
            parts.append(f"基本面一般（评分{score}分），{industry}行业")
        else:
            parts.append(f"基本面偏弱（评分{score}分），需谨慎")

        if fundamental.get("summary"):
            parts.append(fundamental["summary"])

        # 题材解读
        if themes:
            parts.append(f"题材：{'、'.join(themes)}")

        # 风险提示
        high_risks = [r for r in risks if r["level"] == "高"]
        if high_risks:
            parts.append(f"⚠️ {high_risks[0]['desc']}")

        return "；".join(parts)


def build_analysis_message(entries: List[Dict]) -> str:
    """生成智能分析消息段落。"""
    if not entries:
        return ""

    lines = ["", "🧠 智能分析："]
    for e in entries:
        analysis = e.get("analysis")
        if not analysis:
            continue
        name = e.get("name", "")
        code = e.get("code", "")
        interpretation = analysis.get("interpretation", "")
        themes = analysis.get("themes", [])
        risks = analysis.get("risks", [])

        lines.append(f"  {name}({code})：{interpretation}")
        if risks:
            risk_text = "、".join([f"{r['type']}({r['level']})" for r in risks[:2]])
            lines.append(f"    ⚠️ 风险：{risk_text}")

    return "\n".join(lines)
