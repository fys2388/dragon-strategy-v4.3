# -*- coding: utf-8 -*-
"""修改 breakout.py：使用门控变量控制推荐数量和最低得分。"""

filepath = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\breakout.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 修改1：打分前加入最低得分过滤
old1 = """        # 7. 综合打分排序（融合熊猫有财技术面 + 黄阳基本面）
        for s in fundamental_filtered:"""

new1 = """        # 7. 综合打分排序（融合熊猫有财技术面 + 黄阳基本面）
        # 门控：宽松档（3-4分）提高最低得分要求
        if min_score_override > 0:
            fundamental_filtered = [s for s in fundamental_filtered if s.get("composite_score", 0) >= min_score_override]
        for s in fundamental_filtered:"""

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("修改1成功：加入最低得分过滤")
else:
    print("修改1失败：未找到位置")

# 修改2：截断数量使用 max_recommend
old2 = "        top = fundamental_filtered[:5]"
new2 = "        top = fundamental_filtered[:max_recommend]"

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("修改2成功：截断数量使用max_recommend")
else:
    print("修改2失败：未找到位置")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("文件已保存")
