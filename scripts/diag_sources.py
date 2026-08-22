# -*- coding: utf-8 -*-
"""数据源连通性诊断（用于排查 GitHub Actions 运行器上各行情源可达性）。"""
from __future__ import annotations

import json
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def probe(name: str, method: str, url: str, headers=None, params=None, timeout: int = 8) -> str:
    t0 = time.time()
    try:
        r = requests.request(method, url, headers=headers or UA, params=params, timeout=timeout)
        el = time.time() - t0
        if r.status_code == 200:
            body = r.text[:80].replace("\n", " ")
            return f"OK {el:.1f}s [{r.status_code}] {body}"
        return f"HTTP {r.status_code} {el:.1f}s"
    except Exception as e:  # noqa: BLE001
        return f"FAIL {type(e).__name__} {el:.1f}s {str(e)[:80]}"


def main():
    results = {}

    # 东财
    results["eastmoney_index"] = probe(
        "eastmoney_index", "get",
        "https://push2.eastmoney.com/api/qt/ulist.np/get",
        params={"fltt": 2, "invt": 2, "fields": "f2,f3,f12", "secids": "1.000001"})

    # 新浪
    results["sina_index"] = probe(
        "sina_index", "get", "https://hq.sinajs.cn/list=sh000001",
        headers={**UA, "Referer": "https://finance.sina.com.cn/"})
    results["sina_kline"] = probe(
        "sina_kline", "get",
        "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData",
        params={"symbol": "sh600000", "scale": 240, "ma": "no", "datalen": 30},
        headers={**UA, "Referer": "https://finance.sina.com.cn/"})
    results["sina_pool"] = probe(
        "sina_pool", "get",
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
        params={"page": 1, "num": 5, "sort": "amount", "asc": 0, "node": "hs_a"},
        headers={**UA, "Referer": "https://finance.sina.com.cn/"})

    # 腾讯
    results["tencent_kline"] = probe(
        "tencent_kline", "get",
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": "sh600000,day,,,30,qfq"})

    # Yahoo Finance（A股指数/个股，美国可直连）
    results["yahoo_index"] = probe(
        "yahoo_index", "get",
        "https://query1.finance.yahoo.com/v8/finance/chart/%5ESSEC",
        params={"range": "1d", "interval": "1d"})

    print("\n===== 数据源连通性诊断 =====")
    for k, v in results.items():
        print(f"{k:18s} : {v}")
    print("==========================")


if __name__ == "__main__":
    main()
