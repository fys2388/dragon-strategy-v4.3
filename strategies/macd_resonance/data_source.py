# -*- coding: utf-8 -*-
"""东方财富数据源模块（统一封装）。

- 统一市值/金额单位换算（修复 f20/f169 单位 Bug）
- 全部使用 https
- 多周期 K 线获取：日线 / 60min / 30min / 15min
- 超时(5s) + 重试(2次) + 异常兜底，失败返回空 DataFrame 不崩溃
"""
from __future__ import annotations

import time
import requests
import pandas as pd
from typing import Dict, List, Optional

from .config import DATA_SOURCE, KLT_MAP

_BASE = DATA_SOURCE["base_url"]
_KLINE = DATA_SOURCE["kline_url"]
_TIMEOUT = DATA_SOURCE["timeout"]
_RETRY = DATA_SOURCE["retry"]
_UT = DATA_SOURCE["ut"]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.eastmoney.com/",
}


def _request_get(url: str, params: Dict) -> Optional[dict]:
    """带重试的 GET 请求，失败返回 None。"""
    for attempt in range(_RETRY + 1):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        time.sleep(0.3 * (attempt + 1))
    return None


def code_to_secid(code: str) -> str:
    """股票代码 → 东财 secid。"""
    if code.startswith(("6", "5", "9")):
        return f"1.{code}"
    return f"0.{code}"


# ============================================================
# 统一单位换算
# ============================================================
def get_float_market_cap_yi(item: Dict) -> float:
    """流通市值（元）→ 亿元。东财 f20 字段单位为元。"""
    try:
        raw = item.get("f20")
        if raw is None or raw == "-" or raw == "":
            return 0.0
        return float(raw) / 100000000.0
    except (TypeError, ValueError):
        return 0.0


def get_total_market_cap_yi(item: Dict) -> float:
    """总市值（元）→ 亿元。"""
    try:
        raw = item.get("f21")
        if raw is None or raw == "-" or raw == "":
            return 0.0
        return float(raw) / 100000000.0
    except (TypeError, ValueError):
        return 0.0


def get_amount_yi(item: Dict) -> float:
    """成交额（元）→ 亿元。东财 f6 单位为元。"""
    try:
        raw = item.get("f6")
        if raw is None or raw == "-" or raw == "":
            return 0.0
        return float(raw) / 100000000.0
    except (TypeError, ValueError):
        return 0.0


# ============================================================
# K 线获取（多周期）
# ============================================================
def get_kline(code: str, period: str = "daily", count: int = 200) -> pd.DataFrame:
    """获取 K 线数据。

    Args:
        code: 6 位股票代码
        period: daily / 60m / 30m / 15m
        count: 根数

    Returns:
        DataFrame[datetime, open, high, low, close, volume(手), amount(元)]
        失败返回空 DataFrame。
    """
    if period not in KLT_MAP:
        return pd.DataFrame()
    klt = KLT_MAP[period]
    params = {
        "secid": code_to_secid(code),
        "ut": _UT,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": klt,
        "fqt": 1,
        "end": "20500101",
        "lmt": count,
    }
    data = _request_get(f"{_KLINE}/api/qt/stock/kline/get", params)
    if not data or not data.get("data") or not data["data"].get("klines"):
        return pd.DataFrame()

    rows = []
    for line in data["data"]["klines"]:
        p = line.split(",")
        if len(p) < 7:
            continue
        try:
            rows.append({
                "datetime": p[0],
                "open": float(p[1]),
                "close": float(p[2]),
                "high": float(p[3]),
                "low": float(p[4]),
                "volume": float(p[5]),   # 手
                "amount": float(p[6]),   # 元
            })
        except (ValueError, IndexError):
            continue

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def get_kline_daily(code: str, count: int = 120) -> pd.DataFrame:
    """日线 K 线。"""
    return get_kline(code, "daily", count)


def get_kline_minute(code: str, period: str = "60m", count: int = 200) -> pd.DataFrame:
    """分钟 K 线，period 支持 15m/30m/60m。"""
    return get_kline(code, period, count)


# ============================================================
# 行情与指数
# ============================================================
def get_realtime_quotes(codes: List[str]) -> Dict[str, Dict]:
    """批量实时行情（含流通市值）。"""
    if not codes:
        return {}
    secids = ",".join(code_to_secid(c) for c in codes)
    params = {
        "fltt": 2, "invt": 2, "ut": _UT,
        "fields": "f2,f3,f6,f12,f14,f20,f21",
        "secids": secids,
    }
    data = _request_get(f"{_BASE}/api/qt/ulist.np/get", params)
    result = {}
    if data and data.get("data") and data["data"].get("diff"):
        diff = data["data"]["diff"]
        if isinstance(diff, dict):
            diff = list(diff.values())
        for item in diff:
            code = str(item.get("f12", ""))
            result[code] = {
                "code": code,
                "name": item.get("f14", ""),
                "price": float(item.get("f2", 0) or 0),
                "change_pct": float(item.get("f3", 0) or 0),
                "amount_yi": get_amount_yi(item),
                "float_cap_yi": get_float_market_cap_yi(item),
                "total_cap_yi": get_total_market_cap_yi(item),
            }
    return result


def get_market_indices() -> Dict[str, Dict]:
    """五大指数实时数据。"""
    params = {
        "fltt": 2, "invt": 2, "ut": _UT,
        "fields": "f2,f3,f4,f6,f12,f14",
        "secids": "1.000001,0.399001,0.399006,1.000300,1.000016",
    }
    data = _request_get(f"{_BASE}/api/qt/ulist.np/get", params)
    indices = {}
    if data and data.get("data") and data["data"].get("diff"):
        diff = data["data"]["diff"]
        if isinstance(diff, dict):
            diff = list(diff.values())
        for item in diff:
            indices[str(item.get("f12", ""))] = {
                "code": str(item.get("f12", "")),
                "name": item.get("f14", ""),
                "price": float(item.get("f2", 0) or 0),
                "change_pct": float(item.get("f3", 0) or 0),
                "amount_yi": get_amount_yi(item),
            }
    return indices


def get_mainboard_stocks(limit: int = 6000) -> List[Dict]:
    """沪深主板股票列表（60/00 开头）。

    返回字段：code / name / price / float_cap_yi / amount_yi
    """
    stocks: List[Dict] = []
    pn = 1
    while pn <= 3 and len(stocks) < limit:
        params = {
            "pn": pn, "pz": 5000, "po": 1, "np": 1, "ut": _UT,
            "fltt": 2, "invt": 2, "fid": "f6",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f2,f6,f12,f14,f20",
        }
        data = _request_get(f"{_BASE}/api/qt/clist/get", params)
        if not data or not data.get("data") or not data["data"].get("diff"):
            break
        diff = data["data"]["diff"]
        if isinstance(diff, dict):
            diff = list(diff.values())
        for item in diff:
            code = str(item.get("f12", ""))
            if not (code.startswith("60") or code.startswith("00")):
                continue
            stocks.append({
                "code": code,
                "name": str(item.get("f14", "")),
                "price": float(item.get("f2", 0) or 0),
                "float_cap_yi": get_float_market_cap_yi(item),
                "amount_yi": get_amount_yi(item),
            })
        pn += 1
        time.sleep(0.2)
    return stocks[:limit]


def count_limit_up_down() -> tuple[int, int]:
    """主板涨停/跌停家数（涨幅≥9.8 视为涨停）。"""
    params = {
        "pn": 1, "pz": 6000, "po": 1, "np": 1, "ut": _UT,
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f3",
    }
    data = _request_get(f"{_BASE}/api/qt/clist/get", params)
    up = down = 0
    if data and data.get("data") and data["data"].get("diff"):
        diff = data["data"]["diff"]
        if isinstance(diff, dict):
            diff = list(diff.values())
        for item in diff:
            try:
                chg = float(item.get("f3", 0) or 0)
            except (TypeError, ValueError):
                continue
            if chg >= 9.8:
                up += 1
            elif chg <= -9.8:
                down += 1
    return up, down


def get_market_total_amount_yi() -> float:
    """两市总成交额（亿）≈ 上证 + 深证指数成交额。"""
    idx = get_market_indices()
    total = 0.0
    for key in ("000001", "399001"):
        total += idx.get(key, {}).get("amount_yi", 0.0)
    return total
