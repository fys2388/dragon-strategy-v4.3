# -*- coding: utf-8 -*-
"""资金流数据模块。

从东方财富获取个股资金流数据：
- 主力净流入（超大单+大单）
- 中单净流入
- 小单净流入
- 资金流趋势（连续N天净流入）

资金流是重要的alpha因子：主力持续净流入往往预示上涨。
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Any
import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache", "moneyflow")
os.makedirs(CACHE_DIR, exist_ok=True)

# 东财资金流API
MONEYFLOW_API = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _get_secid(stock_code: str) -> str:
    """转换股票代码为东财secid格式。

    沪市：1.xxxxxx
    深市：0.xxxxxx
    """
    if stock_code.startswith(("60", "68", "90")):
        return f"1.{stock_code}"
    else:
        return f"0.{stock_code}"


def get_moneyflow_daily(stock_code: str, days: int = 20) -> pd.DataFrame:
    """获取个股日级资金流数据。

    Args:
        stock_code: 股票代码
        days: 获取天数

    Returns:
        DataFrame，包含：date, main_net_inflow（主力净流入万元）,
        medium_net_inflow（中单净流入）, small_net_inflow（小单净流入）,
        main_net_inflow_pct（主力净流入占成交额比例）
    """
    secid = _get_secid(stock_code)
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "101",  # 日线
        "lmt": str(days),
    }

    try:
        resp = requests.get(MONEYFLOW_API, params=params, headers=HEADERS, timeout=8)
        data = resp.json()

        if not data.get("data") or not data["data"].get("klines"):
            return pd.DataFrame()

        klines = data["data"]["klines"]
        records = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 7:
                records.append({
                    "date": parts[0],
                    "main_net_inflow": float(parts[1]) / 10000,  # 元转万元
                    "small_net_inflow": float(parts[2]) / 10000,
                    "medium_net_inflow": float(parts[3]) / 10000,
                    "large_net_inflow": float(parts[4]) / 10000,
                    "super_large_net_inflow": float(parts[5]) / 10000,
                    "main_net_inflow_pct": float(parts[6]),  # 主力净流入占比%
                })

        df = pd.DataFrame(records)
        return df

    except Exception as e:
        print(f"[资金流] {stock_code} 获取失败: {e}")
        return pd.DataFrame()


def get_moneyflow_realtime(stock_code: str) -> Dict[str, Any]:
    """获取个股实时资金流（当日）。

    Returns:
        {main_net_inflow, main_net_inflow_pct, ...}
    """
    df = get_moneyflow_daily(stock_code, days=1)
    if df.empty:
        return {}
    latest = df.iloc[-1].to_dict()
    return latest


def check_moneyflow_trend(stock_code: str, days: int = 5) -> Dict[str, Any]:
    """检查资金流趋势。

    Args:
        stock_code: 股票代码
        days: 连续天数

    Returns:
        {
            consecutive_inflow_days: 连续主力净流入天数,
            total_inflow: days内主力净流入总额（万元）,
            avg_inflow: 日均主力净流入（万元）,
            inflow_ratio: 净流入天数占比,
            trend: "strong_inflow" / "weak_inflow" / "outflow" / "neutral"
        }
    """
    df = get_moneyflow_daily(stock_code, days=days + 5)
    if df.empty or len(df) < days:
        return {"trend": "no_data", "consecutive_inflow_days": 0}

    # 取最近days天
    recent = df.tail(days)
    inflow_days = (recent["main_net_inflow"] > 0).sum()
    total_inflow = recent["main_net_inflow"].sum()
    avg_inflow = recent["main_net_inflow"].mean()

    # 计算连续净流入天数（从最后一天往前数）
    consecutive = 0
    for i in range(len(df) - 1, -1, -1):
        if df.iloc[i]["main_net_inflow"] > 0:
            consecutive += 1
        else:
            break

    # 判断趋势
    if consecutive >= 3 and total_inflow > 0:
        trend = "strong_inflow"
    elif inflow_days >= days * 0.6 and total_inflow > 0:
        trend = "weak_inflow"
    elif inflow_days <= days * 0.3 and total_inflow < 0:
        trend = "outflow"
    else:
        trend = "neutral"

    return {
        "consecutive_inflow_days": consecutive,
        "total_inflow": round(total_inflow, 2),
        "avg_inflow": round(avg_inflow, 2),
        "inflow_ratio": round(inflow_days / days * 100, 1),
        "trend": trend,
        "latest_main_inflow": round(df.iloc[-1]["main_net_inflow"], 2),
        "latest_main_inflow_pct": round(df.iloc[-1]["main_net_inflow_pct"], 2),
    }


def batch_get_moneyflow(stock_codes: List[str], days: int = 5) -> Dict[str, Dict]:
    """批量获取多只股票的资金流趋势。

    Args:
        stock_codes: 股票代码列表
        days: 检查天数

    Returns:
        {code: moneyflow_info}
    """
    results = {}
    for code in stock_codes:
        try:
            info = check_moneyflow_trend(code, days)
            results[code] = info
        except Exception as e:
            results[code] = {"trend": "error", "error": str(e)}
        time.sleep(0.1)  # 限速
    return results


def build_moneyflow_message(moneyflow_info: Dict, stock_name: str = "") -> str:
    """生成资金流分析消息。"""
    trend_labels = {
        "strong_inflow": "🟢 主力强势流入",
        "weak_inflow": "🟡 主力温和流入",
        "outflow": "🔴 主力流出",
        "neutral": "⚪ 资金中性",
        "no_data": "⚪ 无数据",
    }

    lines = [
        f"💰 资金流分析：{stock_name}",
        f"  趋势：{trend_labels.get(moneyflow_info.get('trend'), '未知')}",
        f"  连续净流入：{moneyflow_info.get('consecutive_inflow_days', 0)}天",
        f"  5日总额：{moneyflow_info.get('total_inflow', 0)}万元",
        f"  日均流入：{moneyflow_info.get('avg_inflow', 0)}万元",
        f"  今日主力净流入：{moneyflow_info.get('latest_main_inflow', 0)}万元（{moneyflow_info.get('latest_main_inflow_pct', 0)}%）",
    ]
    return "\n".join(lines)
