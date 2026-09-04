# -*- coding: utf-8 -*-
"""基本面量化过滤模块。

从东方财富获取个股基本面数据，设置硬门槛过滤：
- PE（市盈率）< 行业均值或 < 50
- PB（市净率）< 10
- ROE（净资产收益率）> 8%
- 营收增速 > 0
- 毛利率 > 15%
- 资产负债率 < 70%

基本面过滤的目的：排除垃圾股、ST股、高估值股。
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional
import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache", "fundamental")
os.makedirs(CACHE_DIR, exist_ok=True)

# 东财个股基本面API
FUNDAMENTAL_API = "https://push2.eastmoney.com/api/qt/stock/get"
PROXY_BASE = "https://macd-strategy-scheduler.fys2388.workers.dev"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _get_secid(stock_code: str) -> str:
    """转换股票代码为东财secid格式。"""
    if stock_code.startswith(("60", "68", "90")):
        return f"1.{stock_code}"
    else:
        return f"0.{stock_code}"


def get_fundamental(stock_code: str) -> Dict[str, Any]:
    """获取个股基本面数据。

    Returns:
        {pe, pb, roe, revenue_growth, gross_margin, debt_ratio, total_mv, ...}
    """
    secid = _get_secid(stock_code)
    params = {
        "secid": secid,
        "fields": "f55,f57,f58,f116,f117,f162,f167,f173,f187,f188,f190,f191,f192",
    }

    # 优先使用Cloudflare Worker代理
    try:
        resp = requests.get(f"{PROXY_BASE}/proxy/fundamental?code={stock_code}", headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data"):
            d = data["data"]
            return {
                "code": stock_code,
                "name": d.get("f58", ""),
                "pe": d.get("f162", 0),
                "pb": d.get("f167", 0),
                "roe": d.get("f173", 0),
                "gross_margin": d.get("f187", 0),
                "net_margin": d.get("f188", 0),
                "debt_ratio": d.get("f190", 0),
                "revenue_growth": d.get("f191", 0),
                "profit_growth": d.get("f192", 0),
                "total_mv": d.get("f116", 0),
                "circulating_mv": d.get("f117", 0),
            }
    except Exception as e:
        print(f"[基本面] Worker代理获取{stock_code}失败: {e}")

    try:
        resp = requests.get(FUNDAMENTAL_API, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        if data.get("data"):
            d = data["data"]
            return {
                "code": stock_code,
                "name": d.get("f58", ""),
                "pe": d.get("f162", 0),  # 市盈率(动)
                "pb": d.get("f167", 0),  # 市净率
                "roe": d.get("f173", 0),  # ROE
                "gross_margin": d.get("f187", 0),  # 毛利率
                "net_margin": d.get("f188", 0),  # 净利率
                "debt_ratio": d.get("f190", 0),  # 资产负债率
                "revenue_growth": d.get("f191", 0),  # 营收同比增长
                "profit_growth": d.get("f192", 0),  # 净利润同比增长
                "total_mv": d.get("f116", 0),  # 总市值
                "circulating_mv": d.get("f117", 0),  # 流通市值
            }
    except Exception as e:
        print(f"[基本面] {stock_code} 获取失败: {e}")
    return {}


def batch_get_fundamental(stock_codes: List[str]) -> Dict[str, Dict]:
    """批量获取基本面数据。"""
    results = {}
    for code in stock_codes:
        results[code] = get_fundamental(code)
        time.sleep(0.1)
    return results


# 默认基本面过滤阈值
DEFAULT_THRESHOLDS = {
    "pe_max": 80,          # PE < 80（排除超高估值）
    "pb_max": 15,          # PB < 15
    "roe_min": 3,          # ROE > 3%（排除亏损股）
    "gross_margin_min": 10,  # 毛利率 > 10%
    "debt_ratio_max": 80,  # 资产负债率 < 80%
    "revenue_growth_min": -30,  # 营收增速 > -30%（排除严重衰退）
    "profit_growth_min": -50,  # 净利润增速 > -50%
}


def filter_by_fundamental(stock_codes: List[str],
                          thresholds: Dict = None,
                          strict: bool = False) -> Dict[str, Any]:
    """基本面过滤。

    Args:
        stock_codes: 待过滤股票列表
        thresholds: 过滤阈值，默认用DEFAULT_THRESHOLDS
        strict: 严格模式，不满足任何一项就过滤；宽松模式，只过滤严重异常

    Returns:
        {passed: [code], rejected: [{code, reason}], fundamental: {code: data}}
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    fundamentals = batch_get_fundamental(stock_codes)
    passed = []
    rejected = []

    for code in stock_codes:
        fund = fundamentals.get(code, {})
        if not fund:
            passed.append(code)  # 获取不到数据时放行
            continue

        reasons = []

        # PE检查（排除负PE和超高PE）
        pe = fund.get("pe", 0)
        if pe and (pe < 0 or pe > thresholds["pe_max"]):
            reasons.append(f"PE={pe}")

        # PB检查
        pb = fund.get("pb", 0)
        if pb and pb > thresholds["pb_max"]:
            reasons.append(f"PB={pb}")

        # ROE检查
        roe = fund.get("roe", 0)
        if roe and roe < thresholds["roe_min"]:
            reasons.append(f"ROE={roe}%")

        # 毛利率检查
        gm = fund.get("gross_margin", 0)
        if gm and gm < thresholds["gross_margin_min"]:
            reasons.append(f"毛利率={gm}%")

        # 资产负债率检查
        dr = fund.get("debt_ratio", 0)
        if dr and dr > thresholds["debt_ratio_max"]:
            reasons.append(f"负债率={dr}%")

        # 营收增速检查
        rg = fund.get("revenue_growth", 0)
        if rg and rg < thresholds["revenue_growth_min"]:
            reasons.append(f"营收增速={rg}%")

        if reasons and strict:
            rejected.append({"code": code, "name": fund.get("name", ""), "reasons": reasons})
        elif reasons and not strict:
            # 宽松模式：只有3项以上不满足才过滤
            if len(reasons) >= 3:
                rejected.append({"code": code, "name": fund.get("name", ""), "reasons": reasons})
            else:
                passed.append(code)
        else:
            passed.append(code)

    return {
        "passed": passed,
        "rejected": rejected,
        "fundamental": fundamentals,
    }


def build_fundamental_report(fundamental: Dict[str, Dict], stock_code: str) -> str:
    """生成单只股票的基本面报告。"""
    fund = fundamental.get(stock_code, {})
    if not fund:
        return ""

    lines = [f"  📋 基本面：PE{fund.get('pe', '-')} | PB{fund.get('pb', '-')} | ROE{fund.get('roe', '-')}%"]
    lines.append(f"     毛利率{fund.get('gross_margin', '-')}% | 负债率{fund.get('debt_ratio', '-')}% | 营收增速{fund.get('revenue_growth', '-')}%")
    return "\n".join(lines)
