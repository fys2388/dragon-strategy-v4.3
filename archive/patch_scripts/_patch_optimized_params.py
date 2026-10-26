# -*- coding: utf-8 -*-
"""让突破策略读取Agent优化参数。"""

with open('strategies/macd_resonance/breakout.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在__init__中添加优化参数加载
old_init_end = """        return cooldown"""

new_init_end = """        return cooldown

    def _load_optimized_params(self) -> dict:
        \"\"\"加载Agent优化的参数（周度优化器自动调整）。\"\"\"
        import json as _json
        state_file = ds.os.path.join(self.base_dir, 'data', 'optimization_state.json')
        default_params = {
            'volume_ratio_min': 1.5,
            'min_score': 40,
            'cooldown_days': 10,
        }
        try:
            if ds.os.path.exists(state_file):
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = _json.load(f)
                optimized = state.get('current_params', {}).get('breakout', {})
                return {**default_params, **optimized}
        except Exception:
            pass
        return default_params"""

if old_init_end in content:
    content = content.replace(old_init_end, new_init_end, 1)
    print('1. 添加优化参数加载方法成功')
else:
    print('1. 未找到匹配位置')

# 2. 在__init__中调用优化参数加载
old_cooldown = """        self.quality_pool = self._load_quality_pool()
        self.cooldown_codes = self._load_cooldown_codes()"""

new_cooldown = """        self.quality_pool = self._load_quality_pool()
        self.optimized_params = self._load_optimized_params()
        self.cooldown_codes = self._load_cooldown_codes()"""

if old_cooldown in content:
    content = content.replace(old_cooldown, new_cooldown, 1)
    print('2. __init__调用优化参数加载成功')
else:
    print('2. 未找到__init__匹配')

# 3. 突破条件过滤中使用优化的量比阈值
old_vr = """            if s.get("volume_ratio", 0) < 1.5:
                reject_reasons[f"量比{s.get('volume_ratio', 0):.1f}<1.5"] += 1
                continue"""

new_vr = """            vr_min = self.optimized_params.get('volume_ratio_min', 1.5)
            if s.get("volume_ratio", 0) < vr_min:
                reject_reasons[f"量比{s.get('volume_ratio', 0):.1f}<{vr_min}"] += 1
                continue"""

if old_vr in content:
    content = content.replace(old_vr, new_vr, 1)
    print('3. 量比阈值使用优化参数成功')
else:
    print('3. 未找到量比阈值匹配')

# 4. 冷却期使用优化的天数
old_cooldown_load = """                cutoff = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')"""

new_cooldown_load = """                cooldown_days = self.optimized_params.get('cooldown_days', 10)
                cutoff = (datetime.now() - timedelta(days=cooldown_days)).strftime('%Y-%m-%d')"""

if old_cooldown_load in content:
    content = content.replace(old_cooldown_load, new_cooldown_load, 1)
    print('4. 冷却期天数使用优化参数成功')
else:
    print('4. 未找到冷却期天数匹配')

with open('strategies/macd_resonance/breakout.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('修改完成')
