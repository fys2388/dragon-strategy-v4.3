# -*- coding: utf-8 -*-
"""修复 breakout.py 中的 market_gate 导入函数名。"""

filepath = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\breakout.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

old = "from .market_gate import evaluate_market_gate"
new = "from .market_gate import get_market_score as evaluate_market_gate"

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print("修复成功：evaluate_market_gate -> get_market_score")
else:
    print("未找到目标行")
    # 查找实际内容
    for i, line in enumerate(content.split("\n"), 1):
        if "market_gate" in line and "import" in line:
            print(f"  行{i}: {line.strip()}")
