# -*- coding: utf-8 -*-
"""修改v43_push.py，集成健康度监控（连续0推荐自动降级）。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\scripts\v43_push.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加导入
old = 'from strategies.macd_resonance.breakout import BreakoutScanner, build_breakout_message  # noqa: E402'
new = '''from strategies.macd_resonance.breakout import BreakoutScanner, build_breakout_message  # noqa: E402
from strategies.macd_resonance.health_monitor import init_health_monitor  # noqa: E402'''
if old in content:
    content = content.replace(old, new)
    print("✅ 健康度监控导入成功")
else:
    print("❌ 未找到导入位置")

# 2. 在main函数开始处初始化健康度监控
old = '''def main():
    report_mode = os.environ.get("REPORT_MODE", "scan")
    if report_mode == "premarket":
        push_premarket_report()
        return'''

new = '''def main():
    report_mode = os.environ.get("REPORT_MODE", "scan")
    if report_mode == "premarket":
        push_premarket_report()
        return

    # 健康度监控：检查连续0推荐，自动降级
    health = init_health_monitor()
    param_override = health.get_current_params_override()
    if param_override["level"] > 0:
        print(f"⚠️ 系统处于降级状态 Level {param_override['level']}：{param_override['general'].get('note', '')}")'''

if old in content:
    content = content.replace(old, new)
    print("✅ main函数初始化健康监控成功")
else:
    print("❌ 未找到main函数位置")

# 3. 在所有策略扫描完成后，记录推荐数量
old = '''    # 更新所有跟踪股票的表现（每天最后一次扫描时执行）
    try:
        now = now_bjt()
        # 下午14:30之后的扫描执行表现更新（一天一次足够）
        if now.hour >= 14 and now.minute >= 30:
            print("\\n" + "=" * 50)
            print("📊 更新选股绩效跟踪...")
            stats = update_performance()
            print(f"[跟踪] 总计{stats['total']}只，更新{stats['updated']}只，完成{stats['completed']}只")
    except Exception as e:
        print(f"⚠️ 绩效跟踪更新失败: {e}")'''

new = '''    # 统计今日总推荐数
    total_recommendations = (
        len(result.get("entries", [])) +
        len(oversold_result.get("entries", [])) +
        len(breakout_result.get("entries", []))
    ) if 'breakout_result' in dir() else (
        len(result.get("entries", [])) +
        len(oversold_result.get("entries", []))
    )

    # 健康度监控：记录今日推荐数
    health.record_recommendations(total_recommendations)
    if total_recommendations == 0:
        print(f"⚠️ 今日0推荐，连续0推荐天数：{health.state['consecutive_zero_days']}天")
        if health.state["degradation_level"] > 0:
            print(f"   当前降级等级：Level {health.state['degradation_level']}")
    else:
        print(f"✅ 今日推荐{total_recommendations}只，系统状态正常")

    # 打印健康度报告
    print("\\n" + health.get_health_report())

    # 更新所有跟踪股票的表现（每天最后一次扫描时执行）
    try:
        now = now_bjt()
        # 下午14:30之后的扫描执行表现更新（一天一次足够）
        if now.hour >= 14 and now.minute >= 30:
            print("\\n" + "=" * 50)
            print("📊 更新选股绩效跟踪...")
            stats = update_performance()
            print(f"[跟踪] 总计{stats['total']}只，更新{stats['updated']}只，完成{stats['completed']}只")
    except Exception as e:
        print(f"⚠️ 绩效跟踪更新失败: {e}")'''

if old in content:
    content = content.replace(old, new)
    print("✅ 推荐记录集成成功")
else:
    print("❌ 未找到记录位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ v43_push.py 修改完成")
