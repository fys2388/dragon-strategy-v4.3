# -*- coding: utf-8 -*-
"""修复推送颜色：3分用黄色，4+分用红色。"""

import os

# 修复 scanner.py 中的推送格式
scanner_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\scanner.py"
with open(scanner_path, "r", encoding="utf-8") as f:
    content = f.read()

old = 'lines = [f"📊 MACD共振：大盘{score:.0f}/7 {\'🔴可开仓\' if can_open else \'🟢观望\'}"]'
new = 'lines = [f"📊 MACD共振：大盘{score:.0f}/7 {\'🔴可开仓\' if can_open and score >= 4 else \'🟡谨慎开仓\' if can_open else \'🟢观望\'}"]'

if old in content:
    content = content.replace(old, new, 1)
    with open(scanner_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("scanner.py 颜色修复成功")
else:
    print("scanner.py 未找到目标行")
    # 查找实际内容
    for i, line in enumerate(content.split("\n"), 1):
        if "MACD共振" in line and "可开仓" in line:
            print(f"  行{i}: {line.strip()}")

# 修复 v43_push.py 中的推送格式
v43_path = r"E:\AI\策略\dragon-strategy-v4.3\scripts\v43_push.py"
with open(v43_path, "r", encoding="utf-8") as f:
    content2 = f.read()

for i, line in enumerate(content2.split("\n"), 1):
    if "MACD共振" in line and ("可开仓" in line or "观望" in line):
        print(f"v43_push.py 行{i}: {line.strip()}")
