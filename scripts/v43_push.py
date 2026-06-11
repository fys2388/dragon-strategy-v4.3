# -*- coding: utf-8 -*-
import datetime, requests, time, random, os, sys

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
IS_CLOUD = os.getenv("IS_CLOUD", "false").lower() == "true"

sys.stdout = open("stock_push.log", "a", encoding="utf-8")
sys.stderr = open("stock_push.log", "a", encoding="utf-8")
print(f"=== 云端策略推送启动日志 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
print(f"运行环境: {'云端GitHub Actions' if IS_CLOUD else '本地'}")

def get_all_stocks_eastmoney():
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f20,f2"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            diff = r.json().get("data", {}).get("diff", [])
            stocks = []
            for d in diff:
                code = d["f12"]
                exchange = "SHSE" if code.startswith(("60", "68")) else "SZSE"
                stocks.append({
                    "symbol": f"{exchange}.{code}",
                    "symbol_name": d["f14"],
                    "circulating_market_cap": d["f20"] * 1e8,
                    "price": d["f2"]
                })
            return stocks
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        return []

def get_history_eastmoney(symbol, days):
    code = symbol.replace("SHSE.", "").replace("SZSE.", "")
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"1.{code}" if code.startswith(("60", "68")) else f"0.{code}",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101, "fqt": 1, "lmt": days
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            klines = r.json().get("data", {}).get("klines", [])
            bars = []
            for k in klines:
                parts = k.split(",")
                bars.append({
                    "close": float(parts[2]),
                    "pre_close": float(parts[1]),
                    "volume": float(parts[5])
                })
            return bars[-days:]
    except Exception as e:
        print(f"获取K线失败: {e}")
        return []

def get_index_eastmoney():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": 2, "invt": 2, "fields": "f1,f2,f3,f4,f14",
        "secids": "1.000001,0.399001,0.399006,1.000300,1.000016"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        diff = r.json().get("data", {}).get("diff", [])
        codes = ["SHSE.000001", "SZSE.399001", "SZSE.399006", "SHSE.000300", "SHSE.000016"]
        index_data = {}
        for i, d in enumerate(diff):
            index_data[codes[i]] = {"name": d["f14"], "price": d["f2"], "pct": round(d["f3"], 2)}
        return index_data
    except Exception as e:
        print(f"获取指数失败: {e}")
        return None

def get_limit_up_eastmoney():
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f1,f2,f3,f12,f14"
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            diff = r.json().get("data", {}).get("diff", [])
            return {"mainboard_count": len([d for d in diff if float(d.get("f3", 0)) >= 9.8])}
    except Exception as e:
        print(f"获取涨停数据失败: {e}")
    return {"mainboard_count": 0, "estimated": True, "note": "数据获取失败，使用估算值"}

def strategy_a():
    selected = []
    all_sym = get_all_stocks_eastmoney()
    if not all_sym:
        print("无法获取股票列表")
        return []
    
    for s in all_sym:
        symbol, name = s["symbol"], s["symbol_name"]
        try:
            if "ST" in name or "*ST" in name:
                continue
            mcap = s["circulating_market_cap"] / 1e8
            if not (40 <= mcap <= 500):
                continue
            price = s["price"]
            if not (3.5 <= price <= 30):
                continue

            bars_7d = get_history_eastmoney(symbol, 7)
            if len(bars_7d) < 7:
                continue
            max_chg_7d = max([(b["close"] - b["pre_close"]) / b["pre_close"] * 100 for b in bars_7d])
            if max_chg_7d < 7:
                continue
            chg_3d = (price - bars_7d[-3]["close"]) / bars_7d[-3]["close"] * 100
            if chg_3d < 3:
                continue

            avg_vol_5d = sum([b["volume"] for b in bars_7d[-5:]]) / 5
            vol_ratio = bars_7d[-1]["volume"] / avg_vol_5d
            if vol_ratio < 1.2:
                continue

            bars_60d = get_history_eastmoney(symbol, 60)
            if len(bars_60d) < 60:
                continue
            ma60 = sum([b["close"] for b in bars_60d]) / 60
            if price < ma60 * 0.85:
                continue

            selected.append({
                "code": symbol.replace("SHSE.", "").replace("SZSE.", ""),
                "name": name,
                "price": round(price, 2),
                "max_chg_7d": round(max_chg_7d, 1),
                "chg_3d": round(chg_3d, 1),
                "vol_ratio": round(vol_ratio, 2)
            })
        except Exception as e:
            continue
    selected.sort(key=lambda x: (x["chg_3d"], x["vol_ratio"]), reverse=True)
    return selected[:5]

def generate_push_content(is_intraday=False):
    idx_data = get_index_eastmoney()
    limit_up = get_limit_up_eastmoney()
    stocks = strategy_a()
    now = datetime.datetime.now()
    
    if is_intraday:
        content = f"""📊 盘中更新 {now.strftime('%H:%M')}
---
上证指数：{idx_data['SHSE.000001']['price']:.2f} ({idx_data['SHSE.000001']['pct']:+.2f}%)
【标的状态】
"""
        if stocks:
            for stk in stocks[:3]:
                content += f"✅ {stk['name']}({stk['code']}): {stk['price']}元 | 3日涨幅{stk['chg_3d']}% | 量能倍数{stk['vol_ratio']}倍\n"
        else:
            content += "暂无新标的\n"
        content += "⚠️ 触及止盈止损请及时操作"
    else:
        avg_pct = sum([d["pct"] for d in idx_data.values()]) / len(idx_data.values())
        score = min(7, 2 if avg_pct >= 1 else 1 if avg_pct >= 0 else 0)
        suggestion = "🔴 弱势行情，仓位0-10%" if score <= 1 else "🟡 震荡行情，仓位10-30%" if score <= 3 else "🟢 强势行情，仓位30-50%"
        content = f"""📊 云端策略推送 {now.strftime('%Y-%m-%d %H:%M')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 上证指数：{idx_data['SHSE.000001']['price']:.2f} ({idx_data['SHSE.000001']['pct']:+.2f}%)
🟢 深证成指：{idx_data['SZSE.399001']['price']:.2f} ({idx_data['SZSE.399001']['pct']:+.2f}%)
🟢 创业板指：{idx_data['SZSE.399006']['price']:.2f} ({idx_data['SZSE.399006']['pct']:+.2f}%)

主板涨停：{limit_up['mainboard_count']}只
大盘评分：{score}/7分 | 操作建议：{suggestion}

【符合策略推荐】
"""
        if not stocks:
            content += "暂无符合条件的标的"
        else:
            for stk in stocks:
                content += f"""✅ {stk['name']}({stk['code']})
  现价：{stk['price']}元 | 3日涨幅：{stk['chg_3d']}%
  7日最大涨幅：{stk['max_chg_7d']}% | 量能倍数：{stk['vol_ratio']}倍
"""
        content += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
V4.4.0 云端纯东方财富API方案
"""
    return content

def send_feishu(content):
    if not FEISHU_WEBHOOK:
        print("未配置飞书Webhook，跳过推送")
        return
    try:
        requests.post(FEISHU_WEBHOOK, json={"msg_type": "text", "content": {"text": content}}, timeout=10)
        print("飞书推送成功")
    except Exception as e:
        print(f"飞书推送失败: {e}")

def main():
    now = datetime.datetime.now()
    print(f"脚本启动时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    weekday = now.weekday()
    if weekday >= 5:
        print("周末非交易时段，退出")
        exit()
    hour, minute = now.hour, now.minute
    if (hour < 9 or (hour == 9 and minute < 15)) or (hour > 15) or (hour == 11 and minute > 30) or (hour == 12):
        print("非交易时段，退出")
        exit()
    
    is_intraday = (hour in [10, 11, 13, 14]) and not (hour == 11 and minute == 30)
    idx_data = get_index_eastmoney()
    if not idx_data:
        print("指数获取失败，终止任务")
        return
    content = generate_push_content(is_intraday)
    send_feishu(content)
    print("推送任务完成")

if __name__ == "__main__":
    main()