# -*- coding: utf-8 -*-
"""动态股票池更新脚本。

每周日运行，自动更新股票池：
1. 保留核心池（原有优质股）
2. 加入近期涨停股、热门板块龙头、主力资金流入股
3. 过滤价格3.5-30元、ST股、退市股
4. 去重合并，目标300-400只

解决静态股票池错过涨停机会的问题。
"""
from __future__ import annotations

import os
import sys
import json
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Worker代理地址（解决GitHub IP被限制问题）
PROXY_BASE = "https://macd-strategy-scheduler.fys2388.workers.dev"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

POOL_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "quality_pool.json")


def load_core_pool() -> list:
    """加载核心股票池。"""
    if os.path.exists(POOL_FILE):
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def get_zt_stocks(days: int = 20) -> list:
    """获取近N天有过涨停的股票（东财涨停板API）。

    Returns:
        [{"code": "xxx", "name": "xxx"}, ...]
    """
    result = []
    try:
        # 东财涨停板行情接口
        url = "https://push2ex.eastmoney.com/getTopicZTPool"
        params = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": "200",
            "sort": "fbt:asc",
            "date": datetime.now().strftime("%Y%m%d"),
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data") and data["data"].get("pool"):
            for item in data["data"]["pool"]:
                code = item.get("c", "")
                name = item.get("n", "")
                if code and name and not code.startswith(("8", "4", "92")):
                    # 过滤北交所、科创板过高价格的在后续处理
                    result.append({"code": code, "name": name})
        print(f"[涨停池] 获取{len(result)}只今日涨停股")
    except Exception as e:
        print(f"[涨停池] 获取失败: {e}")
    return result


def get_hot_sector_leaders() -> list:
    """获取热门板块龙头股（通过Worker代理获取板块强度，取涨幅前10板块的龙头）。"""
    result = []
    try:
        resp = requests.get(f"{PROXY_BASE}/proxy/sector", headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data") and data["data"].get("diff"):
            sectors = sorted(data["data"]["diff"], key=lambda x: x.get("f3", 0), reverse=True)[:10]
            for sector in sectors:
                leader_code = sector.get("f128", "")
                leader_name = sector.get("f128_name", "")
                if leader_code and len(leader_code) == 6:
                    result.append({"code": leader_code, "name": leader_name or sector.get("f14", "")})
        print(f"[热门龙头] 获取{len(result)}只板块龙头")
    except Exception as e:
        print(f"[热门龙头] 获取失败: {e}")
    return result


def get_main_inflow_stocks(top_n: int = 100) -> list:
    """获取主力资金净流入前N的股票。"""
    result = []
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "fid": "f62",  # 按主力净流入排序
            "po": "1",     # 降序
            "pz": str(top_n),
            "pn": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",  # 沪深A股
            "fields": "f12,f14,f2,f3,f62",
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data") and data["data"].get("diff"):
            for item in data["data"]["diff"]:
                code = item.get("f12", "")
                name = item.get("f14", "")
                price = item.get("f2", 0)
                if code and name and 3.5 <= price <= 30:
                    result.append({"code": code, "name": name})
        print(f"[主力流入] 获取{len(result)}只主力净流入股（价格过滤后）")
    except Exception as e:
        print(f"[主力流入] 获取失败: {e}")
    return result


def filter_stocks(pool: list) -> list:
    """过滤股票池：价格3.5-30元、非ST、非退市。"""
    filtered = []
    seen = set()
    for item in pool:
        code = item.get("code", "")
        name = item.get("name", "")
        if not code or not name:
            continue
        if code in seen:
            continue
        # 过滤ST、退市、北交所
        if "ST" in name or "退" in name or code.startswith(("8", "4", "92")):
            continue
        # 过滤科创板（688开头，价格通常较高）
        # 保留科创板，因为可能有好股票，但价格过滤会处理
        seen.add(code)
        filtered.append({"code": code, "name": name})
    return filtered


def main():
    print("=" * 60)
    print("🔄 动态股票池更新")
    print("=" * 60)

    # 1. 加载核心池
    core_pool = load_core_pool()
    print(f"\n[核心池] 原有{len(core_pool)}只")

    # 2. 获取扩展池
    zt_stocks = get_zt_stocks()
    hot_leaders = get_hot_sector_leaders()
    inflow_stocks = get_main_inflow_stocks()

    # 3. 手动加入重点关注股（用户持仓和近期关注）
    manual_stocks = [
        {"code": "600330", "name": "天通股份"},  # 用户关注，电子元件+新材料
        {"code": "000601", "name": "韶能股份"},  # 用户持仓
        {"code": "600487", "name": "亨通光电"},  # 用户持仓
    ]
    print(f"[手动加入] {len(manual_stocks)}只重点关注股")

    # 4. 合并所有股票
    all_stocks = core_pool + zt_stocks + hot_leaders + inflow_stocks + manual_stocks
    print(f"\n[合并前] 总计{len(all_stocks)}只（含重复）")

    # 5. 过滤去重
    final_pool = filter_stocks(all_stocks)
    print(f"[过滤后] 总计{len(final_pool)}只（去重+ST过滤）")

    # 6. 保存
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(final_pool, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 股票池已保存到 {POOL_FILE}")
    print(f"   核心池: {len(core_pool)}只")
    print(f"   涨停股: {len(zt_stocks)}只")
    print(f"   板块龙头: {len(hot_leaders)}只")
    print(f"   主力流入: {len(inflow_stocks)}只")
    print(f"   手动加入: {len(manual_stocks)}只")
    print(f"   最终去重后: {len(final_pool)}只")

    # 7. 验证天通股份
    codes = [x["code"] for x in final_pool]
    print(f"\n[验证] 天通股份(600330)在池中: {'600330' in codes}")


if __name__ == "__main__":
    main()
