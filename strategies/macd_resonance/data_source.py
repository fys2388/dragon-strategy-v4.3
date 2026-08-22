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
# 东财延迟行情镜像：海外IP/代理环境下 push2/push2his 常被阻断，delay 域名相对可达
_BASE_DELAY = "https://push2delay.eastmoney.com"
_KLINE_DELAY = "https://push2delay.eastmoney.com"
_TIMEOUT = DATA_SOURCE["timeout"]
_RETRY = DATA_SOURCE["retry"]
_UT = DATA_SOURCE["ut"]

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.76",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]
_HEADERS = {
    "User-Agent": "",
    "Referer": "https://finance.eastmoney.com/",
}


_BACKOFF = (1.0, 2.0, 4.0)  # 指数退避（秒）：失败后 1s → 2s → 4s，最多 3 次


def _pick_headers() -> Dict:
    """随机轮换 User-Agent，降低被识别为爬虫的概率。"""
    import random
    _HEADERS["User-Agent"] = random.choice(_USER_AGENTS)
    return _HEADERS


def _request_get_once(url: str, params: Dict, timeout: Optional[float] = None,
                       verbose: bool = False) -> Optional[dict]:
    """单域名带重试的 GET 请求（指数退避 1/2/4s），失败返回 None。"""
    timeout = timeout if timeout is not None else _TIMEOUT
    for attempt in range(_RETRY + 1):
        try:
            resp = requests.get(url, params=params, headers=_pick_headers(), timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if verbose and data:
                    diff = (data.get("data") or {}).get("diff") or []
                    print(f"[data_source] GET {url.split('/')[-1]}?pn={params.get('pn')} "
                          f"status=200 total={(data.get('data') or {}).get('total')} "
                          f"diff_len={len(diff) if hasattr(diff, '__len__') else 'n/a'}")
                return data
            if verbose:
                print(f"[data_source] GET {url.split('/')[-1]} status={resp.status_code} "
                      f"body={resp.text[:200]!r}")
        except Exception as e:
            if verbose:
                print(f"[data_source] GET {url.split('/')[-1]} attempt{attempt + 1} 异常: {type(e).__name__} {str(e)[:120]}")
        if attempt < _RETRY:
            time.sleep(_BACKOFF[attempt])
    return None


def _request_get(url: str, params: Dict, timeout: Optional[float] = None,
                 verbose: bool = False) -> Optional[dict]:
    """带重试的 GET 请求，主域名失败时自动降级到东财延迟行情域名。

    verbose=True 时打印状态码与响应片段，用于排查数据源问题。
    """
    candidates = [url]
    if _BASE in url:
        candidates.append(url.replace(_BASE, _BASE_DELAY))
    elif _KLINE in url:
        candidates.append(url.replace(_KLINE, _KLINE_DELAY))
    for cand in candidates:
        data = _request_get_once(cand, params, timeout, verbose)
        if data:
            return data
        if verbose:
            print(f"[data_source] 域名降级: {cand.split('/')[2]} 失败，尝试下一域名")
    return None


def code_to_secid(code: str, is_index: bool = False) -> str:
    """股票/指数代码 → 东财 secid。

    Args:
        code: 6 位代码
        is_index: 是否为指数。默认 False（个股）。
            注意：000001 既指上证指数(1.000001)也指平安银行(0.000001)。
            个股实时行情/持仓查询必须用默认 is_index=False，
            仅指数K线等明确场景传 is_index=True，避免 000001 被误映射为沪指。
    """
    # 指数 secid 映射：沪市指数为 1.xxxxxx，深市指数为 0.xxxxxx
    INDEX_SECIDS = {
        "000001": "1.000001",  # 上证指数
        "000300": "1.000300",  # 沪深300
        "000016": "1.000016",  # 上证50
        "000905": "1.000905",  # 中证500
        "399001": "0.399001",  # 深证成指
        "399006": "0.399006",  # 创业板指
    }
    if is_index and code in INDEX_SECIDS:
        return INDEX_SECIDS[code]
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
def _market_symbol(code: str) -> str:
    """东财代码 → 新浪/腾讯市场前缀（sh/sz）。"""
    if code in ("000001", "000300", "000016", "000905"):
        return f"sh{code}"
    if code in ("399001", "399006"):
        return f"sz{code}"
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _get_kline_sina(code: str, period: str = "daily", count: int = 200) -> pd.DataFrame:
    """备用K线源1：新浪财经（日线/60m/30m/15m）。"""
    scale = {"daily": 240, "60m": 60, "30m": 30, "15m": 15}.get(period)
    if scale is None:
        return pd.DataFrame()
    url = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": _market_symbol(code), "scale": scale, "ma": "no", "datalen": count}
    try:
        resp = requests.get(url, params=params, timeout=8,
                            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
        if resp.status_code != 200:
            return pd.DataFrame()
        rows = resp.json()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "datetime": r["day"],
            "open": float(r["open"]),
            "close": float(r["close"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "volume": float(r.get("volume", 0) or 0),
            "amount": float(r.get("amount", 0) or 0),
        } for r in rows])
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df
    except Exception as e:
        print(f"[data_source] 新浪K线失败({code}/{period}): {e}")
        return pd.DataFrame()


def _get_kline_tencent(code: str, period: str = "daily", count: int = 200) -> pd.DataFrame:
    """备用K线源2：腾讯财经（day/60m/30m/15m）。"""
    freq = {"daily": "day", "60m": "60m", "30m": "30m", "15m": "15m"}.get(period)
    if freq is None:
        return pd.DataFrame()
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{_market_symbol(code)},{freq},,,{count},qfq"}
    try:
        resp = requests.get(url, params=params, timeout=8,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return pd.DataFrame()
        data = resp.json()
        node = (data.get("data") or {}).get(_market_symbol(code)) or {}
        klines = node.get(freq) or node.get("qfq" + freq) or []
        if not klines:
            return pd.DataFrame()
        rows = []
        for p in klines:
            if len(p) < 6:
                continue
            try:
                # 腾讯 qfq 格式第 7 位可能是复权信息 dict/list，安全提取 amount
                amount = 0.0
                if len(p) > 6:
                    a = p[6]
                    if isinstance(a, (list, tuple)):
                        a = a[0] if a else 0
                    if isinstance(a, dict):
                        a = a.get("amount", 0)
                    try:
                        amount = float(a)
                    except (TypeError, ValueError):
                        amount = 0.0
                rows.append({
                    "datetime": p[0],
                    "open": float(p[1]),
                    "close": float(p[2]),
                    "high": float(p[3]),
                    "low": float(p[4]),
                    "volume": float(p[5]),
                    "amount": amount,
                })
            except (ValueError, IndexError, TypeError):
                continue
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df
    except Exception as e:
        print(f"[data_source] 腾讯K线失败({code}/{period}): {e}")
        return pd.DataFrame()


def get_kline(code: str, period: str = "daily", count: int = 200, is_index: bool = False) -> pd.DataFrame:
    """获取 K 线数据。

    Args:
        code: 6 位股票代码
        period: daily / 60m / 30m / 15m
        count: 根数
        is_index: 是否为指数（默认 False，个股；仅指数K线传 True）

    Returns:
        DataFrame[datetime, open, high, low, close, volume(手), amount(元)]
        失败返回空 DataFrame（自动降级：东财 → 新浪 → 腾讯）。
    """
    if period not in KLT_MAP:
        return pd.DataFrame()
    klt = KLT_MAP[period]
    params = {
        "secid": code_to_secid(code),
        "secid": code_to_secid(code, is_index),
        "ut": _UT,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": klt,
        "fqt": 1,
        "end": "20500101",
        "lmt": count,
    }
    data = _request_get(f"{_KLINE}/api/qt/stock/kline/get", params)
    if data and data.get("data") and data["data"].get("klines"):
        df = _parse_eastmoney_kline(data)
        if not df.empty:
            return df
    # 东财失败 → 新浪 → 腾讯
    for fn in (_get_kline_sina, _get_kline_tencent):
        df = fn(code, period, count)
        if not df.empty:
            return df
    return pd.DataFrame()


def _parse_eastmoney_kline(data: dict) -> pd.DataFrame:
    """解析东财 K 线响应为 DataFrame。"""
    klines = (data.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
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


def get_kline_daily(code: str, count: int = 120, is_index: bool = False) -> pd.DataFrame:
    """日线 K 线。"""
    return get_kline(code, "daily", count, is_index)


def get_kline_minute(code: str, period: str = "60m", count: int = 200, is_index: bool = False) -> pd.DataFrame:
    """分钟 K 线，period 支持 15m/30m/60m。"""
    return get_kline(code, period, count, is_index)


# ============================================================
# 行情与指数
# ============================================================
_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}
_SINA_INDEX_SECIDS = {
    "000001": "sh000001",  # 上证指数
    "000300": "sh000300",  # 沪深300
    "000016": "sh000016",  # 上证50
    "399001": "sz399001",  # 深证成指
    "399006": "sz399006",  # 创业板指
}


def _get_sina_indices() -> Dict[str, Dict]:
    """备用指数源：新浪 hq.sinajs.cn（东财不可达时使用）。"""
    try:
        codes = ",".join(_SINA_INDEX_SECIDS.values())
        resp = requests.get(f"https://hq.sinajs.cn/list={codes}",
                            headers=_SINA_HEADERS, timeout=8)
        resp.encoding = "gbk"
        result: Dict[str, Dict] = {}
        for line in resp.text.strip().split("\n"):
            if "=" not in line or '="' not in line:
                continue
            key = line.split("=")[0].strip().replace("var hq_str_", "")
            inner = line.split('="')[1].strip().rstrip(";").rstrip('"')
            if not inner:
                continue
            parts = inner.split(",")
            if len(parts) < 10:
                continue
            code = None
            for c, s in _SINA_INDEX_SECIDS.items():
                if s == key:
                    code = c
                    break
            if not code:
                continue
            try:
                price = float(parts[3])
                prev_close = float(parts[2])
                amount = float(parts[9])
                change_pct = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
                name = parts[0]
                result[code] = {
                    "code": code, "name": name,
                    "price": price, "change_pct": change_pct,
                    "amount_yi": amount / 1e8,
                }
            except (ValueError, IndexError):
                continue
        return result
    except Exception as e:
        print(f"[data_source] 新浪指数备用源失败: {e}")
        return {}


def _get_sina_limit_count() -> tuple[int, int]:
    """备用涨停/跌停统计：新浪全A列表（东财不可达时使用）。"""
    up = down = 0
    try:
        for pn in range(1, 7):
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            params = {"page": pn, "num": 1000, "sort": "changepercent", "asc": 0, "node": "hs_a", "_s_r_a": "page"}
            # 新浪每页最多 100 条，按涨跌幅排序翻页即可覆盖全市场涨停/跌停
            params = {"page": pn, "num": 100, "sort": "changepercent", "asc": 0, "node": "hs_a", "_s_r_a": "page"}
            resp = requests.get(url, params=params, headers=_SINA_HEADERS, timeout=8)
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
            if len(data) < 100:
                break
        return up, down
    except Exception as e:
        print(f"[data_source] 新浪涨跌停备用源失败: {e}")
        return 0, 0


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
    if not indices:
        print("[data_source] 东财指数不可达，切换新浪指数备用源")
        indices = _get_sina_indices()
    return indices


# 标的池分页参数：小页翻页，规避东财对大 pz 的截断/限流（GitHub 海外 IP 尤甚）
POOL_PAGE_SIZE = 200
POOL_MAX_PAGES = 20  # 200 x 20 = 4000，覆盖全部沪深主板
POOL_FETCH_TIMEOUT = 30  # 标的池抓取总时间预算（秒），超时即返回已获取部分
POOL_PAGE_TIMEOUT = 4    # 单页请求超时（秒），东财对海外IP不稳定，快速失败避免耗尽预算


def _get_mainboard_stocks_sina(limit: int = 6000, verbose_pool: bool = True) -> List[Dict]:
    """备用选股池源：新浪全A列表（东财 clist 不可达时使用）。"""
    stocks: List[Dict] = []
    seen: set = set()
    try:
        # 注意：新浪该接口每页最多返回 100 条（num 参数会被截断为 100），
        # 必须按 100/页 翻页直到页空，覆盖全A约 50+ 页
        for pn in range(1, 51):
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            params = {"page": pn, "num": 100, "sort": "amount", "asc": 0, "node": "hs_a", "_s_r_a": "page"}
            resp = requests.get(url, params=params, headers=_SINA_HEADERS, timeout=8)
            resp.encoding = "utf-8"
            try:
                data = resp.json()
            except Exception:
                break
            if not data:
                break
            for item in data:
                code = str(item.get("code", ""))
                if not (code.startswith("60") or code.startswith("00")):
                    continue
                if code in seen:
                    continue
                seen.add(code)
                try:
                    trade = float(item.get("trade", 0) or 0)
                except (TypeError, ValueError):
                    trade = 0.0
                try:
                    nmc_wan = float(item.get("nmc", 0) or 0)
                except (TypeError, ValueError):
                    nmc_wan = 0.0
                try:
                    amount = float(item.get("amount", 0) or 0)
                except (TypeError, ValueError):
                    amount = 0.0
                stocks.append({
                    "code": code,
                    "name": str(item.get("name", "")),
                    "price": trade,
                    "float_cap_yi": nmc_wan / 10000.0,  # nmc 单位：万元
                    "amount_yi": amount / 100000000.0,
                })
            if len(data) < 100:
                break
    except Exception as e:
        print(f"[data_source] 新浪选股池备用源失败: {e}")
    result = stocks[:limit]
    if verbose_pool:
        print(f"[data_source] 新浪选股池获取完成：{len(result)} 只（去重后）")
        for s in result[:3]:
            print(f"[data_source]   样例: {s}")
    return result


def get_mainboard_stocks(limit: int = 6000, verbose_pool: bool = True) -> List[Dict]:
    """沪深主板股票列表（60/00 开头），按成交额降序翻页获取。

    稳健性：
    - 单页失败不中断整体（记录跳过，继续下一页）
    - 按 code 去重，防止分页重叠
    - 遇到空页（数据末尾）提前结束

    返回字段：code / name / price / float_cap_yi / amount_yi
    """
    stocks: List[Dict] = []
    seen: set = set()
    max_pages = POOL_MAX_PAGES  # limit 仅作提前停止条件，不缩减翻页上限
    deadline = time.time() + POOL_FETCH_TIMEOUT
    for pn in range(1, max_pages + 1):
        if time.time() > deadline:
            break  # 时间预算耗尽，返回已获取部分
        params = {
            "pn": pn, "pz": POOL_PAGE_SIZE, "po": 1, "np": 1, "ut": _UT,
            "fltt": 2, "invt": 2, "fid": "f6",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f2,f6,f12,f14,f20",
        }
        data = _request_get(f"{_BASE}/api/qt/clist/get", params, timeout=POOL_PAGE_TIMEOUT,
                            verbose=True)
        if not data or not data.get("data"):
            if pn == 1:
                print(f"[data_source] 选股池首页失败(pn=1)，返回 {len(stocks)} 只，放弃翻页")
                break  # 首页即失败：数据源不可达，不再浪费预算
            continue  # 单页失败，跳过继续
        diff = data["data"].get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not diff:
            break  # 数据末尾
        for item in diff:
            code = str(item.get("f12", ""))
            if not (code.startswith("60") or code.startswith("00")):
                continue
            if code in seen:
                continue
            seen.add(code)
            stocks.append({
                "code": code,
                "name": str(item.get("f14", "")),
                "price": float(item.get("f2", 0) or 0),
                "float_cap_yi": get_float_market_cap_yi(item),
                "amount_yi": get_amount_yi(item),
            })
        time.sleep(0.2)
        if len(stocks) >= limit:
            break
    result = stocks[:limit]
    # 东财被代理限流/翻页受限时可能只拿到部分池子（如 600 只），
    # 若未达健康量（1500 只）则补拉新浪全量池，取覆盖更大者，保证选股池>1000 门槛
    if limit >= 100 and len(result) < 1500:
        print(f"[data_source] 东财选股池覆盖不足(仅{len(result)}只)，补拉新浪全量池")
        sina_pool = _get_mainboard_stocks_sina(limit, verbose_pool)
        if len(sina_pool) > len(result):
            print(f"[data_source] 采用新浪池({len(sina_pool)}只 > 东财{len(result)}只)")
            result = sina_pool
    if verbose_pool:
        print(f"[data_source] 选股池获取完成：{len(result)} 只（去重后）")
        for s in result[:3]:
            print(f"[data_source]   样例: {s}")
        if not result:
            print(f"[data_source] 选股池为空，原始响应样本: {str(data)[:300]}")
    return result


# 涨跌停判定阈值：主板 10%（ST 5% 不计入，天然被 9.9 过滤）
LIMIT_UP_THRESHOLD = 9.9
LIMIT_DOWN_THRESHOLD = -9.9


def get_limit_up_down_count() -> tuple[int, int]:
    """动态统计沪深A股涨停/跌停家数。

    方法：调用东财沪深A股列表接口，遍历全部股票按 f3 涨幅统计：
    - f3 ≥ 9.9 → 涨停（近似，ST 股 5% 涨停不计入）
    - f3 ≤ -9.9 → 跌停
    注意：东财 f3 单位为百分比（10.0 表示 10%），无需再除 100。

    Returns:
        (涨停家数, 跌停家数)；接口失败返回 (0, 0) 并打印错误日志，不崩溃。
    """
    params = {
        "pn": 1, "pz": 6000, "po": 1, "np": 1, "ut": _UT,
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f3,f4,f5,f6,f15,f16,f17,f18",
    }
    try:
        data = _request_get(f"{_BASE}/api/qt/clist/get", params)
        if not data or not data.get("data"):
            print("[get_limit_up_down_count] 东财接口无数据，切换新浪备用源")
            return _get_sina_limit_count()
        diff = data["data"].get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        up = down = 0
        for item in diff:
            try:
                chg = float(item.get("f3", 0) or 0)
            except (TypeError, ValueError):
                continue
            if chg >= LIMIT_UP_THRESHOLD:
                up += 1
            elif chg <= LIMIT_DOWN_THRESHOLD:
                down += 1
        if up == 0 and down == 0:
            print("[get_limit_up_down_count] 东财无涨跌停数据，切换新浪备用源")
            return _get_sina_limit_count()
        return up, down
    except Exception as e:
        print(f"[get_limit_up_down_count] 异常: {e}，切换新浪备用源")
        return _get_sina_limit_count()


def count_limit_up_down() -> tuple[int, int]:
    """兼容旧接口：等价于 get_limit_up_down_count()。"""
    return get_limit_up_down_count()


def get_market_total_amount_yi() -> float:
    """两市总成交额（亿）≈ 上证 + 深证指数成交额。"""
    idx = get_market_indices()
    total = 0.0
    for key in ("000001", "399001"):
        total += idx.get(key, {}).get("amount_yi", 0.0)
    return total
