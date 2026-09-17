# -*- coding: utf-8 -*-
"""修改v43_push.py，集成智能分析。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\scripts\v43_push.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加导入
old = 'from strategies.macd_resonance.tracking import record_recommendations, update_performance  # noqa: E402'
new = '''from strategies.macd_resonance.tracking import record_recommendations, update_performance  # noqa: E402
from strategies.macd_resonance.llm_analyzer import StockAnalyzer, build_analysis_message  # noqa: E402'''
if old in content:
    content = content.replace(old, new)
    print("✅ 导入添加成功")
else:
    print("❌ 未找到导入位置")

# 2. MACD共振：在_send_text前添加智能分析
old = '''    msg = build_message(result)
    print(msg)
    print("\\n[SUMMARY]", result["summary"])

    _send_text(msg)'''

new = '''    msg = build_message(result)
    # 智能分析（如果有推荐股票）
    resonance_entries = result.get("entries", [])
    if resonance_entries:
        try:
            analyzer = StockAnalyzer()
            analyzed = analyzer.analyze_batch(resonance_entries)
            analysis_msg = build_analysis_message(analyzed)
            if analysis_msg:
                msg = msg + analysis_msg
        except Exception as e:
            print(f"⚠️ 智能分析失败: {e}")
    print(msg)
    print("\\n[SUMMARY]", result["summary"])

    _send_text(msg)'''

if old in content:
    content = content.replace(old, new)
    print("✅ MACD共振智能分析添加成功")
else:
    print("❌ 未找到MACD共振推送位置")

# 3. 超跌反弹：在_send_text前添加智能分析
old = '''        oversold_msg = build_oversold_message(oversold_result)
        print(oversold_msg)
        print("\\n[OVERSOLD SUMMARY]", oversold_result.get("summary", ""))
        _send_text(oversold_msg)'''

new = '''        oversold_msg = build_oversold_message(oversold_result)
        # 智能分析（如果有推荐股票）
        oversold_entries = oversold_result.get("entries", [])
        if oversold_entries:
            try:
                analyzer = StockAnalyzer()
                analyzed = analyzer.analyze_batch(oversold_entries)
                analysis_msg = build_analysis_message(analyzed)
                if analysis_msg:
                    oversold_msg = oversold_msg + analysis_msg
            except Exception as e:
                print(f"⚠️ 超跌反弹智能分析失败: {e}")
        print(oversold_msg)
        print("\\n[OVERSOLD SUMMARY]", oversold_result.get("summary", ""))
        _send_text(oversold_msg)'''

if old in content:
    content = content.replace(old, new)
    print("✅ 超跌反弹智能分析添加成功")
else:
    print("❌ 未找到超跌反弹推送位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ v43_push.py 修改完成")
