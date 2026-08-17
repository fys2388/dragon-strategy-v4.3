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
from .trading_calendar import BJT, now_bjt
from .signal_engine import SignalEngine, SignalType

LOCK = threading.Lock()

# ============================================================
# 日志
# ============================================================
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
HISTORY_FILE = os.path.join(os.path.dirname(LOG_DIR), "data", "strategy_history.jsonl")


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
    def run(self, max_stocks: int = 2000, need_push: bool = False) -> Dict:
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

        # 0.5 涨跌停家数（诊断用，异常兜底为 0）
        try:
            result["limit_up"], result["limit_down"] = ds.get_limit_up_down_count()
            LOG.info(f"涨跌停家数：涨停{result['limit_up']}家 / 跌停{result['limit_down']}家")
        except Exception as e:
            LOG.warning(f"涨跌停统计异常: {e}")

        # 1. 大盘门控
        score, desc, can_open = get_market_score()
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

        # 2. 标的池 + 初筛
        all_stocks = ds.get_mainboard_stocks(limit=max_stocks)
        if not all_stocks:
            result["summary"] = "获取标的池失败"
            LOG.warning(result["summary"])
            result["scan_elapsed"] = round(time.time() - t0, 1)
            self._append_history(result)
            return result
        candidates = [s for s in all_stocks if self._quick_filter(s)]
        LOG.info(f"标的池 {len(all_stocks)} 只 → 初筛 {len(candidates)} 只")

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
    lines.append(f"⏱ 触发时间：北京时间{now_full} | 扫描耗时{result.get('scan_elapsed', 0)}s | "
                 f"涨停{result.get('limit_up', 0)}家/跌停{result.get('limit_down', 0)}家 | "
                 f"过滤后{result.get('passed_count', 0)}只→共振通过{result.get('resonance_count', 0)}只")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MACD 多周期共振策略扫描器")
    parser.add_argument("--push", action="store_true", help="推送模式：标记已推送（冷却）")
    parser.add_argument("--max", type=int, default=2000, help="扫描股票上限")
    args = parser.parse_args()

    scanner = Scanner()
    result = scanner.run(max_stocks=args.max, need_push=args.push)
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
