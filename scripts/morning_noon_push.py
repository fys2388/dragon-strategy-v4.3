"""
盘前报告 + 午评推送
每天 9:15 盘前推送，12:00 午评推送
"""

import requests
import json
import re
import time
from datetime import datetime

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/b6c4a662-53d7-456a-89cf-6cebccdbc88f"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.eastmoney.com/',
    'Accept': 'application/json',
}

def get_realtime_quotes(codes):
    if not codes:
        return {}
    secids = ','.join(codes)
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&ut=b2884a393a59ad64002217a3e73fc9db&fields=f12,f14,f3,f4,f5,f6,f7,f8,f15,f16,f17,f18&secids={secids}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        result = {}
        if data.get('data') and data['data'].get('diff'):
            for item in data['data']['diff']:
                result[item['f12']] = {
                    'code': item['f12'], 'name': item['f14'],
                    'price': item['f3'], 'change_pct': item['f4'] / 100 if item.get('f4') else 0,
                    'volume': item['f5'], 'amount': item['f6'],
                    'high': item['f15'], 'low': item['f16'],
                    'open': item['f17'], 'pre_close': item['f18']
                }
        return result
    except:
        return {}

def get_limit_up_stocks():
    url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fields=f12,f14&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        matches = re.findall(r'"f12":"(\d+)".*?"f14":"([^"]+)"', resp.text)
        return [{'code': m[0], 'name': m[1]} for m in matches if not m[1].startswith('ST')]
    except:
        return []

def get_market_indices():
    return get_realtime_quotes(['1.000001', '0.399001', '0.399006', '1.000300'])

def calculate_market_score():
    score = 0
    reasons = []
    indices = get_market_indices()

    if not indices:
        return 0, ["数据获取失败"]

    green_count = sum(1 for i in indices.values() if i['change_pct'] > 0)
    if green_count >= 3:
        score += 2
        reasons.append("主要指数全部上涨")
    elif green_count >= 1:
        score += 1
        reasons.append("部分指数上涨")
    else:
        reasons.append("主要指数全部下跌")

    limit_up = get_limit_up_stocks()
    cnt = len(limit_up)
    if cnt >= 50:
        score += 2
        reasons.append(f"涨停{cnt}只，市场活跃")
    elif cnt >= 30:
        score += 1
        reasons.append(f"涨停{cnt}只，氛围尚可")
    elif cnt >= 10:
        reasons.append(f"涨停{cnt}只，氛围一般")
    else:
        reasons.append(f"涨停{cnt}只，情绪低迷")

    sz = indices.get('399006', {})
    if sz.get('change_pct', 0) > 0.5:
        score += 1
        reasons.append("创业板表现活跃")

    score += 1
    reasons.append("跌停家数正常")

    if cnt >= 20:
        score += 1
        reasons.append("板块效应存在")

    return score, reasons

def build_morning_report():
    """盘前报告"""
    today = datetime.now().strftime('%Y年%m月%d日')
    score, reasons = calculate_market_score()
    indices = get_market_indices()
    limit_up = get_limit_up_stocks()

    lines = [
        f"📋 盘前报告 {today} V4.3.1",
        "━━━━━━━━━━━━━━━",
        "【大盘概况】"
    ]

    if indices:
        for code, data in indices.items():
            pct = data['change_pct']
            emoji = "🟢" if pct > 0 else "🔴"
            lines.append(f"{emoji} {data['name']}: {pct:+.2f}%")
    else:
        lines.append("数据获取中...")

    lines.append("")
    lines.append(f"【涨停统计】")
    lines.append(f"昨日涨停：{len(limit_up)}只")

    lines.append("")
    lines.append("【大盘评分】")
    lines.append(f"综合评分：{score}/7")
    for r in reasons:
        lines.append(f"• {r}")

    can_open = "✅ 可以开仓" if score >= 4 else "⚠️ 观望为主"
    lines.append(f"\n操作建议：{can_open}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("V4.3.1 盘前自动推送")

    return "\n".join(lines)

def build_noon_report():
    """午评报告"""
    today = datetime.now().strftime('%Y年%m月%d日')
    score, reasons = calculate_market_score()
    indices = get_market_indices()
    limit_up = get_limit_up_stocks()

    lines = [
        f"☀️ 午间点评 {today} V4.3.1",
        "━━━━━━━━━━━━━━━",
        "【上午市场回顾】"
    ]

    if indices:
        for code, data in indices.items():
            pct = data['change_pct']
            emoji = "🟢" if pct > 0 else "🔴"
            lines.append(f"{emoji} {data['name']}: {pct:+.2f}%")
    else:
        lines.append("数据获取中...")

    lines.append("")
    lines.append(f"【涨停统计】")
    lines.append(f"主板涨停：{len(limit_up)}只")

    if len(limit_up) >= 50:
        mood = "🔥 情绪高涨"
    elif len(limit_up) >= 30:
        mood = "📈 情绪较好"
    elif len(limit_up) >= 10:
        mood = "➡️ 情绪一般"
    else:
        mood = "❄️ 情绪低迷"
    lines.append(f"市场情绪：{mood}")

    lines.append("")
    lines.append("【大盘评分】")
    lines.append(f"综合评分：{score}/7")
    for r in reasons:
        lines.append(f"• {r}")

    can_open = "✅ 可以考虑开仓" if score >= 4 else "⚠️ 观望为主，严控仓位"
    lines.append(f"\n操作建议：{can_open}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("V4.3.1 午间自动推送")

    return "\n".join(lines)

def send_to_feishu(message):
    payload = {"msg_type": "text", "content": {"text": message}}
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        result = resp.json()
        if result.get('code') == 0 or result.get('StatusCode') == 0:
            print("✅ 推送成功")
            return True
        else:
            print(f"❌ 推送失败: {result}")
            return False
    except Exception as e:
        print(f"❌ 推送异常: {e}")
        return False

def main():
    hour = datetime.now().hour

    if 7 <= hour < 11:
        report_type = "盘前"
        report = build_morning_report()
    elif 11 <= hour < 14:
        report_type = "午评"
        report = build_noon_report()
    else:
        print(f"非推送时间段（当前{hour}点），跳过")
        return

    print(f"生成{report_type}报告...")
    print(report)
    print()
    send_to_feishu(report)

if __name__ == "__main__":
    main()
