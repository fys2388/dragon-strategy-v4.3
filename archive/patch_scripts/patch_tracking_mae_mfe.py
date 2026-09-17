# -*- coding: utf-8 -*-
"""扩展tracking.py，添加MAE/MFE指标。

MAE（Maximum Adverse Excursion）：持仓期间最大浮亏
MFE（Maximum Favorable Excursion）：持仓期间最大浮盈

这两个指标比单纯看最终收益更有价值：
- MAE告诉我们止损是否合理、入场是否太早
- MFE告诉我们止盈是否合理、是否过早离场
"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\tracking.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在record_recommendations的record字典中添加MAE/MFE字段
old = '''            "max_drawdown_pct": 0.0,
            "day1_close": None,'''
new = '''            "max_drawdown_pct": 0.0,
            "mae_pct": 0.0,          # 最大不利波动（最大浮亏）
            "mfe_pct": 0.0,          # 最大有利波动（最大浮盈）
            "mae_day": None,         # MAE发生在第几天
            "mfe_day": None,         # MFE发生在第几天
            "day1_close": None,'''
if old in content:
    content = content.replace(old, new, 1)
    print("✅ MAE/MFE字段添加成功")
else:
    print("❌ 未找到max_drawdown_pct位置")

# 2. 在update_performance中计算MAE和MFE
# 找到计算最大回撤的位置，在其后添加MAE/MFE计算
old = '''            # 计算最大回撤（从推荐后的最高点到后续最低点）
            if high > max_price:
                max_price = high
            drawdown = (max_price - low) / max_price * 100 if max_price > 0 else 0
            if drawdown > r.get("max_drawdown_pct", 0):
                r["max_drawdown_pct"] = round(drawdown, 2)'''

new = '''            # 计算最大回撤（从推荐后的最高点到后续最低点）
            if high > max_price:
                max_price = high
            drawdown = (max_price - low) / max_price * 100 if max_price > 0 else 0
            if drawdown > r.get("max_drawdown_pct", 0):
                r["max_drawdown_pct"] = round(drawdown, 2)

            # 计算MAE（最大不利波动=最大浮亏）
            mae = (recommend_price - low) / recommend_price * 100 if recommend_price > 0 else 0
            if mae > r.get("mae_pct", 0):
                r["mae_pct"] = round(mae, 2)
                r["mae_day"] = i

            # 计算MFE（最大有利波动=最大浮盈）
            mfe = (high - recommend_price) / recommend_price * 100 if recommend_price > 0 else 0
            if mfe > r.get("mfe_pct", 0):
                r["mfe_pct"] = round(mfe, 2)
                r["mfe_day"] = i'''

if old in content:
    content = content.replace(old, new, 1)
    print("✅ MAE/MFE计算逻辑添加成功")
else:
    print("❌ 未找到最大回撤计算位置")

# 3. 在calc_stats函数中添加MAE/MFE统计
old = '''        return {
            "count": len(valid),
            "win_rate": round(len(wins) / len(valid) * 100, 1),
            "avg_return": round(sum(returns) / len(valid), 2),
            "max_return": round(max(returns), 2),
            "min_return": round(min(returns), 2),
            "avg_max_drawdown": round(sum(r.get("max_drawdown_pct", 0) for r in valid) / len(valid), 2),
        }'''

new = '''        avg_mae = round(sum(r.get("mae_pct", 0) for r in valid) / len(valid), 2)
        avg_mfe = round(sum(r.get("mfe_pct", 0) for r in valid) / len(valid), 2)
        # 盈亏效率比 = MFE/MAE，>1说明盈利空间大于亏损空间
        efficiency = round(avg_mfe / avg_mae, 2) if avg_mae > 0 else 0
        return {
            "count": len(valid),
            "win_rate": round(len(wins) / len(valid) * 100, 1),
            "avg_return": round(sum(returns) / len(valid), 2),
            "max_return": round(max(returns), 2),
            "min_return": round(min(returns), 2),
            "avg_max_drawdown": round(sum(r.get("max_drawdown_pct", 0) for r in valid) / len(valid), 2),
            "avg_mae": avg_mae,           # 平均最大浮亏
            "avg_mfe": avg_mfe,           # 平均最大浮盈
            "efficiency_ratio": efficiency,  # 盈亏效率比 MFE/MAE
        }'''

if old in content:
    content = content.replace(old, new, 1)
    print("✅ MAE/MFE统计添加成功")
else:
    print("❌ 未找到calc_stats返回位置")

# 4. 在build_performance_message中添加MAE/MFE展示
old = '''                lines.append(
                    f"  {label}：胜率{win_emoji}{s['win_rate']}% | "
                    f"平均收益{s['avg_return']}% | 最大{s['max_return']}% | 最小{s['min_return']}%"
                )'''

new = '''                mae = s.get("avg_mae", 0)
                mfe = s.get("avg_mfe", 0)
                eff = s.get("efficiency_ratio", 0)
                lines.append(
                    f"  {label}：胜率{win_emoji}{s['win_rate']}% | "
                    f"平均收益{s['avg_return']}% | 最大{s['max_return']}% | 最小{s['min_return']}%"
                )
                lines.append(
                    f"       MAE最大浮亏{mae}% | MFE最大浮盈{mfe}% | 盈亏效率比{eff}"
                )'''

if old in content:
    content = content.replace(old, new, 1)
    print("✅ MAE/MFE展示添加成功")
else:
    print("❌ 未找到绩效展示位置")

# 5. 在总体表现中也添加MAE/MFE
old = '''                lines.append(
                    f"  {label}：胜率{s['win_rate']}% | 平均收益{s['avg_return']}% | "
                    f"平均最大回撤{s.get('avg_max_drawdown', 0)}%"
                )'''

new = '''                mae = s.get("avg_mae", 0)
                mfe = s.get("avg_mfe", 0)
                eff = s.get("efficiency_ratio", 0)
                lines.append(
                    f"  {label}：胜率{s['win_rate']}% | 平均收益{s['avg_return']}% | "
                    f"平均最大回撤{s.get('avg_max_drawdown', 0)}%"
                )
                lines.append(
                    f"       MAE最大浮亏{mae}% | MFE最大浮盈{mfe}% | 盈亏效率比{eff}"
                )'''

if old in content:
    content = content.replace(old, new, 1)
    print("✅ 总体MAE/MFE展示添加成功")
else:
    print("❌ 未找到总体展示位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ tracking.py 修改完成")
