# -*- coding: utf-8 -*-
"""新浪财经公开行情数据源（第三备源）。

接口稳定、对海外IP友好，输出与 MarketData 兼容的格式。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Dict, Optional

import requests

_TIMEOUT = 10
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

_SINA_INDEX = {
    "000001": "sh000001",
    "399001": "sz399001",
}


def get_data_sina() -> Optional[dict]:
    """从新浪财经获取市场快照数据。返回 dict 或 None。"""
    try:
        indices = _fetch_sina_indices()
        if not indices:
            return None
        sh = indices.get("000001") or {}
        index_price = float(sh.get("price") or 0)
        index_change_pct = float(sh.get("change_pct") or 0)
        if index_price <= 0:
            return None
        sz = indices.get("399001") or {}
        sh_vol = float(sh.get("amount_yi", 0) or 0)
        sz_vol = float(sz.get("amount_yi", 0) or 0)
        volume_yi = sh_vol + sz_vol
        limit_up, limit_down = _count_limit_by_sina()
        return {
            "index_price": index_price,
            "index_change_pct": index_change_pct,
            "volume_yi": volume_yi,
            "limit_up_count": limit_up,
            "limit_down_count": limit_down,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "sina",
        }
    except Exception as e:
        print(f"[sina] 备源异常: {e}")
        return None


def _fetch_sina_indices() -> Dict[str, Dict]:
    codes = ",".join(_SINA_INDEX.values())
    url = f"https://hq.sinajs.cn/list={codes}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.encoding = "gbk"
        text = resp.text
        result: Dict[str, Dict] = {}
        for line in text.strip().split("\n"):
            if "=" not in line:
                continue
            code_part = line.split("=")[0].strip().replace("var hq_str_", "")
            match = re.search(r"sh(\d+)|sz(\d+)", code_part)
            if not match:
                continue
            stock_code = match.group(1) or match.group(2)
            inner = line.split('="')[1].strip().rstrip('";') if '="' in line else ""
            if not inner:
                continue
            parts = inner.split(",")
            if len(parts) < 10:
                continue
            try:
                price = float(parts[3])
                prev_close = float(parts[2])
                amount = float(parts[8])
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                result[stock_code] = {
                    "price": price,
                    "change_pct": change_pct,
                    "amount_yi": amount / 1e8,
                }
            except (ValueError, IndexError):
                continue
        return result
    except Exception as e:
        print(f"[sina] 指数拉取失败: {e}")
        return {}


def _count_limit_by_sina() -> tuple:
    up = down = 0
    try:
        for pn in range(1, 7):
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            params = {"page": pn, "num": 1000, "sort": "changepercent", "asc": 0, "node": "hs_a", "_s_r_a": "page"}
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            resp.encoding = "utf-8"
            try:
                data = resp.json()
            except Exception:
                continue
            if not data:
                break
            for item in data:
                try:
                    chg = float(item.get("changepercent", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if chg >= 9.9:
                    up += 1
                elif chg <= -9.9:
                    down += 1
            if len(data) < 1000:
                break
    except Exception as e:
        print(f"[sina] 涨跌停统计失败: {e}")
    return up, down


if __name__ == "__main__":
    md = get_data_sina()
    if md:
        print(f"sina OK: index={md['index_price']:.2f} chg={md['index_change_pct']:.2f}% "
              f"vol={md['volume_yi']:.0f}亿 limit_up={md['limit_up_count']} limit_down={md['limit_down_count']}")
    else:
        print("sina: 数据不可用")
