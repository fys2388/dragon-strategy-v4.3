# -*- coding: utf-8 -*-
"""板块强度排序模块。

从东方财富获取行业板块数据，计算板块强度，
选出强势板块，在强势板块内选股。

板块强度指标：
1. 板块涨幅（今日/5日/20日）
2. 板块内涨停家数
3. 板块成交量变化
4. 板块资金净流入
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional
import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache", "sector")
os.makedirs(CACHE_DIR, exist_ok=True)

# 东财行业板块API
SECTOR_API = "https://push2.eastmoney.com/api/qt/clist/get"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def get_sector_list() -> pd.DataFrame:
    """获取行业板块列表及实时行情。

    Returns:
        DataFrame，包含：板块名称、板块代码、涨跌幅、成交量、领涨股等
    """
    params = {
        "pn": 1,
        "pz": 100,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:90+t:2",  # 行业板块
        "fields": "f12,f14,f2,f3,f4,f5,f6,f7,f8,f15,f16,f17,f18,f20,f21,f62,f128,f136,f140",
    }

    try:
        resp = requests.get(SECTOR_API, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data") and data["data"].get("diff"):
            rows = []
            for item in data["data"]["diff"]:
                rows.append({
                    "sector_code": item.get("f12", ""),
                    "sector_name": item.get("f14", ""),
                    "price": item.get("f2", 0),
                    "change_pct": item.get("f3", 0),
                    "change_amount": item.get("f4", 0),
                    "volume": item.get("f5", 0),
                    "amount": item.get("f6", 0),
                    "amplitude": item.get("f7", 0),
                    "turnover_rate": item.get("f8", 0),
                    "high": item.get("f15", 0),
                    "low": item.get("f16", 0),
                    "open": item.get("f17", 0),
                    "prev_close": item.get("f18", 0),
                    "main_net_inflow": item.get("f62", 0),  # 主力净流入
                    "leading_stock": item.get("f128", ""),  # 领涨股
                    "leading_stock_pct": item.get("f136", 0),  # 领涨股涨幅
                    "up_count": item.get("f140", 0),  # 上涨家数
                })
            df = pd.DataFrame(rows)
            return df
    except Exception as e:
        print(f"[板块强度] 获取板块列表失败: {e}")
    return pd.DataFrame()


def get_sector_stocks(sector_code: str) -> List[str]:
    """获取板块内的股票代码列表。

    Args:
        sector_code: 板块代码（东财格式，如BK0428）

    Returns:
        股票代码列表
    """
    params = {
        "pn": 1,
        "pz": 200,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": f"b:{sector_code}",
        "fields": "f12,f14,f2,f3",
    }

    try:
        resp = requests.get(SECTOR_API, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data") and data["data"].get("diff"):
            codes = [item["f12"] for item in data["data"]["diff"]]
            return codes
    except Exception as e:
        print(f"[板块强度] 获取板块成分股失败: {e}")
    return []


def calc_sector_strength(sector_df: pd.DataFrame) -> pd.DataFrame:
    """计算板块强度评分并排序。

    强度评分 = 涨幅(40%) + 主力净流入(30%) + 上涨家数占比(20%) + 领涨股涨幅(10%)

    Returns:
        按强度降序排列的DataFrame，新增strength_score列
    """
    if sector_df.empty:
        return sector_df

    df = sector_df.copy()

    # 标准化各指标到0-100
    def normalize(series):
        if series.max() == series.min():
            return pd.Series([50] * len(series), index=series.index)
        return (series - series.min()) / (series.max() - series.min()) * 100

    df["score_change"] = normalize(df["change_pct"].fillna(0))
    df["score_inflow"] = normalize(df["main_net_inflow"].fillna(0))
    df["score_upcount"] = normalize(df["up_count"].fillna(0))
    df["score_leading"] = normalize(df["leading_stock_pct"].fillna(0))

    df["strength_score"] = (
        df["score_change"] * 0.4 +
        df["score_inflow"] * 0.3 +
        df["score_upcount"] * 0.2 +
        df["score_leading"] * 0.1
    ).round(1)

    df = df.sort_values("strength_score", ascending=False)
    return df


def get_strong_sectors(top_n: int = 5) -> List[Dict[str, Any]]:
    """获取强势板块Top N。

    Returns:
        强势板块列表，每项含名称、涨幅、强度评分、领涨股
    """
    sector_df = get_sector_list()
    if sector_df.empty:
        return []

    scored = calc_sector_strength(sector_df)
    top = scored.head(top_n)

    result = []
    for _, row in top.iterrows():
        result.append({
            "sector_name": row["sector_name"],
            "sector_code": row["sector_code"],
            "change_pct": round(row["change_pct"], 2),
            "strength_score": row["strength_score"],
            "main_net_inflow_yi": round(row["main_net_inflow"] / 10000, 2) if row["main_net_inflow"] else 0,
            "leading_stock": row["leading_stock"],
            "leading_stock_pct": round(row["leading_stock_pct"], 2),
            "up_count": int(row["up_count"]) if row["up_count"] else 0,
        })
    return result


def filter_stocks_by_strong_sector(stock_codes: List[str],
                                     strong_sectors: List[Dict],
                                     stock_sector_map: Dict[str, str] = None) -> List[str]:
    """过滤出属于强势板块的股票。

    Args:
        stock_codes: 待过滤股票代码列表
        strong_sectors: 强势板块列表
        stock_sector_map: 股票→板块映射（可选，没有则不过滤）

    Returns:
        属于强势板块的股票代码列表
    """
    if not stock_sector_map:
        return stock_codes  # 没有映射时不过滤

    strong_sector_names = {s["sector_name"] for s in strong_sectors}
    filtered = [code for code in stock_codes
                if stock_sector_map.get(code, "") in strong_sector_names]
    return filtered if filtered else stock_codes  # 过滤后为空则返回全部


def build_sector_report(strong_sectors: List[Dict]) -> str:
    """生成板块强度报告。"""
    if not strong_sectors:
        return "📊 板块强度：数据获取失败"

    lines = ["📊 今日强势板块Top5："]
    for i, s in enumerate(strong_sectors, 1):
        emoji = "🔴" if s["change_pct"] > 0 else "🟢"
        lines.append(
            f"  {i}. {s['sector_name']} {emoji}{s['change_pct']}% "
            f"| 强度{s['strength_score']} | 主力净流入{s['main_net_inflow_yi']}亿 "
            f"| 领涨:{s['leading_stock']}({s['leading_stock_pct']}%)"
        )
    return "\n".join(lines)
