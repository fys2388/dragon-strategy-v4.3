# -*- coding: utf-8 -*-
"""当日数据缓存机制。

- 大盘数据：market_YYYYMMDD.json
- 选股池：stock_pool_YYYYMMDD.json
- 缓存有效期：当日交易时段内有效，次日自动失效

用法：
    from .cache import get_cached, set_cached, is_cache_expired
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from .trading_calendar import now_bjt, BJT

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "cache",
)
os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_key(prefix: str) -> str:
    """生成当日缓存文件名。"""
    date_str = now_bjt().strftime("%Y%m%d")
    return os.path.join(_CACHE_DIR, f"{prefix}_{date_str}.json")


def _is_today(filepath: str) -> bool:
    """检查缓存文件是否为当日（失效则为 False）。"""
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        cache_date = data.get("cache_date", "")
        return cache_date == now_bjt().strftime("%Y-%m-%d")
    except Exception:
        return False


def get_cached(prefix: str) -> Optional[Any]:
    """读取当日缓存，过期则返回 None。"""
    filepath = _cache_key(prefix)
    if not _is_today(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("data")
    except Exception:
        return None


def set_cached(prefix: str, data: Any) -> None:
    """写入当日缓存。"""
    filepath = _cache_key(prefix)
    payload = {
        "cache_date": now_bjt().strftime("%Y-%m-%d"),
        "ts": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
        "data": data,
    }
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[cache] 写入失败 {prefix}: {e}")


def is_cache_expired(prefix: str) -> bool:
    """缓存是否已失效（不存在或不是当日）。"""
    return not _is_today(_cache_key(prefix))


def clear_all() -> None:
    """清除所有缓存（用于调试）。"""
    for f in os.listdir(_CACHE_DIR):
        if f.endswith(".json"):
            os.remove(os.path.join(_CACHE_DIR, f))
    print("[cache] 全部缓存已清除")


if __name__ == "__main__":
    set_cached("test", {"hello": "world"})
    print("缓存写入:", get_cached("test"))
    print("缓存日期:", datetime.now(BJT).strftime("%Y-%m-%d"))
