# -*- coding: utf-8 -*-
import json
from collections import defaultdict, Counter

with open('data/quality_pool_raw.json', 'r', encoding='utf-8') as f:
    stocks = json.load(f)

# 进一步筛选：PE 0-80，市值40-300亿
filtered = [s for s in stocks if 0 < s['pe'] <= 80 and 40 <= s['mcap_yi'] <= 300]
print(f'PE 0-80 + 市值40-300亿: {len(filtered)}只')

# 按行业分组
by_sector = defaultdict(list)
for s in filtered:
    for sec in s['sectors']:
        by_sector[sec].append(s)

selected = {}
sector_quota = {
    'new_energy': 35,
    'semi': 20,
    'ai': 40,
    'consumer': 40,
    'medical': 25,
    'manufacturing': 40,
}

for sec, quota in sector_quota.items():
    sector_stocks = sorted(by_sector.get(sec, []), key=lambda x: x['mcap_yi'], reverse=True)
    for s in sector_stocks[:quota]:
        if s['code'] not in selected:
            selected[s['code']] = s

final = list(selected.values())
final.sort(key=lambda x: x['mcap_yi'], reverse=True)

# 保存最终股票池
pool_codes = [{'code': s['code'], 'name': s['name']} for s in final]
with open('data/quality_pool.json', 'w', encoding='utf-8') as f:
    json.dump(pool_codes, f, ensure_ascii=False, indent=2)

with open('data/quality_pool_detail.json', 'w', encoding='utf-8') as f:
    json.dump(final, f, ensure_ascii=False, indent=2)

print(f'\n最终精选: {len(final)}只')
print('行业分布:')
sector_count = Counter()
for s in final:
    for sec in s['sectors']:
        sector_count[sec] += 1
for sec, cnt in sector_count.most_common():
    print(f'  {sec}: {cnt}只')

mcaps = [s['mcap_yi'] for s in final]
pes = [s['pe'] for s in final]
print(f'\n市值范围: {min(mcaps)}亿 - {max(mcaps)}亿')
print(f'PE范围: {min(pes)} - {max(pes)}')
print(f'\n前10只:')
for s in final[:10]:
    print(f"  {s['name']}({s['code']}) 市值{s['mcap_yi']}亿 PE{s['pe']} {s['sectors']}")
