# -*- coding: utf-8 -*-
import datetime
import requests
import os
import sys

log_file = open("stock_push.log", "a", encoding="utf-8")
sys.stdout = log_file
sys.stderr = log_file

print(f"\n{'='*60}")
print(f"=== 云端策略推送启动日志 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
print(f"{'='*60}")

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK_URL", "")
IS_CLOUD = os.getenv("IS_CLOUD", "false").lower() == "true"
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

print(f"环境: {'云端GitHub Actions' if IS_CLOUD else '本地'}")
print(f"测试模式: {'开启' if TEST_MODE else '关闭'}")
print(f"Webhook已配置: {'是' if FEISHU_WEBHOOK else '否'}")
if not FEISHU_WEBHOOK:
    print("警告: FEISHU_WEBHOOK_URL 环境变量为空!")
print(f"Webhook前30字符: {FEISHU_WEBHOOK[:30] if FEISHU_WEBHOOK else '无'}...")

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
            print(f"获取股票列表成功: {len(stocks)}只")
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
        print(f"获取指数成功: {len(index_data)}个")
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
    return {"mainboard_count": 0}

def strategy_a():
    selected = []
    all_sym = get_all_stocks_eastmoney()
    if not all_sym:
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
        except Exception:
            continue
    selected.sort(key=lambda x: (x["chg_3d"], x["vol_ratio"]), reverse=True)
    return selected[:5]

def generate_push_content(is_intraday=False):
    idx_data = get_index_eastmoney()
    limit_up = get_limit_up_eastmoney()
    stocks = strategy_a()
    now = datetime.datetime.now()
    
    if is_intraday:
        content = f"\uD83D\uDCCA 盘中更新 {now.strftime('%H:%M')}\n"
        content += "---\n"
        if idx_data:
            content += f"上证指数：{idx_data['SHSE.000001']['price']:.2f} ({idx_data['SHSE.000001']['pct']:+.2f}%)\n"
        content += "\n[\u6807\u7684\u72B6\u6001]\n"
        if stocks:
            for stk in stocks[:3]:
                content += f"\u2705 {stk['name']}({stk['code']}): {stk['price']}元 | 3日{stk['chg_3d']}% | 量能{stk['vol_ratio']}倍\n"
        else:
            content += "\u6682\u65E0\u65B0\u6807\u7684\n"
        content += "\u26A0\uFE0F 触及止盈止损请及时操作"
    else:
        if not idx_data:
            return f"\uD83D\uDCCA 云端策略推送 {now.strftime('%Y-%m-%d %H:%M')}\n指数数据获取失败，请稍后重试"
        avg_pct = sum([d["pct"] for d in idx_data.values()]) / len(idx_data.values())
        score = min(7, 2 if avg_pct >= 1 else 1 if avg_pct >= 0 else 0)
        suggestion = "\uD83D\uDD34 弱势行情，仓位0-10%" if score <= 1 else "\uD83D\uDFE1 震荡行情，仓位10-30%" if score <= 3 else "\uD83D\uDFE2 强势行情，仓位30-50%"
        content = f"\uD83D\uDCCA 云端策略推送 {now.strftime('%Y-%m-%d %H:%M')}\n"
        content += "="*40 + "\n"
        content += f"\uD83D\uDFE2 上证指数：{idx_data['SHSE.000001']['price']:.2f} ({idx_data['SHSE.000001']['pct']:+.2f}%)\n"
        content += f"\uD83D\uDFE2 深证成指：{idx_data['SZSE.399001']['price']:.2f} ({idx_data['SZSE.399001']['pct']:+.2f}%)\n"
        content += f"\uD83D\uDFE2 创业板指：{idx_data['SZSE.399006']['price']:.2f} ({idx_data['SZSE.399006']['pct']:+.2f}%)\n\n"
        content += f"\u4E3B\u677F\u6DA8\u505C\uFF1A{limit_up['mainboard_count']}只\n"
        content += f"\u5927\u76D8\u8BC4\u5206\uFF1A{score}/7分 | \u64CD\u4F5C\u5EFA\u8BAE\uFF1A{suggestion}\n\n"
        content += "[\u7B26\u5408\u7B56\u7565\u63A8\u8350]\n"
        if not stocks:
            content += "\u6682\u65E0\u7B26\u5408\u6761\u4EF6\u7684\u6807\u7684"
        else:
            for stk in stocks:
                content += f"\u2705 {stk['name']}({stk['code']})\n"
                content += f"  \u73B0\u4EF7\uFF1A{stk['price']}元 | 3日涨幅：{stk['chg_3d']}%\n"
                content += f"  7日最大涨幅：{stk['max_chg_7d']}% | 量能倍数：{stk['vol_ratio']}倍\n\n"
        content += "\n" + "="*40 + "\n"
        content += "V4.4.0 云端纯东方财富API方案"
    return content

def send_feishu(content):
    if not FEISHU_WEBHOOK:
        print("未配置飞书Webhook，跳过推送")
        return False
    try:
        print(f"准备推送，内容长度: {len(content)}")
        print(f"Webhook前20字符: {FEISHU_WEBHOOK[:20]}...")
        payload = {"msg_type": "text", "content": {"text": content}}
        print(f"Payload构造完成，msg_type: text")
        response = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        print(f"HTTP状态码: {response.status_code}")
        print(f"响应内容: {response.text[:200]}")
        if response.status_code == 200:
            result = response.json()
            code = result.get("code", result.get("StatusCode", -1))
            msg = result.get("msg", result.get("StatusMessage", ""))
            if code == 0:
                print(f"\u2705\u98DE\u4E66\u63A8\u9001\u6210\u529F!")
                return True
            else:
                print(f"\u274C\u98DE\u4E66\u63A8\u9001\u5931\u8D25: code={code}, msg={msg}")
                return False
        else:
            print(f"\u274C HTTP\u9519\u8BEF: {response.status_code}")
            return False
    except Exception as e:
        print(f"\u274C\u98DE\u4E66\u63A8\u9001\u5F02\u5E38: {e}")
        return False

def main():
    now = datetime.datetime.now()
    print(f"脚本启动时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not TEST_MODE:
        weekday = now.weekday()
        if weekday >= 5:
            print("周末非交易时段，退出")
            return
        hour, minute = now.hour, now.minute
        if (hour < 9 or (hour == 9 and minute < 15)) or (hour > 15) or (hour == 11 and minute > 30) or (hour == 12):
            print("非交易时段，退出")
            return
    else:
        print("测试模式：跳过交易时段检查")
    
    hour, minute = now.hour, now.minute
    is_intraday = (hour in [10, 11, 13, 14]) and not (hour == 11 and minute == 30)
    
    idx_data = get_index_eastmoney()
    if not idx_data:
        print("指数获取失败，终止任务")
        return
    
    content = generate_push_content(is_intraday)
    print(f"内容生成完成，长度: {len(content)}")
    
    success = send_feishu(content)
    if success:
        print("=== \u63A8\u9001\u4EFB\u52A1\u5B8C\u6210 ===")
    else:
        print("=== \u63A8\u9001\u5931\u8D25 ===")

if __name__ == "__main__":
    main()
