# -*- coding: utf-8 -*-
"""查看Agent学习状态。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.weekly_optimizer import _load_records, analyze_breakout_performance, _load_optimization_state
import json
from collections import defaultdict

records = _load_records()
print(f'总跟踪记录数: {len(records)}')

by_strategy = defaultdict(list)
for r in records:
    by_strategy[r.get('strategy', 'unknown')].append(r)

for strategy, recs in by_strategy.items():
    completed = [r for r in recs if r.get('status') == 'completed' and r.get('day5_return_pct') is not None]
    pending = [r for r in recs if r.get('status') != 'completed']
    print(f'  {strategy}: 总{len(recs)}只, 已完成{len(completed)}只, 跟踪中{len(pending)}只')

perf = analyze_breakout_performance(records)
print()
print('=== 突破策略表现 ===')
print(json.dumps(perf, ensure_ascii=False, indent=2))

state = _load_optimization_state()
print()
print('=== 当前优化参数 ===')
print(json.dumps(state['current_params'], ensure_ascii=False, indent=2))
hist = state.get('history', [])
print(f'历史优化次数: {len(hist)}')
if state.get('last_optimization'):
    lo = state['last_optimization']
    print(f'上次优化: {lo["timestamp"]}')
    print(f'应用参数数: {len(lo.get("applied", []))}')

# 查看最近的跟踪记录详情
print()
print('=== 最近5条跟踪记录 ===')
for r in records[-5:]:
    code = r.get('code', '')
    name = r.get('name', '')
    strategy = r.get('strategy', '')
    status = r.get('status', '')
    day5 = r.get('day5_return_pct')
    day10 = r.get('day10_return_pct')
    scan_time = r.get('scan_time', '')
    print(f'  {name}({code}) | {strategy} | {status} | 5日:{day5}% | 10日:{day10}% | {scan_time}')
