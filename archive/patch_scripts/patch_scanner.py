# -*- coding: utf-8 -*-
"""修改scanner.py，加入优质股票池过滤。"""
import re

file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\scanner.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在__init__中加入优质股票池加载
old_init = '''    def __init__(self, engine: Optional[SignalEngine] = None):
        self.engine = engine or SignalEngine()
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.cache_file = os.path.join(self.base_dir, "data", "signal_cache.json")
        self.cache = self._load_cache()'''

new_init = '''    def __init__(self, engine: Optional[SignalEngine] = None):
        self.engine = engine or SignalEngine()
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.cache_file = os.path.join(self.base_dir, "data", "signal_cache.json")
        self.cache = self._load_cache()
        self.quality_pool = self._load_quality_pool()

    def _load_quality_pool(self) -> set:
        pool_file = os.path.join(self.base_dir, "data", "quality_pool.json")
        try:
            with open(pool_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            codes = {item["code"] for item in data if "code" in item}
            LOG.info(f"优质股票池加载成功：{len(codes)}只")
            return codes
        except Exception as e:
            LOG.warning(f"优质股票池加载失败，使用全市场扫描: {e}")
            return set()'''

if old_init in content:
    content = content.replace(old_init, new_init)
    print("✅ __init__修改成功")
else:
    print("❌ 未找到__init__匹配内容")
    # 尝试查找
    idx = content.find("def __init__")
    print(f"__init__位置: {idx}")
    print(repr(content[idx:idx+300]))

# 2. 在_quick_filter中加入股票池检查
old_quick = '''    def _quick_filter(self, stock: dict) -> bool:
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        price = float(stock.get("price", 0) or 0)
        cap = float(stock.get("float_cap_yi", 0) or 0)
        if price < 3.0 or price > 35.0:
            return False
        if cap < 30 or cap > 600:
            return False
        # 成交额预过滤（用池内当日成交额作 20 日均额的宽松代理）：
        # 当日成交额过低者基本不可能满足 amount_20d≥0.8亿 硬过滤，提前剔除，
        # 大幅减少后续逐票拉 K 线的耗时（云端 5 分钟节奏必需）。
        amt = float(stock.get("amount_yi", 0) or 0)
        if amt > 0 and amt < 0.5:  # 仅当日已有成交额且 <5000万 时剔除
            return False
        return True'''

new_quick = '''    def _quick_filter(self, stock: dict) -> bool:
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        # 优质股票池过滤（基本面预筛选）
        code = str(stock.get("code", ""))
        if self.quality_pool and code not in self.quality_pool:
            return False
        price = float(stock.get("price", 0) or 0)
        cap = float(stock.get("float_cap_yi", 0) or 0)
        if price < 3.0 or price > 35.0:
            return False
        if cap < 30 or cap > 600:
            return False
        # 成交额预过滤（用池内当日成交额作 20 日均额的宽松代理）：
        # 当日成交额过低者基本不可能满足 amount_20d≥0.8亿 硬过滤，提前剔除，
        # 大幅减少后续逐票拉 K 线的耗时（云端 5 分钟节奏必需）。
        amt = float(stock.get("amount_yi", 0) or 0)
        if amt > 0 and amt < 0.5:  # 仅当日已有成交额且 <5000万 时剔除
            return False
        return True'''

if old_quick in content:
    content = content.replace(old_quick, new_quick)
    print("✅ _quick_filter修改成功")
else:
    print("❌ 未找到_quick_filter匹配内容")
    idx = content.find("def _quick_filter")
    print(f"_quick_filter位置: {idx}")
    print(repr(content[idx:idx+400]))

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ 文件已保存")
