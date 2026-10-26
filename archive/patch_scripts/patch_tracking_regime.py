# -*- coding: utf-8 -*-
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\tracking.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改函数签名
old = 'def record_recommendations(entries: List[Dict], strategy_type: str, scan_time: str):'
new = 'def record_recommendations(entries: List[Dict], strategy_type: str, scan_time: str, regime: str = "unknown"):'
content = content.replace(old, new)

# 2. 修改docstring
old = '''        scan_time: 扫描时间字符串
    """'''
new = '''        scan_time: 扫描时间字符串
        regime: 市场环境
    """'''
content = content.replace(old, new)

# 3. 在record中添加regime字段
old = '''            "strategy": strategy_type,
            "recommend_price": price,'''
new = '''            "strategy": strategy_type,
            "regime": regime,
            "recommend_price": price,'''
content = content.replace(old, new)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ tracking.py 添加regime字段成功")
