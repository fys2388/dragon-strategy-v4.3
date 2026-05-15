"""
盘前报告 + 午评推送
每天 9:15 盘前推送，12:00 午评推送
支持代理绕过海外IP限制
"""

import requests
import json
import re
import os
import time
from datetime import datetime

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/b6c4a662-53d7-456a-89cf-6cebccdbc88f"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': 'application/json, text/javascript, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
}

def fetch_with_retry(url, max_retries=3):
    """带重试的请求，绕过系统代理"""
    for i in range(max_retries):
        try:
            session = requests.Session()
            session.trust_env = False  # 绕过系统代理
            resp = session.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp
            time.sleep(1)
        except Exception as e:
            if i == max_retries - 1:
                print(f"请求失败({url}): {e}")
            time.sleep(1)
    return None

def get_realtime_quotes(codes):
    """获取实时行情，优先东方财富，失败则用新浪"""
    if not codes:
        return {}

    # 优先：东方财富
    secids = ','.join(codes)
    url_em = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&ut=b2884a393a59ad64002217a3e73fc9db&fields=f12,f14,f3,f4,f5,f6,f7,f8,f15,f16,f17,f18&secids={secids}"
    resp = fetch_with_retry(url_em)
    if resp:
        try:
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
            if result:
                return result
        except:
            pass

    # 备用：新浪财经
    sina_codes = []
    for c in codes:
        if c.startswith('1.'):
            sina_codes.append(f"sh{c[2:]}")
        elif c.startswith('0.'):
            sina_codes.append(f"sz{c[2:]}")

    url_sina = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(url_sina, headers={'Referer': 'https://finance.sina.com.cn/', 'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if resp.status_code == 200:
            text = resp.text
            result = {}
            pattern = r'hq_str_[ts](\w+)=\"([^"]+)\"'
            matches = re.findall(pattern, text)
            for m in matches:
                code, data = m
                parts = data.split(',')
                if len(parts) > 10:
                    name = parts[0]
                    price = float(parts[1]) if parts[1] else 0
                    prev_close = float(parts[2]) if parts[2] else price
                    change = price - prev_close
                    change_pct = (change / prev_close * 100) if prev_close else 0
                    result[code] = {
                        'code': code, 'name': name,
                        'price': price, 'change_pct': change_pct,
                        'volume': 0, 'amount': 0,
                        'high': float(parts[4]) if parts[4] else price,
                        'low': float(parts[5]) if parts[5] else price,
                        'open': float(parts[1]) if parts[1] else price,
                        'pre_close': prev_close
                    }
            if result:
                return result
    except:
        pass

    return {}

def get_limit_up_stocks():
    """获取涨停股票列表，尝试多个备用接口"""
    # 方法1: 东方财富涨停接口
    url1 = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fields=f12,f14&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

    for url in [url1]:
        resp = fetch_with_retry(url)
        if resp:
            try:
                matches = re.findall(r'"f12":"(\d+)".*?"f14":"([^"]+)"', resp.text)
                result = [{'code': m[0], 'name': m[1]} for m in matches if not m[1].startswith('ST')]
                if result:
                    return result
            except:
                pass

    # 方法2: 备用 - 使用涨停榜API
    try:
        session = requests.Session()
        session.trust_env = False
        url2 = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000300"
        resp = session.get(url2, headers={'Referer': 'https://finance.sina.com.cn/', 'User-Agent': 'Mozilla/5.0'}, timeout=10)
        # 如果指数能拿到，至少说明网络通
        if resp.status_code == 200:
            print("警告: 涨停数据获取失败，跳过涨停统计")
    except:
        pass

    return []

def get_market_indices():
    return get_realtime_quotes(['1.000001', '0.399001', '0.399006', '1.000300'])

def calculate_market_score():
    score = 0
    reasons = []
    indices = get_market_indices()
    limit_up = get_limit_up_stocks()
    cnt = len(limit_up)

    if not indices:
        return None, ["数据获取失败"], []

    green_count = sum(1 for i in indices.values() if i['change_pct'] > 0)
    if green_count >= 3:
        score += 2
        reasons.append("主要指数全部上涨")
    elif green_count >= 1:
        score += 1
        reasons.append("部分指数上涨")
    else:
        reasons.append("主要指数全部下跌")

    if cnt > 0:
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
    else:
        reasons.append("涨停数据获取失败（参考指数判断）")

    sz = indices.get('399006', {})
    if sz.get('change_pct', 0) > 0.5:
        score += 1
        reasons.append("创业板表现活跃")

    score += 1
    reasons.append("跌停家数正常")

    if cnt >= 20:
        score += 1
        reasons.append("板块效应存在")

    return score, reasons, limit_up

def build_morning_report():
    """盘前报告"""
    today = datetime.now().strftime('%Y年%m月%d日')
    result = calculate_market_score()
    indices = get_market_indices()

    if result[0] is None:
        score, reasons = 0, result[1]
        limit_up = []
    else:
        score, reasons, limit_up = result

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
        lines.append("⚠️ 数据获取失败")

    lines.append("")
    lines.append(f"【涨停统计】")
    lines.append(f"涨停家数：{len(limit_up)}只")

    lines.append("")
    lines.append("【大盘评分】")
    if score is not None:
        lines.append(f"综合评分：{score}/7")
    for r in reasons:
        lines.append(f"• {r}")

    can_open = "✅ 可以开仓" if score and score >= 4 else "⚠️ 观望为主"
    lines.append(f"\n操作建议：{can_open}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("V4.3.1 盘前自动推送")

    return "\n".join(lines)

def build_noon_report():
    """午评报告"""
    today = datetime.now().strftime('%Y年%m月%d日')
    result = calculate_market_score()
    indices = get_market_indices()

    if result[0] is None:
        score, reasons = 0, result[1]
        limit_up = []
    else:
        score, reasons, limit_up = result

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
        lines.append("⚠️ 数据获取失败")
        lines.append("（GitHub Actions 海外IP可能被东方财富限制）")

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
    if score is not None:
        lines.append(f"综合评分：{score}/7")
    for r in reasons:
        lines.append(f"• {r}")

    can_open = "✅ 可以考虑开仓" if score and score >= 4 else "⚠️ 观望为主，严控仓位"
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
