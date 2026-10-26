# -*- coding: utf-8 -*-
file_path = r"E:\AI\策略\dragon-strategy-v4.3\scripts\v43_push.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 修改MACD共振记录
old = '''    resonance_entries = result.get("entries", [])
    if resonance_entries:
        record_recommendations(resonance_entries, "resonance", scan_time)'''
new = '''    resonance_entries = result.get("entries", [])
    if resonance_entries:
        regime = result.get("regime", "unknown")
        record_recommendations(resonance_entries, "resonance", scan_time, regime)'''
if old in content:
    content = content.replace(old, new)
    print("✅ MACD共振记录修改成功")
else:
    print("❌ 未找到MACD共振记录位置")

# 修改超跌反弹记录
old = '''        oversold_entries = oversold_result.get("entries", [])
        if oversold_entries:
            oversold_time = oversold_result.get("scan_time", now_bjt().strftime("%Y-%m-%d %H:%M:%S"))
            record_recommendations(oversold_entries, "oversold", oversold_time)'''
new = '''        oversold_entries = oversold_result.get("entries", [])
        if oversold_entries:
            oversold_time = oversold_result.get("scan_time", now_bjt().strftime("%Y-%m-%d %H:%M:%S"))
            oversold_regime = oversold_result.get("regime", "unknown")
            record_recommendations(oversold_entries, "oversold", oversold_time, oversold_regime)'''
if old in content:
    content = content.replace(old, new)
    print("✅ 超跌反弹记录修改成功")
else:
    print("❌ 未找到超跌反弹记录位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ v43_push.py 修改完成")
