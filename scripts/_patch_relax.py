# -*- coding: utf-8 -*-
"""修复：大盘3分时最低得分从60降到50；tracking为空时默认Level3放宽。"""

filepath = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\breakout.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 修复1：大盘3-4分时最低得分从60降到50
old1 = "        min_score_override = 60 if score < 4.0 else 0"
new1 = "        min_score_override = 50 if score < 4.0 else 0"
if old1 in content:
    content = content.replace(old1, new1, 1)
    print("修复1：大盘3-4分最低得分60->50")
else:
    print("修复1未找到位置")

# 修复2：tracking为空时默认hunger_days=7（Level3大幅放宽）
old2 = """        except Exception:
            return 0

        # 从今天往前数，连续0推荐的天数"""
new2 = """        except Exception:
            # tracking为空（新系统/数据丢失），默认大幅放宽
            return 7

        # 从今天往前数，连续0推荐的天数"""
if old2 in content:
    content = content.replace(old2, new2, 1)
    print("修复2：tracking为空时默认hunger_days=7")
else:
    print("修复2未找到位置")

# 修复3：daily_counts为空时也默认hunger_days=7
old3 = """        # 从今天往前数，连续0推荐的天数
        hunger = 0"""
new3 = """        # 从今天往前数，连续0推荐的天数
        hunger = 0
        # 如果没有任何历史记录（新系统），默认7天饥饿度
        if not daily_counts:
            return 7"""
if old3 in content:
    content = content.replace(old3, new3, 1)
    print("修复3：无历史记录时默认7天饥饿度")
else:
    print("修复3未找到位置")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("文件已保存")
