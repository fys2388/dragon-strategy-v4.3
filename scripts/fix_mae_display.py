# -*- coding: utf-8 -*-
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\tracking.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''                lines.append(
                    f"  {label}：样本{s['count']}只 | 胜率{win_emoji}{s['win_rate']}% | "
                    f"平均收益{s['avg_return']}% | 最大{s['max_return']}% | 最小{s['min_return']}%"
                )'''

new = '''                mae = s.get("avg_mae", 0)
                mfe = s.get("avg_mfe", 0)
                eff = s.get("efficiency_ratio", 0)
                lines.append(
                    f"  {label}：样本{s['count']}只 | 胜率{win_emoji}{s['win_rate']}% | "
                    f"平均收益{s['avg_return']}% | 最大{s['max_return']}% | 最小{s['min_return']}%"
                )
                lines.append(
                    f"       MAE最大浮亏{mae}% | MFE最大浮盈{mfe}% | 盈亏效率比{eff}"
                )'''

if old in content:
    content = content.replace(old, new, 1)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ 分策略MAE/MFE展示添加成功")
else:
    print("❌ 仍未匹配")
