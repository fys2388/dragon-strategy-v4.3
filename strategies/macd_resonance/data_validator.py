# -*- coding: utf-8 -*-
"""数据自驱层 V2.0：多源校验 + 异常告警 + 自动降级。

- MarketData：市场快照数据类（指数/成交额/涨跌停）
- get_data_eastmoney()：主源（现有东财逻辑）
- get_data_akshare()：备源（akshare，需 pip install akshare，lazy import）
- validate_market_data()：双源交叉校验，输出异常列表与建议源
- send_feishu_alert()：告警推送（webhook 环境变量/配置文件）
- 数据源成功率记录：data/data_source_status.json（保留最近 10 次）
"""
from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from . import data_source as ds
from .data_sources.source_sina import get_data_sina
from .trading_calendar import now_bjt

def _ensure_utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            reconfigure = getattr(stream, 'reconfigure', None)
            if reconfigure:
                reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


_ensure_utf8_stdout()

STATUS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "data", "data_source_status.json")
STATUS_HISTORY = 10  # 各源保留最近 N 次记录
_FETCH_TIMEOUT = 8   # 并发拉取超时（秒）

_LOCK = threading.Lock()


# ============================================================
# 数据类
# ============================================================
@dataclass
class MarketData:
    """市场快照。"""
    index_price: float          # 沪指点位
    index_change_pct: float     # 沪指涨跌幅（%）
    volume_yi: float            # 两市成交额（亿）
    limit_up_count: int
    limit_down_count: int
    timestamp: str
    source: str = "eastmoney"   # eastmoney / akshare
    raw: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """双源校验结果。"""
    passed: bool                # 是否无异常（含警告视为不通过但可继续）
    anomalies: List[str]
    chosen_source: str          # eastmoney / akshare / none
    severity: str               # ok / warning / critical / fatal(双源不可用)


# ============================================================
# 主源：东方财富
# ============================================================
def get_data_eastmoney() -> Optional[MarketData]:
    """主源数据：东财指数 + 成交额 + 涨跌停。失败返回 None。"""
    try:
        indices = ds.get_market_indices()
        sh = indices.get("000001") or {}
        index_price = float(sh.get("price") or 0)
        index_change_pct = float(sh.get("change_pct") or 0)
        volume_yi = ds.get_market_total_amount_yi()
        up, down = ds.get_limit_up_down_count()
        if index_price <= 0:
            print("[data_validator] 东财主源指数为空，标记不可用")
            return None
        return MarketData(
            index_price=index_price, index_change_pct=index_change_pct,
            volume_yi=volume_yi, limit_up_count=up, limit_down_count=down,
            timestamp=now_bjt().strftime("%Y-%m-%d %H:%M:%S"), source="eastmoney",
        )
    except Exception as e:
        print(f"[data_validator] 东财主源异常: {e}")
        return None


# ============================================================
# 备源：AkShare
# ============================================================
def get_data_akshare() -> Optional[MarketData]:
    """备源数据：akshare 指数 + 全A涨跌停。未安装/失败返回 None。"""
    try:
        import akshare as ak
    except ImportError:
        print("[data_validator] akshare 未安装，备源不可用")
        return None
    try:
        # 指数实时：优先东财版接口（akshare>=1.12），旧版接口名兼容
        idx_fn = getattr(ak, "stock_zh_index_spot_em", None) or getattr(ak, "stock_zh_index_spot", None)
        if idx_fn is None:
            print("[data_validator] akshare 无指数接口")
            return None
        idx = idx_fn()
        code_col = "代码" if "代码" in idx.columns else idx.columns[0]
        sh_row = idx[idx[code_col].astype(str).str.startswith("000001")].head(1)
        if sh_row.empty:
            print("[data_validator] akshare 未取到沪指")
            return None
        index_price = float(sh_row.iloc[0].get("最新价", 0) or 0)
        index_change_pct = float(sh_row.iloc[0].get("涨跌幅", 0) or 0)

        # 全A实时：优先东财版
        spot_fn = getattr(ak, "stock_zh_a_spot_em", None) or getattr(ak, "stock_zh_a_spot", None)
        if spot_fn is None:
            print("[data_validator] akshare 无全A接口")
            return None
        spot = spot_fn()
        chg_col = "涨跌幅"
        if chg_col not in spot.columns:
            print("[data_validator] akshare 全A缺少涨跌幅列")
            return None
        chg = spot[chg_col].astype(float)
        up = int((chg >= 9.9).sum())
        down = int((chg <= -9.9).sum())

        # 两市成交额（亿）≈ 沪市 + 深市指数成交额
        volume_yi = 0.0
        for code in ("000001", "399001"):
            r = idx[idx[code_col].astype(str).str.startswith(code)].head(1)
            if not r.empty:
                vol = float(r.iloc[0].get("成交额", 0) or 0)
                volume_yi += vol / 100000000.0
        return MarketData(
            index_price=index_price, index_change_pct=index_change_pct,
            volume_yi=volume_yi, limit_up_count=up, limit_down_count=down,
            timestamp=now_bjt().strftime("%Y-%m-%d %H:%M:%S"), source="akshare",
            raw={"idx_rows": len(idx), "spot_rows": len(spot)},
        )
    except Exception as e:
        print(f"[data_validator] akshare 备源异常: {e}")
        return None


# ============================================================
# 三级数据源：东财 -> 新浪 -> AkShare
# 说明：AkShare 的 *_em 接口底层仍走东财 push2.eastmoney.com，
#       与东财同源、在海外IP/东财不可达时同样失败且内部重试可能长时间挂起，
#       故把真正独立、对海外IP友好的新浪放在 AkShare 之前。
# ============================================================
_SOURCE_CHAIN = ["eastmoney", "sina", "akshare"]
_AKSHARE_TIMEOUT = 15  # 秒；AkShare 内部网络重试无超时，强制兜底


def _run_with_timeout(fn, timeout: float):
    """在守护线程中执行 fn，超过 timeout 返回 None（防止数据源挂死）。"""
    import queue
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            q.put(fn())
        except Exception as e:  # noqa: BLE001
            print(f"[data_validator] {getattr(fn, '__name__', 'source')} 异常: {e}")
            q.put(None)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        print(f"[data_validator] {getattr(fn, '__name__', 'source')} 超时({timeout}s)，放弃")
        return None


def get_data_with_fallback():
    """按优先级链获取市场数据，返回 (MarketData|None, chosen_source)."""
    for src in _SOURCE_CHAIN:
        if src == "eastmoney":
            fn = get_data_eastmoney
        elif src == "akshare":
            fn = lambda: _run_with_timeout(get_data_akshare, _AKSHARE_TIMEOUT)
        else:
            fn = get_data_sina
        data = fn()
        if data is not None:
            if isinstance(data, dict):
                from .data_validator import MarketData
                data = MarketData(
                    index_price=data.get("index_price", 0),
                    index_change_pct=data.get("index_change_pct", 0),
                    volume_yi=data.get("volume_yi", 0),
                    limit_up_count=data.get("limit_up_count", 0),
                    limit_down_count=data.get("limit_down_count", 0),
                    timestamp=data.get("timestamp", ""),
                    source="sina",
                )
            print(f"[data_validator] 数据源 {src} 可用，指数={data.index_price:.2f} 涨停={data.limit_up_count}")
            return data, src
    print("[data_validator] 三源全部不可用")
    return None, "none"


# ============================================================
# 双源并发拉取 + 交叉校验
# ============================================================
def _fetch_both() -> Dict[str, Optional[MarketData]]:
    """并发拉取主源+备源，单源超时/异常不影响另一源。"""
    result: Dict[str, Optional[MarketData]] = {"eastmoney": None, "akshare": None}

    def _get(name: str, fn):
        try:
            result[name] = fn()
        except Exception as e:
            print(f"[data_validator] {name} 拉取异常: {e}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_get, "eastmoney", get_data_eastmoney)
        f2 = pool.submit(_get, "akshare", get_data_akshare)
        for fut in (f1, f2):
            try:
                fut.result(timeout=_FETCH_TIMEOUT)
            except Exception:
                pass  # 超时，该源记为 None
    return result


def validate_market_data(primary: Optional[MarketData],
                         backup: Optional[MarketData]) -> ValidationResult:
    """交叉校验主备源，决定使用哪个源。

    规则：
    - 指数价格差异 > 2% → 严重异常
    - 成交额差异 > 20% → 警告
    - 涨停家数差异 > 50% 且绝对值 > 10 → 严重异常
    - 跌停家数差异 > 100% → 警告
    """
    anomalies: List[str] = []
    critical = False

    if primary is None and backup is None:
        return ValidationResult(False, ["主源与备源均不可用"], "none", "fatal")
    if primary is None:
        return ValidationResult(False, ["主源(东财)不可用，切换备源"], "akshare", "warning")
    if backup is None:
        return ValidationResult(True, ["备源(AkShare)不可用，使用主源"], "eastmoney", "degraded")

    # 相对差异
    def rel_diff(a: float, b: float) -> float:
        denom = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / denom * 100.0

    # 1. 指数价格
    if rel_diff(primary.index_price, backup.index_price) > 2.0:
        critical = True
        anomalies.append(f"指数价格差异{rel_diff(primary.index_price, backup.index_price):.1f}%>2%（主={primary.index_price:.0f}，备={backup.index_price:.0f}）")
    # 2. 成交额
    if rel_diff(primary.volume_yi, backup.volume_yi) > 20.0:
        anomalies.append(f"成交额差异{rel_diff(primary.volume_yi, backup.volume_yi):.1f}%>20%（主={primary.volume_yi:.0f}亿，备={backup.volume_yi:.0f}亿）")
    # 3. 涨停家数
    up_diff = rel_diff(primary.limit_up_count, backup.limit_up_count)
    if up_diff > 50.0 and abs(primary.limit_up_count - backup.limit_up_count) > 10:
        critical = True
        anomalies.append(f"涨停家数差异{up_diff:.0f}%（主={primary.limit_up_count}，备={backup.limit_up_count}）")
    # 4. 跌停家数
    down_diff = rel_diff(primary.limit_down_count, backup.limit_down_count)
    if down_diff > 100.0:
        anomalies.append(f"跌停家数差异{down_diff:.0f}%（主={primary.limit_down_count}，备={backup.limit_down_count}）")

    if critical:
        return ValidationResult(False, anomalies or ["主源数据严重异常"], "akshare", "critical")
    if anomalies:
        return ValidationResult(False, anomalies, "eastmoney", "warning")
    return ValidationResult(True, [], "eastmoney", "ok")


# ============================================================
# 数据源成功率记录（data_source_status.json）
# ============================================================
def _load_status() -> Dict:
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"eastmoney": {"recent": []}, "akshare": {"recent": []}}


def _save_status(data: Dict):
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[data_validator] 状态记录写入失败: {e}")


def update_source_status(source: str, ok: bool):
    """记录一次数据源调用结果（保留最近 10 次）。"""
    with _LOCK:
        data = _load_status()
        rec = data.setdefault(source, {"recent": []})
        rec["recent"].append({"ts": now_bjt().strftime("%Y-%m-%d %H:%M:%S"), "ok": bool(ok)})
        rec["recent"] = rec["recent"][-STATUS_HISTORY:]
        recent = rec["recent"]
        rec["success"] = sum(1 for r in recent if r["ok"])
        rec["fail"] = len(recent) - rec["success"]
        rec["success_rate"] = round(rec["success"] / len(recent) * 100, 1) if recent else 0.0
        _save_status(data)


def get_source_status() -> Dict:
    return _load_status()

# ============================================================
# 选股池校验
# ============================================================
MIN_POOL_SIZE = 1000
HEALTHY_POOL_SIZE = 3000


def validate_stock_pool(pool):
    """校验选股池数据质量。"""
    anomalies = []
    critical = False
    if not pool:
        return ValidationResult(False, ["选股池为空"], "none", "critical")
    size = len(pool)
    if size < MIN_POOL_SIZE:
        critical = True
        anomalies.append(f"选股池仅 {size} 只 < {MIN_POOL_SIZE}")
    price_zeros = sum(1 for x in pool if not (x.get("price") or 0))
    cap_zeros = sum(1 for x in pool if not (x.get("float_cap_yi") or 0))
    if cap_zeros == size:
        critical = True
        anomalies.append("流通市值字段全为 0")
    if price_zeros == size:
        critical = True
        anomalies.append("现价字段全为 0")
    non_empty_rate = 1.0 - (price_zeros + cap_zeros) / max(size * 2, 1)
    if not critical:
        if size > HEALTHY_POOL_SIZE and non_empty_rate > 0.95:
            return ValidationResult(True, [], "pool", "ok")
        anomalies.append(f"池子 {size} 只（未达健康值 {HEALTHY_POOL_SIZE}）")
        return ValidationResult(False, anomalies, "pool", "warning")
    return ValidationResult(False, anomalies, "pool", "critical")



# ============================================================
# 飞书告警
# ============================================================
def get_webhook() -> str:
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        return webhook
    try:
        from utils.config_loader import load_feishu_config
        return load_feishu_config()["webhook_url"]
    except Exception:
        return ""


def send_feishu_alert(message: str, title: str = "数据异常告警") -> bool:
    """推送 ⚠️ 告警卡片（纯文本卡片）。失败返回 False。"""
    webhook = get_webhook()
    if not webhook:
        print(f"❌ [alert] 未配置 webhook，跳过告警: {message}")
        return False
    text = f"⚠️ {title}\n{message}"
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
        return resp.status_code == 200
    except Exception as e:
        print(f"❌ [alert] 告警推送失败: {e}")
        return False


# ============================================================
# 缓存辅助
# ============================================================
def get_cached_market():
    try:
        from .cache import get_cached
        return get_cached("market")
    except Exception:
        return None

def set_cached_market(data):
    try:
        from .cache import set_cached
        if data is not None:
            set_cached("market", {"index_price": data.index_price, "index_change_pct": data.index_change_pct, "volume_yi": data.volume_yi, "limit_up_count": data.limit_up_count, "limit_down_count": data.limit_down_count, "source": data.source, "timestamp": data.timestamp})
    except Exception as e:
        print(f"[cache] 写入失败: {e}")

def get_cached_pool():
    try:
        from .cache import get_cached
        return get_cached("stock_pool")
    except Exception:
        return None

def set_cached_pool(pool):
    try:
        from .cache import set_cached
        if pool:
            set_cached("stock_pool", pool)
    except Exception as e:
        print(f"[cache] 写入失败: {e}")
