# -*- coding: utf-8 -*-
"""回测模块（日线级别简化模拟）。

说明：分钟级数据难以回溯，回测采用日线级等价信号：
- 入场：日线 DIF>0 且当日金叉（零轴上方金叉）
- 离场：日线死叉 / 浮盈≥15% 清仓 / 浮亏≤-5% 止损

输出：总收益率、胜率、最大回撤、平均持仓天数、交易次数。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd

from . import data_source as ds
from .config import RISK, ZERO_AXIS_EPS
from .macd_indicator import calc_macd, is_death_cross, is_golden_cross


def backtest_single(code: str, days: int = 365) -> Dict:
    """对单只股票执行日线级回测。"""
    df = ds.get_kline_daily(code, count=days + 60)
    if df.empty or len(df) < 60:
        return {"code": code, "error": "数据不足", "trades": [], "stats": {}}

    df = calc_macd(df)
    trades: List[Dict] = []
    entry_idx = None
    entry_price = 0.0
    peak = 0.0

    for i in range(60, len(df)):
        dif = df["dif"].iloc[i]
        dea = df["dea"].iloc[i]
        close = float(df["close"].iloc[i])

        if entry_idx is None:
            # 入场：零轴附近金叉（与信号引擎日线门控一致：DIF > -eps）
            if is_golden_cross(df["dif"].iloc[: i + 1], df["dea"].iloc[: i + 1]) and dif > -ZERO_AXIS_EPS:
                entry_idx = i
                entry_price = close
                peak = close
        else:
            peak = max(peak, close)
            profit = (close - entry_price) / entry_price
            exit_reason = None

            # 离场条件
            if is_death_cross(df["dif"].iloc[: i + 1], df["dea"].iloc[: i + 1]):
                exit_reason = "死叉离场"
            elif profit >= RISK["take_profit_2_pct"]:
                exit_reason = f"止盈{profit * 100:.1f}%"
            elif profit <= -RISK["stop_loss_pct"]:
                exit_reason = f"止损{profit * 100:.1f}%"

            if exit_reason:
                trades.append({
                    "entry_date": str(df["datetime"].iloc[entry_idx].date()),
                    "exit_date": str(df["datetime"].iloc[i].date()),
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(close, 2),
                    "profit_pct": round(profit * 100, 2),
                    "days": int((df["datetime"].iloc[i] - df["datetime"].iloc[entry_idx]).days),
                    "reason": exit_reason,
                })
                entry_idx = None

    stats = _calc_stats(trades)
    return {"code": code, "trades": trades, "stats": stats}


def _calc_stats(trades: List[Dict]) -> Dict:
    if not trades:
        return {"total_trades": 0, "win_rate": 0, "avg_profit": 0, "total_return": 0,
                "max_drawdown": 0, "avg_hold_days": 0}
    profits = [t["profit_pct"] for t in trades]
    wins = [p for p in profits if p > 0]
    total_return = 1.0
    peak_equity = 1.0
    max_dd = 0.0
    for p in profits:
        total_return *= (1 + p / 100)
        peak_equity = max(peak_equity, total_return)
        dd = (total_return - peak_equity) / peak_equity
        max_dd = min(max_dd, dd)
    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "avg_profit": round(sum(profits) / len(trades), 2),
        "total_return": round((total_return - 1) * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "avg_hold_days": round(sum(t["days"] for t in trades) / len(trades), 1),
    }


def run_backtest(codes: List[str], days: int = 365) -> Dict:
    results = [backtest_single(c, days) for c in codes]
    ok = [r for r in results if "error" not in r]
    agg = {
        "total_trades": sum(r["stats"].get("total_trades", 0) for r in ok),
        "win_rate": round(sum(r["stats"].get("win_rate", 0) for r in ok) / len(ok), 2) if ok else 0,
        "total_return": round(sum(r["stats"].get("total_return", 0) for r in ok) / len(ok), 2) if ok else 0,
        "max_drawdown": min((r["stats"].get("max_drawdown", 0) for r in ok), default=0),
    }
    return {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "days": days, "stocks": results, "aggregate": agg}


def main():
    parser = argparse.ArgumentParser(description="MACD 多周期共振策略回测")
    parser.add_argument("--codes", required=True, help="股票代码，逗号分隔，如 600519,000001")
    parser.add_argument("--days", type=int, default=365, help="回测天数")
    args = parser.parse_args()

    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    result = run_backtest(codes, args.days)

    agg = result["aggregate"]
    print("=" * 50)
    print(f"回测结果（近{args.days}天，{len(codes)}只）")
    print(f"总交易次数：{agg['total_trades']}  |  平均胜率：{agg['win_rate']}%")
    print(f"平均累计收益：{agg['total_return']}%  |  最大回撤：{agg['max_drawdown']}%")
    print("=" * 50)
    for r in result["stocks"]:
        if "error" in r:
            print(f"{r['code']}: {r['error']}")
        else:
            s = r["stats"]
            print(f"{r['code']}: {s['total_trades']}笔 胜率{s['win_rate']}% 收益{s['total_return']}% 最大回撤{s['max_drawdown']}%")

    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports", "output"), exist_ok=True)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "reports", "output", f"backtest_macd_resonance_{datetime.now().strftime('%Y%m%d')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"结果已保存：{out}")


if __name__ == "__main__":
    main()
