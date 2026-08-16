# -*- coding: utf-8 -*-
"""主扫描入口模块。

流程：大盘门控 → 标的池初筛 → 硬过滤 → 多周期信号分析 → 去重冷却 → 输出。
并发控制：ThreadPoolExecutor(max_workers=8) + 单只 0.3s 间隔。
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

from . import data_source as ds
from .config import RISK, SIGNAL
from .filters import pass_hard_filters
from .market_gate import get_market_score
from .signal_engine import SignalEngine, SignalType

LOCK = threading.Lock()


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
        hours = (datetime.now() - last_ts).total_seconds() / 3600
        return hours < SIGNAL["cooldown_hours"]

    def _mark_pushed(self, code: str):
        self.cache.setdefault("pushed", {})[code] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._save_cache()

    # ----------------------------------------------------------
    # 快速初筛（价格/市值/名称，不拉K线）
    # ----------------------------------------------------------
    def _quick_filter(self, stock: dict) -> bool:
        name = str(stock.get("name", ""))
        if "ST" in name.upper() or "退" in name:
            return False
        price = float(stock.get("price", 0) or 0)
        cap = float(stock.get("float_cap_yi", 0) or 0)
        if price < 3.0 or price > 35.0:      # 略宽于硬过滤，交给硬过滤精确判断
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
              entries: [SignalResult...], avoids: [...], errors: [...],
              summary: ...
            }
        """
        result = {
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "market_score": 0.0,
            "market_desc": "",
            "can_open": False,
            "entries": [],
            "avoids": 0,
            "errors": [],
            "summary": "",
        }

        # 1. 大盘门控
        score, desc, can_open = get_market_score()
        result["market_score"] = score
        result["market_desc"] = desc
        result["can_open"] = can_open
        if not can_open:
            result["summary"] = f"大盘评分 {score:.1f} 分 < 4，仅允许平仓/空仓，禁止新开多。"
            return result

        # 2. 标的池 + 初筛
        all_stocks = ds.get_mainboard_stocks(limit=max_stocks)
        if not all_stocks:
            result["summary"] = "获取标的池失败"
            return result
        candidates = [s for s in all_stocks if self._quick_filter(s)]
        result["summary"] = f"初筛 {len(all_stocks)} → {len(candidates)} 只"

        # 3. 硬过滤（并发补齐 20 日均额/振幅）
        with ThreadPoolExecutor(max_workers=8) as pool:
            enriched = list(pool.map(self._enrich_hard_metrics, candidates))
        passed = []
        for s in enriched:
            ok, reason = pass_hard_filters(s)
            if ok:
                passed.append(s)
            else:
                result["errors"].append(reason)  # 保留为日志

        # 4. 多周期信号分析（并发 + 0.3s 间隔限速）
        entries: List[Dict] = []
        avoid_count = 0
        delay = threading.Event()

        def analyze(stock: dict):
            delay.wait(0.3)
            return self.engine.analyze_stock(stock["code"], stock["name"], stock["price"])

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(analyze, s) for s in passed]
            for fut in as_completed(futs):
                try:
                    sig = fut.result()
                except Exception as e:  # 单只异常不影响整体
                    result["errors"].append(f"analyze error: {e}")
                    continue
                if sig.signal_type == SignalType.LONG_ENTRY:
                    entries.append(sig.__dict__)
                elif sig.signal_type == SignalType.AVOID:
                    avoid_count += 1

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
        result["summary"] += f" → 硬过滤 {len(passed)} 只 → 共振信号 {len(entries)} 只 → 推荐 {len(final)} 只"
        return result


def build_message(result: Dict) -> str:
    """将扫描结果格式化为飞书消息。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
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
        # 1 万本金仓位建议
        single = RISK["total_capital"] * RISK["position_pct"]
        lines.append(f"💼 仓位建议（本金{RISK['total_capital']:.0f}元）")
        lines.append(f"  单票≤30%（{single:.0f}元），最多{RISK['max_positions']}只")
        lines.append(f"  止盈：+{RISK['take_profit_1_pct'] * 100:.0f}%减半 / +{RISK['take_profit_2_pct'] * 100:.0f}%清仓 | 止损：-{RISK['stop_loss_pct'] * 100:.0f}%")
    else:
        lines.append("  当前无符合多周期共振的标的，继续观望")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ 仅为策略信号，不构成投资建议，最终操作请自行判断")
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

    # 推送模式：调用飞书
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
