# -*- coding: utf-8 -*-
import datetime, requests, time, random, os, sys

# ====================== 基础配置 & 日志 & 单例锁 ======================
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK_URL", "")
LOG_FILE = "stock_push.log"

# 日志重定向
sys.stdout = open(LOG_FILE, "a", encoding="utf-8")
sys.stderr = open(LOG_FILE, "a", encoding="utf-8")
print(f"\n=== 策略启动 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

# 单例锁：防止脚本多开冲突
LOCK_FILE = "v43_push.lock"
try:
    lock_fd = open(LOCK_FILE, "w", encoding="utf-8")
except:
    print("⚠️ 脚本已在运行，直接退出")
    sys.exit(0)

# 交易时段拦截：周末/非交易时间直接退出
now = datetime.datetime.now()
weekday = now.weekday()
if weekday >= 5:
    print("📌 周末非交易时段，退出")
    sys.exit(0)

hour, minute = now.hour, now.minute
if (hour < 9 or (hour == 9 and minute < 15)) or (hour > 15) \
        or (hour == 11 and minute > 30) or (hour == 12):
    print("📌 非交易时段，退出")
    sys.exit(0)

# 标记是否为盘中时段（区分推送样式）
IS_INTRADAY = (hour in [10, 11, 13, 14]) and not (hour == 11 and minute == 30)

# ====================== 东方财富API 数据源（超时优化为8秒） ======================
def get_all_stocks_eastmoney():
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f74271dc3",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f20,f2"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code != 200:
            return []
        diff_list = resp.json().get("data", {}).get("diff", [])
        stock_list = []
        for item in diff_list:
            code = item.get("f12", "")
            name = item.get("f14", "")
            cap = item.get("f20", 0)
            price = item.get("f2", 0.0)
            if not code:
                continue
            exchange = "SHSE" if code.startswith(("60", "68")) else "SZSE"
            stock_list.append({
                "symbol": f"{exchange}.{code}",
                "symbol_name": name,
                "circulating_market_cap": cap * 100000000,
                "price": float(price)
            })
        return stock_list
    except Exception as e:
        print(f"❌ 获取股票列表异常: {e}")
        return []

def get_history_eastmoney(symbol, days):
    code = symbol.replace("SHSE.", "").replace("SZSE.", "")
    secid = f"1.{code}" if code.startswith(("60", "68")) else f"0.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "bd1d9ddb04089700cf9c27f6f74271dc3",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101, "fqt": 1, "lmt": days
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code != 200:
            return []
        kline_list = resp.json().get("data", {}).get("klines", [])
        bars = []
        for kline in kline_list:
            parts = kline.split(",")
            bars.append({
                "close": float(parts[2]),
                "pre_close": float(parts[1]),
                "volume": float(parts[5])
            })
        return bars[-days:]
    except Exception as e:
        print(f"❌ 获取K线异常: {e}")
        return []

def get_index_eastmoney():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": 2, "invt": 2, "fields": "f1,f2,f3,f4,f14",
        "secids": "1.000001,0.399001,0.399006,1.000300,1.000016"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        diff_list = resp.json().get("data", {}).get("diff", [])
        code_map = [
            "SHSE.000001", "SZSE.399001", "SZSE.399006",
            "SHSE.000300", "SHSE.000016"
        ]
        index_data = {}
        for idx, item in enumerate(diff_list):
            index_data[code_map[idx]] = {
                "name": item.get("f14", ""),
                "price": float(item.get("f2", 0)),
                "pct": round(float(item.get("f3", 0)), 2)
            }
        return index_data
    except Exception as e:
        print(f"❌ 获取指数异常: {e}")
        return None

# 主板涨停统计
def get_limit_up():
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f74271dc3",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f3"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        diff_list = resp.json().get("data", {}).get("diff", [])
        count = 0
        for item in diff_list:
            change = float(item.get("f3", 0))
            if change >= 9.8:
                count += 1
        return count
    except:
        return 0

# 主板跌停统计
def get_limit_down():
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f74271dc3",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f3"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        diff_list = resp.json().get("data", {}).get("diff", [])
        count = 0
        for item in diff_list:
            change = float(item.get("f3", 0))
            if change <= -9.8:
                count += 1
        return count
    except:
        return 0

# ====================== V4.4.0 核心选股策略 ======================
def strategy_a():
    selected = []
    stock_list = get_all_stocks_eastmoney()
    if not stock_list:
        return []

    for stock in stock_list:
        symbol = stock["symbol"]
        name = stock["symbol_name"]
        cap = stock["circulating_market_cap"]
        price = stock["price"]

        # 过滤ST、市值、股价
        if "ST" in name or "*ST" in name:
            continue
        cap_yi = cap / 100000000
        if not (40 <= cap_yi <= 500):
            continue
        if not (3.5 <= price <= 30):
            continue

        # 获取K线
        bars_7d = get_history_eastmoney(symbol, 7)
        if len(bars_7d) < 7:
            continue

        # 7日最大涨幅
        max_rise_7d = max([(b["close"] - b["pre_close"]) / b["pre_close"] * 100 for b in bars_7d])
        if max_rise_7d < 7:
            continue

        # 3日涨幅
        rise_3d = (price - bars_7d[-3]["close"]) / bars_7d[-3]["close"] * 100
        if rise_3d < 3:
            continue

        # 5日均量 & 量比
        vol_5d = sum([b["volume"] for b in bars_7d[-5:]]) / 5
        now_vol = bars_7d[-1]["volume"]
        vol_ratio = now_vol / vol_5d
        if vol_ratio < 1.2:
            continue

        # 60日均线过滤
        bars_60d = get_history_eastmoney(symbol, 60)
        if len(bars_60d) < 60:
            continue
        ma60 = sum([b["close"] for b in bars_60d]) / 60
        if price < ma60 * 0.85:
            continue

        selected.append({
            "code": symbol.split(".")[-1],
            "name": name,
            "price": round(price, 2),
            "max_chg_7d": round(max_rise_7d, 1),
            "chg_3d": round(rise_3d, 1),
            "vol_ratio": round(vol_ratio, 2)
        })

    # 排序：3日涨幅 > 量比，取前5
    selected.sort(key=lambda x: (x["chg_3d"], x["vol_ratio"]), reverse=True)
    return selected[:5]

# ====================== 推送内容组装 ======================
def build_content(idx_data, up_num, down_num, stock_list):
    now_str = now.strftime("%H:%M")
    if IS_INTRADAY:
        # 盘中简化推送
        content = f"📊 盘中更新 {now_str}\n"
        content += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        content += f"上证指数：{idx_data['SHSE.000001']['price']:.2f} ({idx_data['SHSE.000001']['pct']:+.2f}%)\n"
        content += "【标的状态】\n"
        if stock_list:
            for s in stock_list[:3]:
                content += f"✅ {s['name']}({s['code']})：{s['price']}元 | 3日涨幅{s['chg_3d']}% | 量能{s['vol_ratio']}倍\n"
        else:
            content += "暂无新标的\n"
        content += "⚠️ 触及止盈止损请及时操作"
    else:
        # 完整推送（开盘/午盘/尾盘/盘后）
        avg_pct = sum([v["pct"] for v in idx_data.values()]) / len(idx_data)
        score = 0
        if avg_pct >= 1.0:
            score = 2
        elif avg_pct >= 0:
            score = 1
        else:
            score = 0
        score = min(score, 7)

        if score <= 1:
            tip = "🔴 弱势行情，仓位0-10% 轻仓观望"
        elif score <= 3:
            tip = "🟡 震荡行情，仓位10-30% 择机参与"
        else:
            tip = "🟢 强势行情，仓位30-50% 正常操作"

        content = f"📊 实时大盘 V4.4.0 {now_str}\n"
        content += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        content += f"🟢 上证指数：{idx_data['SHSE.000001']['price']:.2f} ({idx_data['SHSE.000001']['pct']:+.2f}%)\n"
        content += f"🟢 深证成指：{idx_data['SZSE.399001']['price']:.2f} ({idx_data['SZSE.399001']['pct']:+.2f}%)\n"
        content += f"🟢 创业板指：{idx_data['SZSE.399006']['price']:.2f} ({idx_data['SZSE.399006']['pct']:+.2f}%)\n"
        content += f"🟢 沪深300：{idx_data['SHSE.000300']['price']:.2f} ({idx_data['SHSE.000300']['pct']:+.2f}%)\n"
        content += f"🟢 上证50：{idx_data['SHSE.000016']['price']:.2f} ({idx_data['SHSE.000016']['pct']:+.2f}%)\n\n"
        content += f"主板涨停：{up_num}只 | 主板跌停：{down_num}只\n"
        content += f"大盘评分：{score}/7 分 | 操作建议：{tip}\n\n"
        content += "【符合策略推荐】\n"
        if not stock_list:
            content += "暂无符合条件的标的\n"
        else:
            for s in stock_list:
                content += f"✅ {s['name']}({s['code']})\n"
                content += f"  现价：{s['price']}元 | 3日涨幅：{s['chg_3d']}%\n"
                content += f"  7日最大涨幅：{s['max_chg_7d']}% | 量能倍数：{s['vol_ratio']}倍\n\n"
        content += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nV4.4.0 本地实时推送"
    return content

# ====================== 飞书推送 ======================
def send_feishu(msg):
    if not FEISHU_WEBHOOK:
        print("⚠️ 未配置飞书Webhook，跳过推送")
        return
    try:
        resp = requests.post(
            FEISHU_WEBHOOK,
            json={"msg_type": "text", "content": {"text": msg}},
            timeout=8
        )
        print(f"✅ 飞书推送成功，接口返回：{resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书推送失败：{e}")

# ====================== 主逻辑 ======================
def main():
    idx_data = get_index_eastmoney()
    if not idx_data:
        print("❌ 指数数据获取失败，退出")
        return

    up_count = get_limit_up()
    down_count = get_limit_down()
    stock_result = strategy_a()

    push_msg = build_content(idx_data, up_count, down_count, stock_result)
    send_feishu(push_msg)

if __name__ == "__main__":
    main()
    # 释放锁文件
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
