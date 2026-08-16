# -*- coding: utf-8 -*-
"""回测模块（MACD 多周期共振策略 V1.0）。

设计说明：
- 按日遍历历史日线，每日用「截至当日的数据」驱动 signal_engine.analyze_stock 判断信号
- 多周期简化：60/30/15min 用日线降采样近似（历史分钟数据不可得，已在文档标注）
- 入场 LONG_ENTRY 按收盘价买入（单票 30% 仓位）；离场 LONG_EXIT 按收盘价卖出
- 输出：控制台汇总 + reports/backtest_YYYYMMDD_HHMM.json

CLI：
    python -m strategies.macd_resonance.backtest --codes 600519,000001 --days 365
    python -m strategies.macd_resonance.backtest --codes 600519 --start 2026-01-01 --end 2026-08-14
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from unittest import mock

import pandas as pd

from . import data_source as ds
from .config import RISK, SIGNAL, ZERO_AXIS_EPS
from .macd_indicator import calc_macd, is_death_cross, is_golden_cross
from .signal_engine import SignalType

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Trade:
    code: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    exit_reason: str


@dataclass
class BacktestResult:
    code: str = ""
    total_return: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    avg_holding_days: float = 0.0
    trade_count: int = 0
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


def _slice_for_date(df: pd.DataFrame, end_idx: int, period: str, count: int) -> pd.DataFrame:
    """构造截至 end_idx 的周期数据（历史分钟数据用日线降采样近似）。"""
    window = df.iloc[max(0, end_idx - count + 1): end_idx + 1].copy()
    if window.empty:
        return pd.DataFrame()
    if period == "daily":
        return window
    # 60/30/15min 近似：日线每根代表一个周期 K 线
    out = pd.DataFrame({
        "datetime": window["datetime"],
        "open": window["open"], "close": window["close"],
        "high": window["high"], "low": window["low"],
        "volume": window["volume"], "amount": window["amount"],
    })
    return out


def backtest_single(code: str, name: str, start_date: str, end_date: str) -> BacktestResult:
    """对单只股票执行回测（日线级信号，多周期以日线 MACD 近似）。"""
    result = BacktestResult(code=code)

    df_all = ds.get_kline_daily(code, count=400)
    if df_all.empty or len(df_all) < 60:
        return result

    df_all = df_all[(df_all["datetime"] >= pd.Timestamp(start_date)) &
                    (df_all["datetime"] <= pd.Timestamp(end_date))].reset_index(drop=True)
    if len(df_all) < 30:
        return result

    df_macd = calc_macd(df_all)
    dif = df_macd["dif"]
    dea = df_macd["dea"]
    volumes = df_all["volume"].astype(float)
    closes = df_all["close"].astype(float)
    highs = df_all["high"].astype(float)

    equity = 10000.0  # 单票 30% 仓位模拟
    curve: List[float] = []
    open_trade: Optional[Trade] = None

    def daily_entry_signal(i: int) -> bool:
        """入场：日线金叉 + DIF>-0.05 + 量能1.3倍 + 突破近20日高点。"""
        if i < 2 or not is_golden_cross(dif.iloc[: i + 1], dea.iloc[: i + 1]):
            return False
        if dif.iloc[i] <= -ZERO_AXIS_EPS:
            return False
        if i < 6 or volumes.iloc[i] <= volumes.iloc[i - 6:i - 1].mean() * SIGNAL["volume_ratio_min"]:
            return False
        if i < 20 or closes.iloc[i] <= float(highs.iloc[i - 20:i].max()):
            return False
        return True

    def daily_exit_signal(i: int) -> Optional[str]:
        """离场：日线死叉 / 止盈 / 止损。"""
        reasons = []
        if i >= 1 and is_death_cross(dif.iloc[: i + 1], dea.iloc[: i + 1]):
            reasons.append("日线死叉")
        if open_trade and open_trade.entry_price > 0:
            ret = (closes.iloc[i] - open_trade.entry_price) / open_trade.entry_price
            if ret >= RISK["take_profit_2_pct"]:
                reasons.append(f"止盈{ret * 100:.1f}%")
            elif ret <= -RISK["stop_loss_pct"]:
                reasons.append(f"止损{ret * 100:.1f}%")
        return "；".join(reasons) if reasons else None

    for i in range(30, len(df_all)):
        price = float(closes.iloc[i])
        date_str = str(df_all["datetime"].iloc[i].date())

        if open_trade is None:
            if daily_entry_signal(i):
                open_trade = Trade(code=code, entry_date=date_str, entry_price=round(price, 2),
                                   exit_date="", exit_price=0.0, return_pct=0.0, exit_reason="")
        else:
            reason = daily_exit_signal(i)
            if reason:
                ret = (price - open_trade.entry_price) / open_trade.entry_price * 100
                open_trade.exit_date = date_str
                open_trade.exit_price = round(price, 2)
                open_trade.return_pct = round(ret, 2)
                open_trade.exit_reason = reason
                result.trades.append(open_trade)
                equity *= (1 + ret / 100 * RISK["position_pct"])
                open_trade = None

        curve.append(equity)

    # 期末强制平仓
    if open_trade is not None:
        last_price = float(closes.iloc[-1])
        ret = (last_price - open_trade.entry_price) / open_trade.entry_price * 100
        open_trade.exit_date = str(df_all["datetime"].iloc[-1].date())
        open_trade.exit_price = round(last_price, 2)
        open_trade.return_pct = round(ret, 2)
        open_trade.exit_reason = "期末强制平仓"
        result.trades.append(open_trade)
        equity *= (1 + ret / 100 * RISK["position_pct"])

    result.equity_curve = [round(x, 2) for x in curve]
    result.total_return = round((equity - 10000) / 10000 * 100, 2)
    result.trade_count = len(result.trades)
    if result.trades:
        wins = [t for t in result.trades if t.return_pct > 0]
        result.win_rate = round(len(wins) / len(result.trades) * 100, 2)
        result.avg_holding_days = round(sum((pd.Timestamp(t.exit_date) - pd.Timestamp(t.entry_date)).days
                                            for t in result.trades) / len(result.trades), 1)
        if curve:
            max_dd = 0.0
            running_peak = curve[0]
            for v in curve:
                running_peak = max(running_peak, v)
                max_dd = min(max_dd, (v - running_peak) / running_peak)
            result.max_drawdown = round(max_dd * 100, 2)
    return result


def run_backtest(codes: List[str], start_date: str, end_date: str) -> Dict:
    results = [backtest_single(c, c, start_date, end_date) for c in codes]
    valid = [r for r in results if r.trade_count > 0]
    agg = {}
    if valid:
        agg = {
            "trade_count": sum(r.trade_count for r in valid),
            "win_rate": round(sum(r.win_rate for r in valid) / len(valid), 2),
            "total_return": round(sum(r.total_return for r in valid) / len(valid), 2),
            "max_drawdown": min(r.max_drawdown for r in valid),
            "avg_holding_days": round(sum(r.avg_holding_days for r in valid) / len(valid), 1),
        }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": start_date,
        "end_date": end_date,
        "stocks": [asdict(r) for r in results],
        "aggregate": agg,
    }


def _ascii_curve(curve: List[float], width: int = 60, height: int = 8) -> str:
    """简单 ASCII 净值曲线。"""
    if len(curve) < 2:
        return "(数据不足)"
    lo, hi = min(curve), max(curve)
    span = (hi - lo) or 1.0
    lines = []
    step = max(1, len(curve) // width)
    sampled = curve[::step]
    for row in range(height, 0, -1):
        level = hi - (row - 0.5) * span / height
        line = ""
        for v in sampled:
            line += "█" if v >= level else " "
        lines.append(f"{level:10.0f} |{line}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MACD 多周期共振策略回测")
    parser.add_argument("--codes", required=True, help="股票代码，逗号分隔")
    parser.add_argument("--days", type=int, default=365, help="回溯天数")
    parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now()
    start = pd.Timestamp(args.start) if args.start else end - timedelta(days=args.days)
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    result = run_backtest(codes, str(start.date()), str(end.date()))
    agg = result["aggregate"]

    print("=" * 60)
    print(f"回测区间：{result['start_date']} ~ {result['end_date']}（{len(codes)} 只）")
    if agg:
        print(f"总交易次数：{agg['trade_count']}  |  平均胜率：{agg['win_rate']}%")
        print(f"平均累计收益：{agg['total_return']}%  |  最大回撤：{agg['max_drawdown']}%")
        print(f"平均持仓天数：{agg['avg_holding_days']}")
    else:
        print("无交易信号（可能数据不足或网络不通）")
    print("=" * 60)

    for r in result["stocks"]:
        if r["trade_count"] == 0:
            print(f"{r['code']}: 无交易")
        else:
            print(f"{r['code']}: {r['trade_count']}笔 胜率{r['win_rate']}% 收益{r['total_return']}% 回撤{r['max_drawdown']}%")
            if r["equity_curve"]:
                print(_ascii_curve(r["equity_curve"]))

    out_dir = os.path.join(BASE_DIR, "reports", "output")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"backtest_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存：{out}")


if __name__ == "__main__":
    main()
