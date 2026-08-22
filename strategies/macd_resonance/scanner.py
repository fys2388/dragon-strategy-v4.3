# -*- coding: utf-8 -*-
"""主扫描入口模块。

流程：大盘门控 → 标的池初筛 → 硬过滤 → 多周期信号分析 → 去重冷却 → 输出。
并发控制：ThreadPoolExecutor(max_workers=8) + 单只 0.3s 间隔。
日志：logs/scanner_YYYYMMDD.log + 控制台双输出。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

from . import data_source as ds
from .config import RISK, SIGNAL
from .filters import pass_hard_filters
from .market_gate import get_market_score
from .portfolio_manager import PortfolioManager
from .trading_calendar import BJT, is_trading_time, now_bjt
from .signal_engine import SignalEngine, SignalType
from .data_validator import (ValidationResult, get_data_with_fallback, send_feishu_alert,
                             update_source_status, validate_stock_pool, get_cached_pool, set_cached_pool)
from .market_regime import REGIME_LABELS, classify_regime

LOCK = threading.Lock()

# ============================================================
# 日志
# ============================================================
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
HISTORY_FILE = os.path.join(os.path.dirname(LOG_DIR), "data", "strategy_history.jsonl")
MIN_POOL_SIZE = 100  # 选股池最小数量（正常 A 股 5000+ 只）


class _BJTFormatter(logging.Formatter):
    """日志时间使用北京时间显示。"""

    def formatTime(self, record, datefmt=None):
        dt = now_bjt()
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def _now_naive() -> datetime:
    """当前北京时间（naive，用于缓存/冷却期比较）。"""
    return now_bjt().replace(tzinfo=None)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("scanner")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = _BJTFormatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = logging.FileHandler(os.path.join(LOG_DIR, f"scanner_{datetime.now().strftime('%Y%m%d')}.log"),
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


LOG = setup_logger()


def _write_anomaly_log(line: str):
    """追加数据异常日志到 logs/data_anomaly.log。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "data_anomaly.log"), "a", encoding="utf-8") as f:
            f.write(f"{now_bjt().strftime('%Y-%m-%d %H:%M:%S')} | {line}\n")
    except Exception as e:
        LOG.warning(f"异常日志写入失败: {e}")


class Scanner:
    """MACD 多周期共振主扫描器。"""

    def __init__(self, engine: Optional[SignalEngine] = None):
        self.engine = engine or SignalEngine()
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.cache_file = os.path.join(self.base_dir, "data", "signal_cache.json")
        self.cache = self._load_cache()

    # ----------------------------------------------------------
    # 信号去重（冷却期）
    # ----------------------------------------------------------
    def _load_cache(self) -> Dict:
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"pushed": {}}

    def _save_cache(self):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def _is_in_cooldown(self, code: str) -> bool:
        last = self.cache.get("pushed", {}).get(code)
        if not last:
            return False
        try:
            last_ts = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
        hours = (_now_naive() - last_ts).total_seconds() / 3600
        return hours < SIGNAL["cooldown_hours"]

    def _mark_pushed(self, code: str):
        self.cache.setdefault("pushed", {})[code] = _now_naive().strftime("%Y-%m-%d %H:%M:%S")
        self._save_cache()

    # ----------------------------------------------------------
    # 策略历史记录（供复盘/看板使用）
    # ----------------------------------------------------------
    def _append_history(self, result: Dict):
        """将一次扫描结果追加到 data/strategy_history.jsonl。"""
        record = {
            "ts": result.get("scan_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "market_score": result.get("market_score", 0.0),
            "can_open": result.get("can_open", False),
            "summary": result.get("summary", ""),
            "entries": [
                {"code": e.get("code"), "name": e.get("name"),
                 "price": e.get("price"), "score": e.get("score")}
                for e in result.get("entries", [])
            ],
            "exit_signals": [
                {"code": s.get("code"), "signal_type": s.get("signal_type"),
                 "profit_pct": s.get("profit_pct"), "suggestion": s.get("suggestion")}
                for s in result.get("exit_signals", [])
            ],
        }
        try:
            os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            LOG.warning(f"策略历史记录写入失败: {e}")

    # ----------------------------------------------------------
    # 快速初筛（价格/市值/名称，不拉K线）
    # ----------------------------------------------------------
    def _fetch_pool_with_retry(self, max_stocks: int,
                               min_size: int = MIN_POOL_SIZE,
                               retries: int = 2, gap: float = 2.0) -> List[Dict]:
        """获取选股池，不足 min_size 只时重试 retries 次（间隔 gap 秒）。"""
        # 当日缓存优先：避免多次扫描重复请求接口（大盘数据同理由 data_validator 处理）
        try:
            cached = data_validator.get_cached_pool()
            cached = get_cached_pool()
            if cached and len(cached) >= min_size:
                LOG.info(f"选股池使用当日缓存：{len(cached)} 只")
                return cached[:max_stocks]
        except Exception as e:
            LOG.warning(f"选股池缓存读取失败: {e}")
        stocks: List[Dict] = []
        for attempt in range(retries + 1):
            stocks = ds.get_mainboard_stocks(limit=max_stocks)
            if len(stocks) >= min_size:
                try:
                    data_validator.set_cached_pool(stocks)
                    set_cached_pool(stocks)
                except Exception as e:
                    LOG.warning(f"选股池缓存写入失败: {e}")
                return stocks
            LOG.warning(f"选股池异常: 仅 {len(stocks)} 只 < {min_size}（第 {attempt + 1}/{retries + 1} 次）")
            if attempt < retries:
                time.sleep(gap)
        return stocks

    def _quick_filter(self, stock: dict) -> bool:
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        price = float(stock.get("price", 0) or 0)
        cap = float(stock.get("float_cap_yi", 0) or 0)
        if price < 3.0 or price > 35.0:
            return False
        if cap < 30 or cap > 600:
            return False
        return True

    def _enrich_hard_metrics(self, stock: dict) -> dict:
        """补充 20 日均额与振幅，供硬过滤使用。"""
        df = ds.get_kline_daily(stock["code"], count=25)
        if df.empty or len(df) < 20:
            stock["amount_20d_wan"] = 0.0
            stock["amplitude_20d_pct"] = 0.0
            return stock
        closes = df["close"].astype(float)
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        amounts = df["amount"].astype(float)
        stock["amount_20d_wan"] = float(amounts.iloc[-20:].mean()) / 10000.0
        base = float(closes.iloc[-21]) if len(closes) >= 21 else float(closes.iloc[0])
        if base > 0:
            stock["amplitude_20d_pct"] = (float(highs.iloc[-20:].max()) - float(lows.iloc[-20:].min())) / base * 100.0
        else:
            stock["amplitude_20d_pct"] = 0.0
        return stock

    # ----------------------------------------------------------
    # 主扫描
    # ----------------------------------------------------------
    def run(self, max_stocks: int = 2000, need_push: bool = False,
            source: str = "auto") -> Dict:
        """执行扫描。

        Returns:
            {
              scan_time, market_score, market_desc, can_open,
              entries, avoids, errors, summary, diagnosis,
            }
        """
        result = {
            "scan_time": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
            "market_score": 0.0,
            "market_desc": "",
            "can_open": False,
            "entries": [],
            "avoids": 0,
            "errors": [],
            "summary": "",
            "diagnosis": "",
            "exit_signals": [],
            "scan_elapsed": 0.0,
            "limit_up": 0,
            "limit_down": 0,
            "scanned_count": 0,
            "passed_count": 0,
            "resonance_count": 0,
            "recommend_count": 0,
            "data_source": "eastmoney",
            "validation_state": "ok",
            "validation_anomalies": [],
            "regime": "range_bound",
            "data_error": False,
        }
        t0 = time.time()

        # 0. 持仓离场信号（无论门控是否通过都执行）
        try:
            pm = PortfolioManager()
            exit_signals = pm.check_exit_signals()
            if exit_signals:
                result["exit_signals"] = [s.__dict__ for s in exit_signals]
                LOG.info(f"持仓离场信号 {len(exit_signals)} 条："
                         + "; ".join(f"{s.code} {s.signal_type}" for s in exit_signals))
        except Exception as e:
            LOG.warning(f"持仓离场检查异常: {e}")

        # 0.5 数据自驱层：三源降级（东财 → AkShare → 新浪）+ 熔断
        chosen_md = None
        if source in ("eastmoney", "akshare", "sina"):
            from .data_validator import get_data_eastmoney, get_data_akshare, get_data_sina
            fn_map = {"eastmoney": get_data_eastmoney, "akshare": get_data_akshare, "sina": get_data_sina}
            forced = fn_map[source]()
            update_source_status(source, forced is not None)
            if forced is None:
                result["data_error"] = True
                result["summary"] = f"强制数据源 {source} 不可用，跳过本次扫描"
                result["scan_elapsed"] = round(time.time() - t0, 1)
                msg = f"指定数据源 {source} 不可用，已跳过本次扫描。"
                LOG.error(msg)
                _write_anomaly_log(msg)
                send_feishu_alert(msg, "数据源不可用")
                self._append_history(result)
                return result
            chosen_md = forced
            result["data_source"] = source
            result["validation_state"] = "ok"
            LOG.info(f"强制数据源 {source} 可用，指数={chosen_md.index_price:.2f}")
        else:
            chosen_md, chosen_src = get_data_with_fallback()
            update_source_status("eastmoney", chosen_src == "eastmoney")
            update_source_status("akshare", chosen_src == "akshare")
            update_source_status("sina", chosen_src == "sina")
            result["data_source"] = chosen_src
            result["validation_state"] = "ok" if chosen_src == "eastmoney" else "switched"
            if chosen_src == "none":
                result["data_error"] = True
                result["summary"] = "数据异常，策略暂停"
                result["scan_elapsed"] = round(time.time() - t0, 1)
                msg = "东财/AkShare/新浪三源均不可用，今日策略暂停执行，请检查网络或数据源。"
                LOG.error(msg)
                _write_anomaly_log(msg)
                send_feishu_alert(msg, "数据异常，策略暂停")
                self._append_history(result)
                return result
            if chosen_src != "eastmoney":
                LOG.warning(f"主源(东财)不可用，自动切换 {chosen_src}")
                _write_anomaly_log(f"data_validate | 主源不可用，切换 {chosen_src}")
                send_feishu_alert(f"主源(东财)不可用，已自动切换至 {chosen_src} 数据源")

        # 熔断：数据有效性前置校验（指数为0 / 交易时段涨跌停均为0）
        if chosen_md is not None:
            if chosen_md.index_price <= 0:
                result["data_error"] = True
                msg = "行情数据异常：指数价格为0，本次扫描暂停。"
                LOG.error(msg)
                _write_anomaly_log(f"circuit_break | {msg}")
                send_feishu_alert(msg, "行情数据异常")
                result["summary"] = msg
                result["scan_elapsed"] = round(time.time() - t0, 1)
                self._append_history(result)
                return result
            if is_trading_time() and chosen_md.limit_up_count == 0 and chosen_md.limit_down_count == 0:
                result["data_error"] = True
                msg = "行情数据异常：交易时段内涨跌停数为0，疑似接口故障，本次扫描暂停。"
                LOG.error(msg)
                _write_anomaly_log(f"circuit_break | {msg}")
                send_feishu_alert(msg, "行情数据异常")
                result["summary"] = msg
                result["scan_elapsed"] = round(time.time() - t0, 1)
                self._append_history(result)
                return result

        result["limit_up"] = int(chosen_md.limit_up_count)
        result["limit_down"] = int(chosen_md.limit_down_count)
        result["regime"] = classify_regime(chosen_md)
        LOG.info(f"涨跌停家数：涨停{result['limit_up']}家 / 跌停{result['limit_down']}家 | "
                 f"数据源={result['data_source']} | 市场环境={result['regime']}")

        # 1. 大盘门控（使用选中源的同一快照）
        score, desc, can_open = get_market_score(market_data=chosen_md)
        result["market_score"] = score
        result["market_desc"] = desc
        result["can_open"] = can_open
        LOG.info(f"大盘评分 {score:.1f}/7，门控{'通过' if can_open else '未通过'}")
        if not can_open:
            result["summary"] = f"大盘评分 {score:.1f} 分 < 4，仅允许平仓/空仓，禁止新开多。"
            LOG.info(result["summary"])
            result["scan_elapsed"] = round(time.time() - t0, 1)
            self._append_history(result)
            return result

        # 2. 标的池 + 初筛（空池保护：<100 只重试 2 次，仍失败推送告警并跳过）
        all_stocks = self._fetch_pool_with_retry(max_stocks)
        if len(all_stocks) < MIN_POOL_SIZE:
            result["summary"] = "选股池数据异常，已跳过本次扫描"
            LOG.error(f"{result['summary']}（仅 {len(all_stocks)} 只）")
            _write_anomaly_log(f"stock_pool | 选股池仅 {len(all_stocks)} 只 < {MIN_POOL_SIZE}")
            send_feishu_alert(
                f"选股池数据异常：获取 {len(all_stocks)} 只（< {MIN_POOL_SIZE}），已跳过本次扫描。",
                "选股池数据异常")
            result["scan_elapsed"] = round(time.time() - t0, 1)
            self._append_history(result)
            return result

        # 池质量校验（f20/f2 字段完整性）
        pv = validate_stock_pool(all_stocks)
        result["pool_validation"] = pv.severity
        if pv.severity == "critical":
            detail = "; ".join(pv.anomalies)
            LOG.error(f"选股池校验失败: {detail}")
            _write_anomaly_log(f"stock_pool | {detail}")
            send_feishu_alert(f"选股池数据异常：{detail}，已跳过本次扫描。", "选股池数据异常")
            result["summary"] = "选股池数据异常，已跳过本次扫描"
            result["scan_elapsed"] = round(time.time() - t0, 1)
            self._append_history(result)
            return result
        candidates = [s for s in all_stocks if self._quick_filter(s)]
        LOG.info(f"标的池 {len(all_stocks)} 只（校验:{pv.severity}）→ 初筛 {len(candidates)} 只")

        # 3. 硬过滤（并发补齐 20 日均额/振幅）
        with ThreadPoolExecutor(max_workers=8) as pool:
            enriched = list(pool.map(self._enrich_hard_metrics, candidates))
        passed = []
        reject_reasons = Counter()
        for s in enriched:
            ok, reason = pass_hard_filters(s)
            if ok:
                passed.append(s)
            else:
                reject_reasons[reason] += 1
        LOG.info(f"硬过滤通过 {len(passed)} 只，拒绝 {len(enriched) - len(passed)} 只")
        top_rejects = [r for r, _ in reject_reasons.most_common(3)]

        # 4. 多周期信号分析（并发 + 0.3s 间隔限速）
        entries: List[Dict] = []
        avoid_count = 0
        tf_stats = Counter()
        delay = threading.Event()

        def analyze(stock: dict):
            delay.wait(0.3)
            return self.engine.analyze_stock(stock["code"], stock["name"], stock["price"])

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(analyze, s) for s in passed]
            for fut in as_completed(futs):
                try:
                    sig = fut.result()
                except Exception as e:
                    result["errors"].append(f"analyze error: {e}")
                    continue
                if sig.tf_status:
                    if sig.tf_status.get("daily_above_zero"):
                        tf_stats["日线零轴上方"] += 1
                    if sig.tf_status.get("tf60_golden"):
                        tf_stats["60min金叉"] += 1
                    if sig.tf_status.get("tf30_golden"):
                        tf_stats["30min金叉"] += 1
                    if sig.tf_status.get("tf15_cross_zero"):
                        tf_stats["15min上穿零轴"] += 1
                if sig.signal_type == SignalType.LONG_ENTRY:
                    entries.append(sig.__dict__)
                elif sig.signal_type == SignalType.AVOID:
                    avoid_count += 1

        tf_desc = " | ".join(f"{k}{v}只" for k, v in tf_stats.most_common())
        LOG.info(f"周期信号统计：{tf_desc or '无'}")
        LOG.info(f"共振信号 {len(entries)} 只，空头规避 {avoid_count} 只")

        # 5. 共振强度排序，取前 5
        entries.sort(key=lambda x: x.get("score", 0), reverse=True)
        top = entries[:5]

        # 6. 去重冷却
        final = []
        for e in top:
            if not self._is_in_cooldown(e["code"]):
                final.append(e)
                if need_push:
                    self._mark_pushed(e["code"])

        result["entries"] = final
        result["avoids"] = avoid_count
        result["scanned_count"] = len(all_stocks)
        result["passed_count"] = len(passed)
        result["resonance_count"] = len(entries)
        result["recommend_count"] = len(final)
        result["summary"] = f"初筛 {len(all_stocks)} → {len(candidates)} 只 → 硬过滤 {len(passed)} 只 → 共振信号 {len(entries)} 只 → 推荐 {len(final)} 只"
        result["diagnosis"] = (
            f"扫描{len(all_stocks)}只 → 过滤后{len(passed)}只 → 共振通过{len(entries)}只"
            f" | 主要拒因：{'、'.join(top_rejects) if top_rejects else '无'}"
        )
        LOG.info(result["summary"])
        result["scan_elapsed"] = round(time.time() - t0, 1)
        self._append_history(result)
        return result


def build_message(result: Dict) -> str:
    """将扫描结果格式化为飞书消息。"""
    now = now_bjt().strftime("%Y-%m-%d %H:%M")
    lines = [f"📊 MACD多周期共振策略 盘中实时 {now}", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]

    lines.append("【大盘环境】")
    lines.append(f"大盘评分：{result['market_score']:.1f}/7分 | {'🟢可开仓' if result['can_open'] else '🔴观望'}")
    for line in result["market_desc"].split("\n")[:5]:
        lines.append(f"  {line}")
    lines.append("")

    lines.append("【重点推荐（多周期共振）】")
    if result["entries"]:
        for i, e in enumerate(result["entries"], 1):
            levels = "+".join(e.get("resonance_levels", []))
            lines.append(f"{i}. {e['name']}({e['code']}) | 现价{e['price']}元")
            lines.append(f"   共振级别：{levels} | 得分{e['score']}")
            lines.append(f"   理由：{e['reason']}")
            lines.append("")
        single = RISK["total_capital"] * RISK["position_pct"]
        lines.append(f"💼 仓位建议（本金{RISK['total_capital']:.0f}元）")
        lines.append(f"  单票≤30%（{single:.0f}元），最多{RISK['max_positions']}只")
        lines.append(f"  止盈：+{RISK['take_profit_1_pct'] * 100:.0f}%减半 / +{RISK['take_profit_2_pct'] * 100:.0f}%清仓 | 止损：-{RISK['stop_loss_pct'] * 100:.0f}%")
    else:
        lines.append("  当前无符合多周期共振的标的，继续观望")
    lines.append("")

    # 持仓提醒（最高优先级区块）
    if result.get("exit_signals"):
        lines.append("【持仓提醒】")
        icon = {"hard_stop": "🚨", "zero_axis_break": "🔴", "tf60_divergence": "🟠",
                "take_profit_2": "💰", "take_profit_1": "💎"}
        for s in result["exit_signals"]:
            lines.append(f"{icon.get(s['signal_type'], '⚠️')} {s['name']}({s['code']})")
            lines.append(f"   现价{s['current_price']} | 盈亏{s['profit_pct']:+.1f}%")
            lines.append(f"   {s['reason']} → {s['suggestion']}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if result.get("diagnosis"):
        lines.append(f"📈 诊断：{result['diagnosis']}")
    lines.append("⚠️ 仅为策略信号，不构成投资建议，最终操作请自行判断")
    now_full = now_bjt().strftime("%Y-%m-%d %H:%M:%S")
    vstate = result.get("validation_state", "ok")
    vtxt = {"ok": "✅正常", "switched": "⚠️已切换", "degraded": "⚠️部分异常"}.get(vstate, vstate)
    regime = result.get("regime", "range_bound")
    regime_txt = f"{regime}({REGIME_LABELS.get(regime, '')})"
    ds_name = {"eastmoney": "东财(主)", "akshare": "AkShare(备1)", "sina": "新浪(备2)", "none": "无"}.get(result.get("data_source", "eastmoney"), result.get("data_source", "eastmoney"))
    lines.append(f"📡 数据源：{ds_name} | 校验：{vtxt} | "
                 f"市场环境：{regime_txt} | "
                 f"扫描{result.get('scanned_count', 0)}只→过滤{result.get('passed_count', 0)}只→通过{result.get('resonance_count', 0)}只")
    lines.append(f"⏱ 触发时间：北京时间{now_full} | 扫描耗时{result.get('scan_elapsed', 0)}s | "
                 f"涨停{result.get('limit_up', 0)}家/跌停{result.get('limit_down', 0)}家 | "
                 f"过滤后{result.get('passed_count', 0)}只→共振通过{result.get('resonance_count', 0)}只")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MACD 多周期共振策略扫描器")
    parser.add_argument("--push", action="store_true", help="推送模式：标记已推送（冷却）")
    parser.add_argument("--max", type=int, default=2000, help="扫描股票上限")
    parser.add_argument("--source", choices=["auto", "eastmoney", "akshare", "sina"], default="auto",
                        help="数据源选择：auto自动(默认)/eastmoney强制主源/akshare备1/sina备2")
    args = parser.parse_args()

    # 交易时段窗口：盘前 9:15-9:30 + 盘中 9:30-11:30/13:00-15:00。
    # 本机任务计划程序/云端 cron 均在窗口内触发；TEST_MODE=true 可跳过（手动排查用）。
    if os.environ.get("TEST_MODE", "").lower() != "true":
        now = now_bjt()
        hm = now.hour * 100 + now.minute
        in_window = now.weekday() < 5 and (915 <= hm < 930 or is_trading_time(now))
        if not in_window:
            print(f"📌 非交易时段（北京时间 {now.strftime('%Y-%m-%d %H:%M:%S')}），跳过扫描。"
                  f"如需强制运行请设置 TEST_MODE=true")
            return

    scanner = Scanner()
    result = scanner.run(max_stocks=args.max, need_push=args.push, source=args.source)
    msg = build_message(result)
    print(msg)
    print("\n[SUMMARY]", result["summary"])

    if args.push:
        webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
        if webhook:
            import requests
            try:
                resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": msg}}, timeout=8)
                print(f"[PUSH] 飞书推送完成 HTTP {resp.status_code}")
            except Exception as e:
                print(f"[PUSH] 飞书推送失败: {e}")
        else:
            print("[PUSH] 未配置 FEISHU_WEBHOOK_URL，跳过推送")


if __name__ == "__main__":
    main()
