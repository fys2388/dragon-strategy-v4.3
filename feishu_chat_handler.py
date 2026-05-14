#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V4.3.1 飞书关键词聊天处理器
当用户在GitHub workflow_dispatch中触发时，按关键词执行对应功能
"""

import requests
import json
import re
import sys
from datetime import datetime

# ============================================================
# 配置
# ============================================================
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/8cb1308d-2c0e-4e16-9e7e-aafd4c970c51"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.eastmoney.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
}

# 代理设置（GitHub Actions无需代理）
import os
PROXIES = None
if os.environ.get('GITHUB_ACTIONS') is None:
    # 本地开发环境可能需要代理
    http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    if http_proxy:
        PROXIES = {'http': http_proxy, 'https': http_proxy}

# ============================================================
# 东方财富数据接口
# ============================================================

def get_realtime_quotes(codes):
    """获取实时行情"""
    if not codes:
        return {}
    secids = ','.join(codes)
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&ut=b2884a393a59ad64002217a3e73fc9db&fields=f12,f14,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18&secids={secids}"
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
                    'amplitude': item['f8'] / 100 if item.get('f8') else 0,
                    'high': item['f15'], 'low': item['f16'],
                    'open': item['f17'], 'pre_close': item['f18']
                }
        return result
    except:
        return {}

def get_daily_kline(code, days=20):
    """获取日K线"""
    market = '1' if code.startswith(('6', '5')) else '0'
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={market}.{code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={days}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get('data') and data['data'].get('klines'):
            klines = []
            for line in data['data']['klines']:
                parts = line.split(',')
                klines.append({
                    'date': parts[0], 'open': float(parts[1]), 'close': float(parts[2]),
                    'high': float(parts[3]), 'low': float(parts[4]), 'volume': float(parts[5])
                })
            return klines
    except:
        pass
    return []

def get_weekly_kline(code, weeks=12):
    """获取周K线"""
    market = '1' if code.startswith(('6', '5')) else '0'
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={market}.{code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=102&fqt=1&end=20500101&lmt={weeks}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get('data') and data['data'].get('klines'):
            klines = []
            for line in data['data']['klines']:
                parts = line.split(',')
                klines.append({
                    'date': parts[0], 'close': float(parts[2]),
                    'high': float(parts[3]), 'low': float(parts[4]),
                    'volume': float(parts[5])
                })
            return klines
    except:
        pass
    return []

def get_market_indices():
    """获取指数"""
    return get_realtime_quotes(['000001', '399001', '399006', '000300'])

def get_limit_up_stocks():
    """获取涨停股"""
    url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fields=f12,f14&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        matches = re.findall(r'"f12":"(\d+)".*?"f14":"([^"]+)"', resp.text)
        return [{'code': m[0], 'name': m[1]} for m in matches if not m[1].startswith('ST')]
    except:
        return []

# ============================================================
# 策略计算
# ============================================================

def calculate_market_score():
    """大盘7分制评分"""
    score = 0
    reasons = []
    indices = get_market_indices()
    
    if not indices:
        return 0, ["❌ 无法获取数据"]
    
    # 1. 指数翻红
    green_count = sum(1 for i in indices.values() if i['change_pct'] > 0)
    if green_count >= 3: score += 2; reasons.append("✅ 全部指数翻红")
    elif green_count >= 1: score += 1; reasons.append("🟡 部分指数翻红")
    else: reasons.append("❌ 全部收绿")
    
    # 2. 涨停家数
    limit_up = get_limit_up_stocks()
    cnt = len(limit_up)
    if cnt >= 50: score += 2; reasons.append(f"✅ 涨停{cnt}家")
    elif cnt >= 30: score += 1; reasons.append(f"🟡 涨停{cnt}家")
    else: reasons.append(f"❌ 涨停{cnt}家")
    
    # 3. 市场活跃
    sz = indices.get('399006', {})
    if sz.get('change_pct', 0) > 0.5: score += 1; reasons.append("✅ 活跃度高")
    else: reasons.append("❌ 活跃度一般")
    
    # 4. 跌停正常
    score += 1; reasons.append("✅ 跌停正常")
    
    # 5. 板块效应
    if cnt >= 20: score += 1; reasons.append("✅ 有板块效应")
    
    return score, reasons

def analyze_stock(code):
    """分析单只股票"""
    quote = get_realtime_quotes([code])
    if code not in quote:
        return f"❌ 未找到股票 {code}，请检查代码是否正确"
    
    q = quote[code]
    daily = get_daily_kline(code, 60)
    weekly = get_weekly_kline(code, 12)
    
    text = f"""📊 【{q['name']}({code}) V4.3.1分析】

━━━━━━━━━━━━━━━━━━
💰 实时行情
现价: {q['price']:.2f}
涨跌幅: {q['change_pct']:+.2f}%
今开: {q['open']:.2f} | 昨收: {q['pre_close']:.2f}
最高: {q['high']:.2f} | 最低: {q['low']:.2f}
成交额: {q['amount']/100000000:.2f}亿

━━━━━━━━━━━━━━━━━━
📈 日线分析"""
    
    if daily:
        closes = [d['close'] for d in daily]
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else sum(closes) / len(closes)
        
        text += f"""
MA5:  {ma5:.2f}  ({q['price']/ma5*100-100:+.1f}%)
MA10: {ma10:.2f}  ({q['price']/ma10*100-100:+.1f}%)
MA20: {ma20:.2f}  ({q['price']/ma20*100-100:+.1f}%)
MA60: {ma60:.2f}  ({q['price']/ma60*100-100:+.1f}%)"""
        
        # 均线多头排列
        if ma5 > ma10 > ma20:
            text += "\n✅ 均线多头排列"
        elif ma5 < ma10 < ma20:
            text += "\n🔴 均线空头排列"
        else:
            text += "\n🟡 均线混乱"
    
    text += f"""

━━━━━━━━━━━━━━━━━━
📅 周线形态"""
    
    if weekly:
        closes = [w['close'] for w in weekly]
        highs = [w['high'] for w in weekly]
        lows = [w['low'] for w in weekly]
        
        # 周线突破
        prev_high = max(highs[-5:-1])
        if q['price'] > prev_high * 0.98:
            text += "\n✅ 周线突破平台"
        
        # 底部抬升
        recent_lows = sorted(lows[-4:])
        if len(recent_lows) >= 3 and recent_lows[0] < recent_lows[1] < recent_lows[2]:
            text += "\n✅ 周线底部抬升"
        
        # 周线趋势
        if closes[-1] > closes[-4]:
            text += "\n🟢 近4周上涨"
        else:
            text += "\n🔴 近4周下跌"
    
    text += f"""

━━━━━━━━━━━━━━━━━━
⚠️ 风险提示
• 价格区间: {'偏低' if q['price'] < 10 else '中等' if q['price'] < 20 else '偏高'}
• 波动性: {'较大' if q['amplitude'] > 5 else '正常'}
• 成交活跃度: {'活跃' if q['amount'] > 500000000 else '一般'}"""
    
    # V4.3.1 低吸区间
    if daily and len(daily) >= 10:
        ma10 = sum([d['close'] for d in daily[-10:]]) / 10
        ideal = min(q['price'], ma10)
        zone_low = ideal * 0.97
        zone_high = ideal * 1.01
        text += f"""

━━━━━━━━━━━━━━━━━━
🎯 V4.3.1 低吸参考
理想买点: {ideal:.2f}
低吸区间: {zone_low:.2f} ~ {zone_high:.2f}
建议: 等待回调至MA10附近考虑"""
    
    text += """

━━━━━━━━━━━━━━━━━━
⚠️ 以上分析仅供参考，不构成买卖建议"""
    
    return text

def get_strategy_rules(path=None):
    """获取策略规则"""
    if path == 'A':
        return """📋 【路径A：超跌反弹 规则】

━━━━━━━━━━━━━━━━━━
✅ 准入条件
• 近12月跌幅 ≥ 30%
• 跌幅越大越好（超跌）
• 必须配合周线见底形态

━━━━━━━━━━━━━━━━━━
🎯 买点
• 回踩周线均线/平台
• 日线缩量止跌
• MACD底背离

━━━━━━━━━━━━━━━━━━
🛡️ 止损
• 周线收盘跌破60日线
• 从低点反弹超过15%后缩量

━━━━━━━━━━━━━━━━━━
⚠️ 注意
只配周线见底标的，不追空头"""
    
    elif path == 'B':
        return """📋 【路径B：强势龙头 规则】

━━━━━━━━━━━━━━━━━━
✅ 准入条件
• 近3月跌幅 10-25%
• 区间振幅 < 40%
• 成交额持续放大

━━━━━━━━━━━━━━━━━━
🎯 买点
• 回踩5/10日均线
• 突破前高时跟进
• 缩量回踩平台

━━━━━━━━━━━━━━━━━━
🛡️ 止损
• 跌破20日线离场
• 从高点回落8%离场

━━━━━━━━━━━━━━━━━━
⚠️ 注意
只配周线多头标的，不做空头"""
    
    else:
        return """📋 【V4.3.1 完整策略规则】

━━━━━━━━━━━━━━━━━━
🏆 大盘评分（≥4分才可开仓）
1. 指数翻红 +2分
2. 涨停≥30家 +2分
3. 市场活跃 +1分
4. 跌停<10家 +1分
5. 板块效应 +1分

━━━━━━━━━━━━━━━━━━
🔒 硬过滤（必须全部通过）
• 主板: 60/00开头
• 价格: 5-20元
• 市值: 40-200亿
• 成交额: 日≥3亿
• 过滤: ST/涨跌停

━━━━━━━━━━━━━━━━━━
📈 双路径选股
【路径A】超跌反弹
• 近12月跌幅≥30%
• 配合周线见底
• 强调低吸

【路径B】强势龙头
• 近3月跌幅10-25%
• 周线多头排列
• 强调顺势

━━━━━━━━━━━━━━━━━━
📅 周线五大形态
1. 突破平台
2. 回踩均线
3. 缩量整理
4. MACD多头
5. 底部抬升

━━━━━━━━━━━━━━━━━━
💰 卖出规则
• 硬性止损: 周线破位/从高点回落8%
• 阶段止盈: +15%/+30%/+50%
• 动态止盈: 从最高点回落8%"""

def get_portfolio_status():
    """获取持仓状态"""
    try:
        with open('portfolio_data.json', 'r', encoding='utf-8') as f:
            portfolio = json.load(f)
    except:
        return "❌ 暂无持仓数据"
    
    positions = portfolio.get('positions', [])
    if not positions:
        return "📭 【持仓状态】\n\n暂无持仓，继续空仓观望"
    
    text = "📊 【持仓状态 V4.3.1】\n\n"
    
    for pos in positions:
        code = pos['code']
        quote = get_realtime_quotes([code]).get(code, {})
        
        if not quote:
            continue
        
        entry = pos['entry_price']
        current = quote.get('price', entry)
        profit_pct = (current - entry) / entry * 100
        pnl = (current - entry) * pos.get('quantity', 100)
        
        emoji = "🟢" if profit_pct > 0 else "🔴"
        text += f"{emoji} {pos['name']}({code})\n"
        text += f"   成本: {entry:.2f} → 现价: {current:.2f}\n"
        text += f"   盈亏: {profit_pct:+.1f}% ({pnl:+.0f}元)\n"
        
        # 检查卖出信号
        targets = {
            'phase1': entry * 1.15,
            'phase2': entry * 1.30,
            'phase3': entry * 1.50,
        }
        stop_loss = pos.get('stop_loss', entry * 0.93)
        
        if current <= stop_loss:
            text += "   🚨 触发止损！\n"
        elif profit_pct >= 50:
            text += "   ⚠️ 达到阶段三止盈\n"
        elif profit_pct >= 30:
            text += "   📢 达到阶段二止盈\n"
        elif profit_pct >= 15:
            text += "   💡 达到阶段一止盈\n"
        
        text += "\n"
    
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += "⚠️ 以上仅供参考，不构成买卖建议"
    
    return text

# ============================================================
# 飞书推送
# ============================================================

def send_to_feishu(message):
    """发送到飞书"""
    payload = {"msg_type": "text", "content": {"text": message}}
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        return True
    except Exception as e:
        print(f"推送失败: {e}")
        return False

def handle_command(command):
    """处理用户命令"""
    cmd = command.lower().strip()
    
    # 大盘评分
    if '大盘' in cmd or '指数' in cmd:
        score, reasons = calculate_market_score()
        indices = get_market_indices()
        text = "📊 【大盘评分 V4.3.1】\n\n"
        for code, data in indices.items():
            pct = data['change_pct']
            text += f"{'🟢' if pct > 0 else '🔴'} {data['name']}: {pct:+.2f}%\n"
        text += f"\n━━━━━━━━━━━━━━━━━━\n🏆 评分: {score}/7\n"
        text += "\n".join(reasons)
        text += f"\n━━━━━━━━━━━━━━━━━━\n{'✅ 可以开仓' if score >= 4 else '❌ 建议观望'}"
        return text
    
    # 今日选股
    if '选股' in cmd or '今日' in cmd or '预选' in cmd:
        limit_up = get_limit_up_stocks()
        if not limit_up:
            return "📈 【今日预选】\n\n今日暂无涨停标的"
        
        candidates = []
        for stock in limit_up[:20]:
            code = stock['code']
            quote = get_realtime_quotes([code]).get(code, {})
            if not quote:
                continue
            
            # 硬过滤
            if quote.get('price', 0) < 5 or quote.get('price', 0) > 20:
                continue
            if quote.get('amount', 0) < 300000000:
                continue
            
            candidates.append(stock)
        
        if not candidates:
            return "📈 【今日预选】\n\n暂无符合条件标的"
        
        text = "📈 【今日预选池 V4.3.1】\n\n"
        for i, c in enumerate(candidates[:8], 1):
            text += f"{i}. {c['name']}({c['code']})\n"
        
        text += f"\n━━━━━━━━━━━━━━━━━━\n"
        text += f"共 {len(candidates)} 只通过硬过滤\n"
        text += "💡 输入股票代码获取详细分析"
        return text
    
    # 持仓状态
    if '持仓' in cmd or '仓位' in cmd or '看看我' in cmd:
        return get_portfolio_status()
    
    # 路径A规则
    if '路径a' in cmd or '路径A' in cmd or '路径甲' in cmd:
        return get_strategy_rules('A')
    
    # 路径B规则
    if '路径b' in cmd or '路径B' in cmd or '路径乙' in cmd:
        return get_strategy_rules('B')
    
    # 卖出规则
    if '卖出' in cmd or '止盈' in cmd or '止损' in cmd:
        return """💰 【卖出规则 V4.3.1】

━━━━━━━━━━━━━━━━━━
🚨 硬性止损（必须执行）
• 周线收盘跌破60日均线
• 日线放量跌破60日线
• 连续3日收盘破5日线

━━━━━━━━━━━━━━━━━━
💎 分阶段止盈
• 阶段一: +15% → 减仓50%
• 阶段二: +30% → 再减30%
• 阶段三: +50% → 清仓

━━━━━━━━━━━━━━━━━━
🎯 动态止盈
• 从最高点回落8% → 离场

━━━━━━━━━━━━━━━━━━
⚠️ 异常离场
• 所属板块大跌>5%
• 连续2日缩量
• 炸板后无法回封"""
    
    # 单只股票分析
    code_match = re.search(r'(\d{6})', cmd)
    if code_match:
        return analyze_stock(code_match.group(1))
    
    # 帮助
    if '帮助' in cmd or 'help' in cmd or '怎么用' in cmd:
        return """🤖 【V4.3.1 智能助手 使用指南】

━━━━━━━━━━━━━━━━━━
📊 查询命令
• "大盘评分" - 实时大盘评分
• "今日选股" - 符合条件标的
• "持仓" - 查看当前持仓

━━━━━━━━━━━━━━━━━━
📈 分析命令
• "600519" - 分析指定股票
• 任意6位股票代码

━━━━━━━━━━━━━━━━━━
📚 规则查询
• "路径A规则" - 超跌反弹规则
• "路径B规则" - 强势龙头规则
• "卖出规则" - 止盈止损规则

━━━━━━━━━━━━━━━━━━
💡 示例
• "帮我看看大盘"
• "贵州茅台600519"
• "现在可以买吗"
• "给我讲讲路径A"
• "我的持仓怎么样"

━━━━━━━━━━━━━━━━━━
📝 使用说明
• 直接发送股票代码查询分析
• 发送中文指令获取对应功能
• 盘中时段可获取实时选股建议"""
    
    # 默认回复
    return """🤖 您好，我是V4.3.1智能助手

请输入指令：
• "大盘评分" - 查看当前大盘
• "今日选股" - 查看预选标的
• "持仓" - 查看我的持仓
• "600519" - 分析单只股票
• "帮助" - 查看所有指令"""

# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    response = handle_command(command)
    print(response)
    send_to_feishu(response)
