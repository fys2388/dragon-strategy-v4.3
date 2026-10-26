# -*- coding: utf-8 -*-
"""为突破策略添加同股冷却期功能。"""
import re

with open('strategies/macd_resonance/breakout.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在__init__中添加冷却期加载
old_init = """    def __init__(self):
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.quality_pool = self._load_quality_pool()"""

new_init = """    def __init__(self):
        self.base_dir = ds.os.path.dirname(ds.os.path.dirname(ds.os.path.dirname(ds.os.path.abspath(__file__))))
        self.quality_pool = self._load_quality_pool()
        self.cooldown_codes = self._load_cooldown_codes()

    def _load_cooldown_codes(self) -> set:
        \"\"\"加载冷却期股票（最近10天内被止损的股票不再推荐）。\"\"\"
        import json as _json
        from datetime import datetime, timedelta
        tracking_file = ds.os.path.join(self.base_dir, 'data', 'tracking.jsonl')
        cooldown = set()
        try:
            if ds.os.path.exists(tracking_file):
                cutoff = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
                with open(tracking_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = _json.loads(line)
                            if rec.get('status') == 'completed':
                                day5 = rec.get('day5_return_pct')
                                day10 = rec.get('day10_return_pct')
                                if (day5 is not None and day5 < -3) or (day10 is not None and day10 < -3):
                                    scan_date = str(rec.get('scan_time', ''))[:10]
                                    if scan_date >= cutoff:
                                        cooldown.add(rec.get('code', ''))
                        except Exception:
                            continue
        except Exception:
            pass
        return cooldown"""

if old_init in content:
    content = content.replace(old_init, new_init, 1)
    print('1. __init__添加冷却期加载成功')
else:
    print('1. 未找到__init__匹配')

# 2. 在初筛阶段添加冷却期过滤
old_filter = """            if cap < HARD_FILTERS["cap_min_yi"] or cap > HARD_FILTERS["cap_max_yi"]:
                continue
            candidates.append(s)"""

new_filter = """            if cap < HARD_FILTERS["cap_min_yi"] or cap > HARD_FILTERS["cap_max_yi"]:
                continue
            # 融合优化：同股冷却期（最近10天止损过的股票不再推荐）
            if code in self.cooldown_codes:
                continue
            candidates.append(s)"""

if old_filter in content:
    content = content.replace(old_filter, new_filter, 1)
    print('2. 初筛添加冷却期过滤成功')
else:
    print('2. 未找到初筛匹配')

with open('strategies/macd_resonance/breakout.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('修改完成')
