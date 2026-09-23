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

import requests

from . import data_source as ds
from .config import LLM, RISK

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
    "金融": ["银行", "证券", "保险", "信托", "中信", "招商", "平安", "兴业", "资本"],
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
    "证券": ["证券", "券商", "资本"],
    "保险": ["保险", "人寿", "平安"],
    # 万科A(000002)/保利发展(600048)/招商蛇口(001979)/金地集团(600383)/
    # 新城控股(601155)/龙湖集团(09977) 等地产龙头名字里没有"地产/置业/建设"字样，
    # 靠关键字匹配会全部落到"综合"，导致基本面打分和 LLM 叙述把地产股说成综合类企业。
    "房地产": ["地产", "置业", "建设", "城建", "万科", "保利", "招商蛇口",
               "金地", "新城", "龙湖", "碧桂园", "旭辉", "金科", "融信",
               "华侨城", "首开", "华发"],
    # 医药：名字里含"药业"的是最常见的中药/化药企业（千金药业、白云山、太极
    # 集团、片仔癀、云南白药、上海家化 等），关键词不能漏"药业"两个字，否则
    # 一大类医药股会被错归"综合"，LLM 分析叙述就跟着跑偏。
    "医药": ["医药", "生物", "制药", "药业", "医疗", "健康", "片仔癀"],
    "电子": ["电子", "科技", "半导体", "芯片", "光电"],
    "计算机": ["软件", "信息", "网络", "数据", "智能"],
    "电力设备": ["电气", "电力", "新能源", "光伏", "电池"],
    "机械设备": ["机械", "设备", "重工", "精密"],
    "汽车": ["汽车", "车业", "零部件"],
    # 食品饮料：白酒/乳业/调味品龙头名字里很少直接带"食品/饮料/酒业"字样
    # （贵州茅台、五粮液、泸州老窖、洋河股份、青岛啤酒、伊利股份、海天味业、
    # 双汇发展、金龙鱼 等），得靠公司名直接命中。
    "食品饮料": ["食品", "饮料", "酒业", "乳业", "调味",
                 "茅台", "五粮液", "泸州老窖", "洋河", "汾酒",
                 "青岛啤酒", "伊利", "双汇", "海天", "金龙鱼",
                 "古井", "今世缘", "舍得", "水井坊", "张裕",
                 "农夫山泉", "养元饮品", "安井", "三全", "思念",
                 "绝味", "周黑鸭", "千味"],
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
    "传媒": ["传媒", "文化", "影视", "游戏", "出版", "新华", "文轩"],
    "通信": ["通信", "通讯", "电信"],
    "国防军工": ["军工", "航天", "航空", "兵器", "船舶"],
    "美容护理": ["美妆", "护理", "日化"],
}

# ============================================================
# 股票代码 → 行业 兜底表
# ------------------------------------------------------------
# 有些股票名字里完全没有行业信息，关键词匹配必然落到"综合"：
# - 莲花控股(600186)：主业"味精+健康饮品"，名字里没有"味精/食品/饮料"
# - 双汇发展、承德露露、洽洽食品 等：名字里没有行业关键词
#
# 收录原则（严格）：
#   1. 关键词匹配不到（否则会重复/冲突）
#   2. 推送里大概率会作为推荐标的出现（不是冷门股）
#   3. 行业归属在业内没有争议（避免用兜底表掩盖关键词设计缺陷）
#
# 新出现的漏网之鱼追加进来即可，不需要改关键词逻辑。
STOCK_CODE_INDUSTRY: Dict[str, str] = {
    # 食品/饮料/调味 —— 名字里没有对应关键词
    "600186": "食品饮料",  # 莲花控股（主业：味精+健康饮品，名字里无行业词）
    "603866": "食品饮料",  # 桃李面包（"面包"不在关键词里）

    # 电子/半导体 —— 名字里没有"电子/科技/半导体"等关键词
    # 收录原则：关键词匹配不到 + 推送里大概率出现 + 行业归属无争议
    "002156": "电子",      # 通富微电（半导体封测，名字里没有"电子/半导体"）
    "002138": "电子",      # 顺络电子（"电子"关键词命中，保留作兜底）
}

# 汽车关键词补"比亚迪"
INDUSTRY_KEYWORDS["汽车"].append("比亚迪")

# 电子关键词补半导体封测/晶圆龙头
# 通富微电是半导体封测龙头，但名字里没有"电子"字样，必须显式收录
INDUSTRY_KEYWORDS["电子"].extend([
    "通富微电",  # 半导体封测
    "长电科技",  # 半导体封测（"科技"命中，双保险）
    "华天科技",  # 半导体封测（"科技"命中，双保险）
    "晶方科技",  # 半导体封装（"科技"命中，双保险）
    "太极实业",  # 半导体封装（"实业"不命中，必须收录）
    "晶瑞电材",  # 电子化学品（"电材"不命中"电子"，必须收录）
])


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

    # ============================================================
    # LLM 调用（OpenAI 兼容接口）
    # ============================================================

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM API，返回文本回复。失败返回空字符串。"""
        if not LLM.get("enabled", False):
            return ""
        api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            # 尝试从本地配置文件读取（仅本地调试用）
            local_config = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "config", "llm_config.json",
            )
            if os.path.exists(local_config):
                try:
                    with open(local_config, "r", encoding="utf-8") as f:
                        api_key = json.load(f).get("api_key", "")
                except Exception:
                    pass
            if not api_key:
                print("[LLM] 未配置 LLM_API_KEY，跳过 LLM 分析")
                return ""

        api_base = LLM.get("api_base", "https://platform.sensenova.cn/v1")
        model = LLM.get("model", "sensenova-6.7-flash")
        timeout = LLM.get("timeout", 15)
        max_tokens = LLM.get("max_tokens", 500)
        temperature = LLM.get("temperature", 0.3)
        retry = LLM.get("retry", 1)

        for attempt in range(retry + 1):
            try:
                resp = requests.post(
                    f"{api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                    timeout=timeout,
                )
                if resp.status_code != 200:
                    print(f"[LLM] API 返回 {resp.status_code}: {resp.text[:200]}")
                    if attempt < retry:
                        time.sleep(2)
                        continue
                    return ""
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip()
            except Exception as e:
                if attempt < retry:
                    time.sleep(2)
                    continue
                print(f"[LLM] 调用失败: {e}")
                return ""

    def _build_analysis_prompt(self, code: str, name: str, price: float,
                                huangyang_score: Optional[int] = None) -> str:
        """构建分析 prompt。

        止损/目标价口径强约束：由 config.py 的 RISK.stop_loss_pct 计算止损价，
        LLM 不能自由发挥。历史推送里出现过 -9.3% 的止损（config 是 -5%），
        单票仓位 3000 元 = 亏 300 元，是风控设计上限的 2 倍。
        """
        industry = self._infer_industry(name, code)
        # 如果已有黄阳打分，将分数传入prompt，让LLM基于分数评级而非自行判断
        score_section = ""
        if huangyang_score is not None:
            score_section = f"""
基本面打分：{huangyang_score}分
评级标准（必须严格遵循）：
- ≥80分 = 优秀
- ≥65分 = 良好
- ≥50分 = 一般
- ≥35分 = 偏弱
- <35分 = 差
请在分析中引用该分数和对应评级，不要自行重新判断评级。
"""
        # 硬止损口径由 config.py 统一维护，LLM 只能按此计算不能自造
        stop_loss_pct = RISK.get("stop_loss_pct", 0.05)
        stop_loss_price = round(price * (1 - stop_loss_pct), 2) if price > 0 else 0.0
        take_profit_1 = RISK.get("take_profit_1_pct", 0.10)
        target_price_hint = round(price * (1 + take_profit_1), 2) if price > 0 else 0.0
        return f"""你是A股量化分析师。请分析以下股票，用 JSON 格式回复（不要加其他文字）：

股票：{name}({code})
现价：{price}元
行业：{industry}
{score_section}
【重要约束】
1. 行业字段由系统提供（见上方"行业："），你必须在分析文本里引用该字段，
   绝对不要自行判断或改写行业（历史事故：LLM 曾把半导体封测的通富微电脑补成
   "医药行业"，完全错误）。
2. 如果上方"行业"显示为"综合"，说明系统暂未识别，请写"行业归属暂不明确"，
   不要凭感觉归类到其他行业。
3. 风控数字（止损价/目标价）必须严格使用下方给定的数值，不要自造。
   历史事故：LLM 曾对 4.19 元的万科A 报出 3.80 元止损（-9.3%），config 是 -5%。

风控口径（必须严格遵守，不要自造数字）：
- 硬止损：{stop_loss_pct*100:.0f}%，对应止损价 = {stop_loss_price} 元
- 首档止盈参考：+{take_profit_1*100:.0f}%，对应 {target_price_hint} 元

请输出：
{{
  "推荐理由": "1-2句话核心推荐逻辑",
  "风险提示": "1句话主要风险点",
  "仓位建议": "X%试仓 / X%观察 / 不建议（单票最大仓位 30%）",
  "目标价": 数字（元，参考首档止盈 {target_price_hint} 元附近，可上下浮动），
  "止损价": {stop_loss_price}
}}
"""

    def _analyze_with_llm(self, code: str, name: str, price: float,
                           huangyang_score: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """用 LLM 分析股票，失败返回 None（调用方降级到规则方案）。"""
        prompt = self._build_analysis_prompt(code, name, price, huangyang_score)
        result = self._call_llm(prompt)
        if not result:
            return None
        try:
            # LLM 可能返回带 markdown 代码块的 JSON，需要清理
            text = result.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            data = json.loads(text)
        except (json.JSONDecodeError, IndexError) as e:
            print(f"[LLM] {name}({code}) JSON 解析失败: {e}，降级到规则方案")
            return None

        # 后端保险：LLM 有时无视 prompt 里的止损约束自己拍数字。
        self._clamp_risk_fields(data, price)
        return data

    @staticmethod
    def _clamp_risk_fields(data: Dict[str, Any], price: float) -> None:
        """把 LLM 返回的止损价/目标价强制夹到 config.RISK 口径内。就地修改 data。

        - 止损价：强制等于 price * (1 - stop_loss_pct)（不允许 LLM 自造）
        - 目标价：不低于首档止盈档价（price * (1 + take_profit_1_pct)），
          避免 LLM 给出比首档止盈还低的目标价（盈亏比不足）

        历史事故：LLM 曾对 4.19 元的万科A 报出 3.80 元止损（-9.3%，config 是 -5%），
        单票仓位 3000 元 → 亏 300 元，是风控设计上限的 2 倍。
        """
        if price <= 0:
            return
        stop_loss_pct = RISK.get("stop_loss_pct", 0.05)
        expected_stop = round(price * (1 - stop_loss_pct), 2)
        try:
            llm_stop = float(data.get("止损价", 0) or 0)
        except (TypeError, ValueError):
            llm_stop = 0.0
        if llm_stop <= 0 or llm_stop != expected_stop:
            if llm_stop > 0:
                print(f"[LLM] 止损价强制校正: {llm_stop} → {expected_stop}"
                      f"（config.RISK.stop_loss_pct={stop_loss_pct}）")
            data["止损价"] = expected_stop

        take_profit_1_pct = RISK.get("take_profit_1_pct", 0.10)
        min_target = round(price * (1 + take_profit_1_pct), 2)
        try:
            llm_target = float(data.get("目标价", 0) or 0)
        except (TypeError, ValueError):
            llm_target = 0.0
        if llm_target <= 0:
            data["目标价"] = min_target
        elif llm_target < min_target:
            print(f"[LLM] 目标价过低({llm_target})，抬升到首档止盈档 {min_target}")
            data["目标价"] = min_target

    def _build_llm_interpretation(self, llm_result: Dict[str, Any],
                                   huangyang_score: Optional[int],
                                   name: str, code: str = "") -> str:
        """构建LLM分析解读文本，用黄阳打分统一评级口径。"""
        parts = []

        # 用黄阳打分统一评级（与 huangyang_scorer 阈值一致）
        if huangyang_score is not None:
            if huangyang_score >= 80:
                parts.append(f"基本面优秀（评分{huangyang_score}分）")
            elif huangyang_score >= 65:
                parts.append(f"基本面良好（评分{huangyang_score}分）")
            elif huangyang_score >= 50:
                parts.append(f"基本面一般（评分{huangyang_score}分）")
            elif huangyang_score >= 35:
                parts.append(f"基本面偏弱（评分{huangyang_score}分），需谨慎")
            else:
                parts.append(f"基本面较差（评分{huangyang_score}分），不建议参与")
        else:
            industry = self._infer_industry(name, code)
            parts.append(f"行业：{industry}")

        # LLM 核心分析
        reason = llm_result.get("推荐理由", "")
        if reason:
            parts.append(reason)

        # 风险
        risk = llm_result.get("风险提示", "")
        if risk:
            parts.append(f"风险：{risk}")

        # 仓位
        position = llm_result.get("仓位建议", "")
        if position:
            parts.append(f"建议：{position}")

        # 目标价和止损价
        target = llm_result.get("目标价", None)
        stop = llm_result.get("止损价", None)
        tp_parts = []
        if target:
            tp_parts.append(f"目标{target}元")
        if stop:
            tp_parts.append(f"止损{stop}元")
        if tp_parts:
            parts.append(" | ".join(tp_parts))

        return "；".join(parts)

    def analyze_stock(self, code: str, name: str, price: float = 0,
                      huangyang_score: Optional[int] = None) -> Dict[str, Any]:
        """分析单只股票，返回完整分析结果。

        优先级：LLM 智能分析 → 规则降级方案。
        huangyang_score: 黄阳五维打分（可选），用于统一评级口径。
        """
        cache_key = f"{code}_{time.strftime('%Y%m%d')}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 1. 尝试 LLM 智能分析
        llm_result = self._analyze_with_llm(code, name, price, huangyang_score)
        if llm_result and LLM.get("enabled", False):
            print(f"[LLM] ✅ {name}({code}) LLM 分析成功")
            # 用黄阳打分统一评级，避免LLM幻觉
            interpretation = self._build_llm_interpretation(
                llm_result, huangyang_score, name, code
            )
            result = {
                "code": code,
                "name": name,
                "price": price,
                "fundamental": llm_result,
                "themes": self._mine_themes(code, name),
                "risks": self._scan_risks(code, name, price),
                "interpretation": interpretation,
                "analysis_source": "llm",
            }
        else:
            # 2. LLM 不可用或失败 → 降级到规则方案
            result = {
                "code": code,
                "name": name,
                "price": price,
                "fundamental": self._analyze_fundamental(code, name, price),
                "themes": self._mine_themes(code, name),
                "risks": self._scan_risks(code, name, price),
                "analysis_source": "rules",
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
                    huangyang_score=e.get("huangyang_score"),
                )
                e["analysis"] = analysis
                results.append(e)
            except Exception as ex:
                print(f"[智能分析] {e.get('code')} 分析失败: {ex}")
                e["analysis"] = None
                results.append(e)
        return results

    def _infer_industry(self, name: str, code: Optional[str] = None) -> str:
        """推断行业。优先级：名称关键词 → 代码兜底表 → "综合"。

        归一化：去掉所有空白字符、把全角字母数字转成半角。
        背景：数据源（东财 f58 字段）返回的股票名带半角空格和全角字母，
        直接对原始名字做 `in` 匹配会漏掉关键词，导致股票被错归"综合"。
        历史上推送里出现过万科A 行业标"综合"的事故。

        代码兜底：有些股票名字里没有行业信息（如莲花控股主业是味精+饮品，
        名字里没有"食品/饮料/味精"），关键词匹配必落到"综合"，此时按
        STOCK_CODE_INDUSTRY 兜底。只在关键词未命中时才走代码兜底，避免
        兜底表掩盖关键词逻辑缺陷。

        Args:
            name: 股票名称（可为全角/半角混排）
            code: 6 位股票代码，可选；提供时可在关键词匹配失败后走兜底表
        """
        if name:
            normalized = self._normalize_stock_name(name)
            for industry, keywords in INDUSTRY_KEYWORDS.items():
                if any(kw in normalized for kw in keywords):
                    return industry
        # 关键词未命中时，尝试代码兜底
        if code:
            industry = STOCK_CODE_INDUSTRY.get(code)
            if industry:
                return industry
        return "综合"

    @staticmethod
    def _normalize_stock_name(name: str) -> str:
        """归一化股票名称：去空白 + 全角转半角。"""
        # 去所有 Unicode 空白字符（空格、全角空格、tab 等）
        stripped = "".join(ch for ch in name if not ch.isspace())
        # 全角转半角：全角字符的 code point 都在 FF00~FFEF 之间
        result = []
        for ch in stripped:
            cp = ord(ch)
            if 0xFF01 <= cp <= 0xFF5E:
                result.append(chr(cp - 0xFEE0))
            elif cp == 0x3000:  # 全角空格
                continue
            else:
                result.append(ch)
        return "".join(result)

    def _analyze_fundamental(self, code: str, name: str, price: float) -> Dict[str, Any]:
        """基本面分析（基于名称推断+技术面辅助）。"""
        industry = self._infer_industry(name, code)

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
        industry = self._infer_industry(name, code)

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

        # 基本面解读（阈值与 huangyang_scorer 一致：≥80优秀/≥65良好/≥50一般/≥35偏弱）
        score = fundamental.get("score", 50)
        industry = fundamental.get("industry", "未知")
        if score >= 80:
            parts.append(f"基本面优秀（评分{score}分），{industry}赛道")
        elif score >= 65:
            parts.append(f"基本面良好（评分{score}分），{industry}行业")
        elif score >= 50:
            parts.append(f"基本面一般（评分{score}分），{industry}行业")
        elif score >= 35:
            parts.append(f"基本面偏弱（评分{score}分），需谨慎")
        else:
            parts.append(f"基本面较差（评分{score}分），不建议参与")

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
    has_llm = False
    for e in entries:
        analysis = e.get("analysis")
        name = e.get("name", "")
        code = e.get("code", "")
        if not analysis:
            lines.append(f"  {name}({code})：⚠️ 智能分析未获取")
            continue
        has_llm = True
        source = analysis.get("analysis_source", "rules")
        if source == "llm":
            interpretation = analysis.get("interpretation", "")
            lines.append(f"  {name}({code})：{interpretation}")
        else:
            interpretation = analysis.get("interpretation", "")
            lines.append(f"  {name}({code})：{interpretation}")
        risks = analysis.get("risks", [])
        if risks:
            risk_text = "、".join([f"{r['type']}({r['level']})" for r in risks[:2]])
            lines.append(f"    ⚠️ 风险：{risk_text}")

    if not has_llm and lines[-1].strip() != "🧠 智能分析：":
        lines.append("  （以上为规则降级分析，非LLM智能分析）")

    return "\n".join(lines)
