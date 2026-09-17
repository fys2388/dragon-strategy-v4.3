# -*- coding: utf-8 -*-
"""修改oversold_rebound.py，加入优质股票池过滤。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\oversold_rebound.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在__init__中加入优质股票池加载
old_init = '''    def __init__(self):
        self.engine = SignalEngine()
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.cache_file = ds.os.path.join(self.base_dir, "data", "oversold_cache.json")
        self.cache = self._load_cache()'''

new_init = '''    def __init__(self):
        self.engine = SignalEngine()
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.cache_file = ds.os.path.join(self.base_dir, "data", "oversold_cache.json")
        self.cache = self._load_cache()
        self.quality_pool = self._load_quality_pool()

    def _load_quality_pool(self) -> set:
        pool_file = ds.os.path.join(self.base_dir, "data", "quality_pool.json")
        try:
            import json
            with open(pool_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            codes = {item["code"] for item in data if "code" in item}
            LOG.info(f"[超跌反弹] 优质股票池加载成功：{len(codes)}只")
            return codes
        except Exception as e:
            LOG.warning(f"[超跌反弹] 优质股票池加载失败，使用全市场扫描: {e}")
            return set()'''

if old_init in content:
    content = content.replace(old_init, new_init)
    print("✅ __init__修改成功")
else:
    print("❌ 未找到__init__匹配内容")
    idx = content.find("def __init__")
    print(repr(content[idx:idx+300]))

# 2. 在_quick_filter中加入股票池检查
old_quick = '''    def _quick_filter(self, stock: dict) -> bool:
        """初筛：价格、市值、非ST、主板。"""
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        code = str(stock.get("code", ""))
        if not code.startswith(("60", "00")):
            return False
        price = float(stock.get("price", 0) or 0)
        cap = float(stock.get("float_cap_yi", 0) or 0)
        if price < HARD_FILTERS["price_min"] or price > HARD_FILTERS["price_max"]:
            return False
        if cap < HARD_FILTERS["cap_min_yi"] or cap > HARD_FILTERS["cap_max_yi"]:
            return False
        # 当日成交额预过滤
        amt = float(stock.get("amount_yi", 0) or 0)
        if amt > 0 and amt < 0.3:
            return False
        return True'''

new_quick = '''    def _quick_filter(self, stock: dict) -> bool:
        """初筛：价格、市值、非ST、主板、优质股票池。"""
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        code = str(stock.get("code", ""))
        if not code.startswith(("60", "00")):
            return False
        # 优质股票池过滤（基本面预筛选）
        if self.quality_pool and code not in self.quality_pool:
            return False
        price = float(stock.get("price", 0) or 0)
        cap = float(stock.get("float_cap_yi", 0) or 0)
        if price < HARD_FILTERS["price_min"] or price > HARD_FILTERS["price_max"]:
            return False
        if cap < HARD_FILTERS["cap_min_yi"] or cap > HARD_FILTERS["cap_max_yi"]:
            return False
        # 当日成交额预过滤
        amt = float(stock.get("amount_yi", 0) or 0)
        if amt > 0 and amt < 0.3:
            return False
        return True'''

if old_quick in content:
    content = content.replace(old_quick, new_quick)
    print("✅ _quick_filter修改成功")
else:
    print("❌ 未找到_quick_filter匹配内容")
    idx = content.find("def _quick_filter")
    print(repr(content[idx:idx+400]))

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ 文件已保存")
