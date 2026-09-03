# -*- coding: utf-8 -*-
"""回测引擎（策略有效性验证基础）。

核心能力：
1. 历史数据回测：在过去N天模拟策略运行
2. 绩效指标计算：胜率、平均收益、最大回撤、夏普比率
3. 参数优化：网格搜索找出最优参数区间
4. 策略准入判断：是否满足上线标准

设计原则：
- 轻量级，能在GitHub Actions中快速运行
- 基于真实历史K线数据，不编造
- 输出可解释的回测报告
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta

from . import data_source as ds

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BacktestEngine:
    """轻量级回测引擎。"""

    # A股交易成本配置
    COMMISSION_RATE = 0.00025    # 佣金万2.5
    COMMISSION_MIN = 5.0         # 最低佣金5元
    STAMP_TAX_RATE = 0.001       # 印花税千1（卖出）
    SLIPPAGE_RATE = 0.001        # 滑点0.1%

    def __init__(self, enable_cost: bool = True):
        self.trades = []
        self.enable_cost = enable_cost

    def _calc_buy_cost(self, price: float, shares: int) -> Dict:
        """计算买入成本。"""
        if not self.enable_cost:
            return {"actual_price": price, "commission": 0, "total_cost": price * shares}
        actual_price = price * (1 + self.SLIPPAGE_RATE)
        commission = max(actual_price * shares * self.COMMISSION_RATE, self.COMMISSION_MIN)
        total_cost = actual_price * shares + commission
        return {"actual_price": round(actual_price, 3), "commission": round(commission, 2), "total_cost": round(total_cost, 2)}

    def _calc_sell_cost(self, price: float, shares: int) -> Dict:
        """计算卖出成本。"""
        if not self.enable_cost:
            return {"actual_price": price, "commission": 0, "stamp_tax": 0, "total_revenue": price * shares}
        actual_price = price * (1 - self.SLIPPAGE_RATE)
        commission = max(actual_price * shares * self.COMMISSION_RATE, self.COMMISSION_MIN)
        stamp_tax = actual_price * shares * self.STAMP_TAX_RATE
        total_revenue = actual_price * shares - commission - stamp_tax
        return {"actual_price": round(actual_price, 3), "commission": round(commission, 2),
                "stamp_tax": round(stamp_tax, 2), "total_revenue": round(total_revenue, 2)}

    def backtest_strategy(
        self,
        stock_code: str,
        strategy_func: Callable,
        days: int = 60,
        initial_capital: float = 10000.0,
    ) -> Dict[str, Any]:
        """回测单只股票的策略。

        Args:
            stock_code: 股票代码
            strategy_func: 策略函数，输入(history_data, current_index)返回(是否买入, 止损价, 止盈价)
            days: 回测天数
            initial_capital: 初始资金

        Returns:
            回测结果字典
        """
        df = ds.get_kline_daily(stock_code, count=days + 30)  # 多取30天作为预热
        if df.empty or len(df) < days:
            return {"status": "no_data", "code": stock_code, "message": "历史数据不足"}

        closes = df["close"].astype(float).values
        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        volumes = df["volume"].astype(float).values
        dates = df["date"].values if "date" in df.columns else list(range(len(df)))

        capital = initial_capital
        position = 0  # 持仓数量
        entry_price = 0
        entry_date = None
        trades = []

        # 从第30天开始（预热期）
        for i in range(30, len(df) - 1):
            # 构建历史数据（到当前为止）
            history = {
                "closes": closes[: i + 1],
                "highs": highs[: i + 1],
                "lows": lows[: i + 1],
                "volumes": volumes[: i + 1],
                "dates": dates[: i + 1],
            }

            current_price = closes[i]

            # 如果持仓中，检查止损止盈
            if position > 0:
                # 检查当日是否触发止损止盈
                if lows[i + 1] <= entry_price * 0.95:  # 止损-5%
                    signal_exit = entry_price * 0.95
                    sell_info = self._calc_sell_cost(signal_exit, position)
                    exit_price = sell_info["actual_price"]
                    pnl = sell_info["total_revenue"] - entry_price * position - entry_commission
                    capital += sell_info["total_revenue"]
                    trades.append({
                        "entry_date": str(entry_date),
                        "exit_date": str(dates[i + 1]),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "return_pct": round(pnl / (entry_price * position) * 100, 2),
                        "pnl": round(pnl, 2),
                        "reason": "stop_loss",
                        "buy_commission": entry_commission,
                        "sell_commission": sell_info["commission"],
                        "stamp_tax": sell_info["stamp_tax"],
                    })
                    position = 0
                    continue
                elif highs[i + 1] >= entry_price * 1.10:  # 止盈+10%
                    signal_exit = entry_price * 1.10
                    sell_info = self._calc_sell_cost(signal_exit, position)
                    exit_price = sell_info["actual_price"]
                    pnl = sell_info["total_revenue"] - entry_price * position - entry_commission
                    capital += sell_info["total_revenue"]
                    trades.append({
                        "entry_date": str(entry_date),
                        "exit_date": str(dates[i + 1]),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "return_pct": round(pnl / (entry_price * position) * 100, 2),
                        "pnl": round(pnl, 2),
                        "reason": "take_profit",
                        "buy_commission": entry_commission,
                        "sell_commission": sell_info["commission"],
                        "stamp_tax": sell_info["stamp_tax"],
                    })
                    position = 0
                    continue

            # 如果空仓，检查是否买入
            if position == 0:
                try:
                    signal = strategy_func(history, i)
                    if signal and signal.get("buy"):
                        # 用次日开盘价买入（简化用收盘价）
                        signal_price = closes[i + 1]
                        buy_info = self._calc_buy_cost(signal_price, int(capital * 0.3 / signal_price))
                        entry_price = buy_info["actual_price"]
                        position = int(capital * 0.3 / entry_price)  # 30%仓位
                        if position > 0:
                            buy_info = self._calc_buy_cost(signal_price, position)
                            entry_price = buy_info["actual_price"]
                            capital -= buy_info["total_cost"]
                            entry_date = dates[i + 1]
                            entry_commission = buy_info["commission"]
                except Exception:
                    continue

        # 最后平仓
        if position > 0:
            sell_info = self._calc_sell_cost(closes[-1], position)
            exit_price = sell_info["actual_price"]
            pnl = sell_info["total_revenue"] - entry_price * position - entry_commission
            capital += sell_info["total_revenue"]
            trades.append({
                "entry_date": str(entry_date),
                "exit_date": str(dates[-1]),
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "return_pct": round(pnl / (entry_price * position) * 100, 2),
                "pnl": round(pnl, 2),
                "reason": "end",
                "buy_commission": entry_commission,
                "sell_commission": sell_info["commission"],
                "stamp_tax": sell_info["stamp_tax"],
            })

        # 计算绩效指标
        return self._calculate_metrics(trades, initial_capital, capital, stock_code)

    def _calculate_metrics(
        self,
        trades: List[Dict],
        initial_capital: float,
        final_capital: float,
        stock_code: str,
    ) -> Dict[str, Any]:
        """计算回测绩效指标。"""
        if not trades:
            return {
                "status": "no_trades",
                "code": stock_code,
                "total_trades": 0,
                "message": "回测期内无交易信号",
            }

        returns = [t["return_pct"] for t in trades]
        win_trades = [r for r in returns if r > 0]
        loss_trades = [r for r in returns if r <= 0]

        win_rate = len(win_trades) / len(trades) * 100
        avg_return = sum(returns) / len(returns)
        max_return = max(returns)
        min_return = min(returns)

        # 最大回撤（基于交易序列）
        cumulative = 0
        peak = 0
        max_drawdown = 0
        for r in returns:
            cumulative += r
            peak = max(peak, cumulative)
            drawdown = peak - cumulative
            max_drawdown = max(max_drawdown, drawdown)

        # 夏普比率（简化版）
        import statistics
        if len(returns) > 1:
            std = statistics.stdev(returns)
            sharpe = (avg_return / std) * (252 ** 0.5) if std > 0 else 0
        else:
            sharpe = 0

        total_return = (final_capital - initial_capital) / initial_capital * 100

        return {
            "status": "ok",
            "code": stock_code,
            "total_trades": len(trades),
            "win_trades": len(win_trades),
            "loss_trades": len(loss_trades),
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "max_return_pct": round(max_return, 2),
            "min_return_pct": round(min_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_return_pct": round(total_return, 2),
            "initial_capital": initial_capital,
            "final_capital": round(final_capital, 2),
            "total_commission": round(sum(t.get("buy_commission", 0) + t.get("sell_commission", 0) for t in trades), 2),
            "total_stamp_tax": round(sum(t.get("stamp_tax", 0) for t in trades), 2),
            "total_trading_cost": round(sum(t.get("buy_commission", 0) + t.get("sell_commission", 0) + t.get("stamp_tax", 0) for t in trades), 2),
            "cost_enabled": self.enable_cost,
            "trades": trades,
        }

    def batch_backtest(
        self,
        stock_codes: List[str],
        strategy_func: Callable,
        days: int = 60,
    ) -> Dict[str, Any]:
        """批量回测多只股票。"""
        results = []
        for code in stock_codes:
            try:
                result = self.backtest_strategy(code, strategy_func, days)
                results.append(result)
                time.sleep(0.1)  # 避免请求过快
            except Exception as e:
                results.append({"status": "error", "code": code, "message": str(e)})

        # 汇总
        valid_results = [r for r in results if r["status"] == "ok"]
        if not valid_results:
            return {"status": "no_valid", "total": len(results), "valid": 0, "results": results}

        avg_win_rate = sum(r["win_rate"] for r in valid_results) / len(valid_results)
        avg_return = sum(r["avg_return_pct"] for r in valid_results) / len(valid_results)
        avg_drawdown = sum(r["max_drawdown_pct"] for r in valid_results) / len(valid_results)
        total_trades = sum(r["total_trades"] for r in valid_results)

        return {
            "status": "ok",
            "total_stocks": len(results),
            "valid_stocks": len(valid_results),
            "total_trades": total_trades,
            "avg_win_rate": round(avg_win_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "avg_max_drawdown_pct": round(avg_drawdown, 2),
            "results": valid_results,
        }

    def check_admission_criteria(self, backtest_result: Dict) -> Dict[str, Any]:
        """检查策略是否满足准入标准。

        准入标准：
        - 胜率 > 50%
        - 平均收益 > 3%
        - 最大回撤 < 10%
        - 交易次数 > 5（有统计意义）
        """
        if backtest_result.get("status") != "ok":
            return {"passed": False, "reason": "回测失败或无数据", "details": backtest_result}

        checks = {
            "win_rate": {
                "value": backtest_result.get("avg_win_rate", backtest_result.get("win_rate", 0)),
                "threshold": 50,
                "passed": backtest_result.get("avg_win_rate", backtest_result.get("win_rate", 0)) > 50,
            },
            "avg_return": {
                "value": backtest_result.get("avg_return_pct", 0),
                "threshold": 3,
                "passed": backtest_result.get("avg_return_pct", 0) > 3,
            },
            "max_drawdown": {
                "value": backtest_result.get("avg_max_drawdown_pct", backtest_result.get("max_drawdown_pct", 99)),
                "threshold": 10,
                "passed": backtest_result.get("avg_max_drawdown_pct", backtest_result.get("max_drawdown_pct", 99)) < 10,
            },
            "trade_count": {
                "value": backtest_result.get("total_trades", 0),
                "threshold": 5,
                "passed": backtest_result.get("total_trades", 0) > 5,
            },
        }

        all_passed = all(c["passed"] for c in checks.values())
        failed = [k for k, v in checks.items() if not v["passed"]]

        return {
            "passed": all_passed,
            "checks": checks,
            "failed_items": failed,
            "verdict": "通过准入" if all_passed else f"未通过（{', '.join(failed)}）",
        }


# ============================================================
# 预设策略函数（用于回测）
# ============================================================

def macd_resonance_strategy(history: Dict, idx: int) -> Dict:
    """MACD多周期共振策略（简化版，用于回测）。"""
    closes = history["closes"]
    if len(closes) < 26:
        return {"buy": False}

    # 计算MACD（简化版）
    import numpy as np
    close_arr = np.array(closes)
    ema12 = _ema(close_arr, 12)
    ema26 = _ema(close_arr, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    macd = (dif - dea) * 2

    # 金叉条件：DIF上穿DEA
    if len(dif) >= 2 and dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
        # 均线多头
        ma5 = close_arr[-5:].mean()
        ma10 = close_arr[-10:].mean()
        ma20 = close_arr[-20:].mean()
        if ma5 > ma10 > ma20:
            return {"buy": True, "stop_loss": 0.95, "take_profit": 1.10}

    return {"buy": False}


def oversold_rebound_strategy(history: Dict, idx: int) -> Dict:
    """超跌反弹策略（简化版，用于回测）。"""
    closes = history["closes"]
    volumes = history["volumes"]
    if len(closes) < 25:
        return {"buy": False}

    # 20日跌幅
    drop_20d = (closes[-21] - closes[-1]) / closes[-21] * 100
    if drop_20d < 25:
        return {"buy": False}

    # 当日涨幅
    today_gain = (closes[-1] - closes[-2]) / closes[-2] * 100
    if today_gain < 4:
        return {"buy": False}

    # 放量
    if len(volumes) >= 6:
        avg_vol_5d = sum(volumes[-6:-1]) / 5
        if avg_vol_5d > 0 and volumes[-1] / avg_vol_5d < 1.8:
            return {"buy": False}

    return {"buy": True, "stop_loss": 0.95, "take_profit": 1.10}


def breakout_strategy(history: Dict, idx: int) -> Dict:
    """趋势突破策略（简化版，用于回测）。"""
    closes = history["closes"]
    volumes = history["volumes"]
    if len(closes) < 25:
        return {"buy": False}

    # 突破20日新高
    recent_high = max(closes[-21:-1])  # 前20日最高（不含当日）
    if closes[-1] <= recent_high:
        return {"buy": False}

    # 放量
    if len(volumes) >= 6:
        avg_vol_5d = sum(volumes[-6:-1]) / 5
        if avg_vol_5d > 0 and volumes[-1] / avg_vol_5d < 1.5:
            return {"buy": False}

    # 均线多头
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    if ma5 <= ma10:
        return {"buy": False}

    return {"buy": True, "stop_loss": 0.96, "take_profit": 1.08}


def _ema(data, period):
    """计算EMA。"""
    import numpy as np
    alpha = 2 / (period + 1)
    ema = np.zeros_like(data)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
    return ema


def build_backtest_report(result: Dict, strategy_name: str) -> str:
    """生成回测报告。"""
    lines = [
        f"📊 策略回测报告：{strategy_name}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if result.get("status") == "no_trades":
        lines.append("❌ 回测期内无交易信号，策略可能过于严格")
        return "\n".join(lines)

    if result.get("status") == "no_valid":
        lines.append("❌ 无有效回测结果")
        return "\n".join(lines)

    lines.append(f"📈 回测股票数：{result.get('valid_stocks', result.get('code', 'N/A'))}")
    lines.append(f"🔄 总交易次数：{result.get('total_trades', 0)}")
    lines.append("")
    lines.append("【绩效指标】")
    lines.append(f"  胜率：{result.get('avg_win_rate', result.get('win_rate', 0))}%")
    lines.append(f"  平均收益：{result.get('avg_return_pct', result.get('avg_return_pct', 0))}%")
    lines.append(f"  最大回撤：{result.get('avg_max_drawdown_pct', result.get('max_drawdown_pct', 0))}%")
    lines.append(f"  最佳单笔：{result.get('max_return_pct', 0)}%")
    lines.append(f"  最差单笔：{result.get('min_return_pct', 0)}%")
    if result.get("cost_enabled"):
        lines.append(f"  总交易成本：佣金{result.get('total_commission', 0)}元 + 印花税{result.get('total_stamp_tax', 0)}元 = {result.get('total_trading_cost', 0)}元")
    lines.append("")

    # 准入检查
    engine = BacktestEngine()
    admission = engine.check_admission_criteria(result)
    lines.append("【准入检查】")
    for key, check in admission.get("checks", {}).items():
        status = "✅" if check["passed"] else "❌"
        lines.append(f"  {status} {key}: {check['value']} (阈值{check['threshold']})")
    lines.append("")
    lines.append(f"🎯 结论：{admission.get('verdict', '未知')}")

    return "\n".join(lines)
