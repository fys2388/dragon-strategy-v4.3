# -*- coding: utf-8 -*-
"""修复v43_push.py的health初始化和变量定义。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\scripts\v43_push.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在 scanner = Scanner() 之前添加 health 初始化
old = '    scanner = Scanner()'
new = '''    # 健康度监控：检查连续0推荐，自动降级
    health = init_health_monitor()
    param_override = health.get_current_params_override()
    if param_override["level"] > 0:
        print(f"⚠️ 系统处于降级状态 Level {param_override['level']}：{param_override['general'].get('note', '')}")

    scanner = Scanner()'''

if old in content:
    content = content.replace(old, new, 1)
    print("✅ health 初始化添加成功")
else:
    print("❌ 未找到 scanner = Scanner()")

# 2. 修复 breakout_result 未定义问题
old2 = '    # ===== 趋势突破模式（第三策略，震荡市补充）====='
new2 = '    breakout_result = {"entries": []}  # 初始化，防止异常时未定义\n    # ===== 趋势突破模式（第三策略，震荡市补充）====='
if old2 in content:
    content = content.replace(old2, new2, 1)
    print("✅ breakout_result 初始化添加成功")
else:
    print("❌ 未找到趋势突破注释")

# 3. 简化 total_recommendations 计算
old3 = '''    total_recommendations = (
        len(result.get("entries", [])) +
        len(oversold_result.get("entries", [])) +
        len(breakout_result.get("entries", []))
    ) if 'breakout_result' in dir() else (
        len(result.get("entries", [])) +
        len(oversold_result.get("entries", []))
    )'''
new3 = '''    total_recommendations = (
        len(result.get("entries", [])) +
        len(oversold_result.get("entries", [])) +
        len(breakout_result.get("entries", []))
    )'''
if old3 in content:
    content = content.replace(old3, new3, 1)
    print("✅ total_recommendations 简化成功")
else:
    print("❌ 未找到 total_recommendations")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ 文件保存完成")
