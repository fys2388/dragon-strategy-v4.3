"""
回测引擎

向量化回测，验证信号有效性。
计算：胜率、盈亏比、最大回撤、夏普比率、年化收益。
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime

from config.settings import SIGNAL_PARAMS, CACHE_DIR
from src.data.source import data_source
from src.data.cache import cache

logger = logging.getLogger(__name__)


class BacktestEngine:
    """向量化回测引擎"""

    def __init__(self, initial_capital: float = 500000):
        self.initial_capital = initial_capital
        self.commission_rate = 0.0003  # 佣金 0.03%
        self.stamp_tax = 0.001       # 印花税 0.1%（卖出）
        self.slippage = 0.001         # 滑点 0.1%

    def run(self, signals: List[Dict], trading_days: int = 20) -> Dict:
        """
        回测信号组

        Args:
            signals: 信号列表（包含 entry_price, stop_loss, target_1, target_2）
            trading_days: 持仓天数

        Returns:
            回测结果 dict
        """
        if not signals:
            return {"error": "无信号可回测"}

        results = []
        for sig in signals:
            code = sig["code"]
            try:
                # 获取信号日之后的 K 线
                kline = self._get_kline_after_signal(code, sig)
                if kline is None or len(kline) < 3:
                    continue

                # 模拟交易
                trade_result = self._simulate_trade(sig, kline, trading_days)
                if trade_result:
                    results.append(trade_result)

            except Exception as e:
                logger.debug(f"回测异常 {code}: {e}")
                continue

        if not results:
            return {"error": "无有效回测结果", "signals_tested": len(signals)}

        return self._calculate_metrics(results)

    def _get_kline_after_signal(self, code: str, signal: Dict) -> Optional[pd.DataFrame]:
        """获取信号日之后的 K 线"""
        cache_key = f"kline_bt_{code}"
        cached = cache.get(cache_key, ttl=3600)
        if cached is not None:
            return cached

        kline = data_source.get_kline(code, days=250)
        if kline is None or kline.empty:
            return None

        cache.set(cache_key, kline)
        return kline

    def _simulate_trade(self, sig: Dict, kline: pd.DataFrame, holding_days: int) -> Optional[Dict]:
        """
        模拟单笔交易

        逻辑：
        1. 以 entry_price 买入
        2. 每天检查：止损/止盈/时间止损/移动止损
        3. 返回交易结果
        """
        entry_price = sig["entry_price"]
        stop_loss = sig["stop_loss"]
        target_1 = sig["target_1"]
        target_2 = sig["target_2"]

        # 实际买入价（含滑点）
        actual_entry = entry_price * (1 + self.slippage)

        # 确定起始位置（信号日）
        # 用最近的数据模拟
        start_idx = max(0, len(kline) - holding_days - 1)
        trade_kline = kline.iloc[start_idx:].reset_index(drop=True)

        position = 1  # 持仓 1 股（比例计算）
        realized_pnl = 0
        exit_reason = "time_stop"
        exit_price = actual_entry
        peak_price = actual_entry

        for i in range(len(trade_kline)):
            row = trade_kline.iloc[i]
            high = row["high"]
            low = row["low"]
            close = row["close"]

            # 更新最高价
            peak_price = max(peak_price, high)

            # 检查止损
            if low <= stop_loss:
                exit_price = stop_loss * (1 - self.slippage)
                exit_reason = "stop_loss"
                break

            # 检查止盈1
            if high >= target_1:
                exit_price = target_1 * (1 - self.slippage)
                exit_reason = "take_profit_1"
                # 止盈1后减半，剩余继续持有
                remaining_position = 0.5
                # 继续检查剩余仓位
                for j in range(i + 1, len(trade_kline)):
                    row2 = trade_kline.iloc[j]
                    if row2["low"] <= stop_loss:
                        exit_price = stop_loss * (1 - self.slippage)
                        exit_reason = "stop_loss_after_tp1"
                        break
                    if row2["high"] >= target_2:
                        exit_price = target_2 * (1 - self.slippage)
                        exit_reason = "take_profit_2"
                        break
                break

            # 检查止盈2
            if high >= target_2:
                exit_price = target_2 * (1 - self.slippage)
                exit_reason = "take_profit_2"
                break

            # 移动止损（跌破10日线）
            if "ma10" in trade_kline.columns:
                ma10 = trade_kline.iloc[i].get("ma10", 0)
                if ma10 > 0 and close < ma10:
                    exit_price = close * (1 - self.slippage)
                    exit_reason = "trailing_stop"
                    break

            # 时间止损
            if i >= holding_days - 1:
                exit_price = close * (1 - self.slippage)
                exit_reason = "time_stop"
                break

        # 计算盈亏
        gross_pnl = (exit_price - actual_entry) / actual_entry
        commission = actual_entry * self.commission_rate + exit_price * self.commission_rate
        tax = exit_price * self.stamp_tax if exit_price > actual_entry else 0
        net_pnl = gross_pnl - (commission + tax) / actual_entry

        return {
            "code": sig["code"],
            "name": sig["name"],
            "signal_type": sig["signal_type"],
            "entry_price": actual_entry,
            "exit_price": exit_price,
            "gross_pnl_pct": round(gross_pnl * 100, 2),
            "net_pnl_pct": round(net_pnl * 100, 2),
            "exit_reason": exit_reason,
            "holding_days": i + 1 if 'i' in dir() else holding_days,
            "peak_price": peak_price,
            "mae": round((min(trade_kline["low"].iloc[:i+1]) - actual_entry) / actual_entry * 100, 2) if i > 0 else 0,
            "mfe": round((peak_price - actual_entry) / actual_entry * 100, 2),
        }

    def _calculate_metrics(self, results: List[Dict]) -> Dict:
        """计算回测指标"""
        pnls = [r["net_pnl_pct"] for r in results]
        gross_pnls = [r["gross_pnl_pct"] for r in results]

        total_trades = len(results)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        win_rate = wins / total_trades if total_trades > 0 else 0

        avg_win = np.mean([p for p in pnls if p > 0]) if wins > 0 else 0
        avg_loss = np.mean([p for p in pnls if p < 0]) if losses > 0 else 0
        profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # 最大回撤（按信号顺序模拟）
        equity = self.initial_capital
        equity_curve = [equity]
        for r in results:
            equity *= (1 + r["net_pnl_pct"] / 100)
            equity_curve.append(equity)

        max_drawdown = 0
        peak = equity_curve[0]
        for val in equity_curve:
            peak = max(peak, val)
            drawdown = (peak - val) / peak
            max_drawdown = max(max_drawdown, drawdown)

        # 夏普比率（简化）
        returns = [r["net_pnl_pct"] / 100 for r in results]
        if len(returns) > 1:
            sharpe = np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(250 / max(total_trades, 1))
        else:
            sharpe = 0

        # 按出场原因统计
        exit_reasons = {}
        for r in results:
            reason = r["exit_reason"]
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        # 按信号类型统计
        by_signal_type = {}
        for r in results:
            stype = r["signal_type"]
            if stype not in by_signal_type:
                by_signal_type[stype] = {"count": 0, "wins": 0, "total_pnl": 0}
            by_signal_type[stype]["count"] += 1
            by_signal_type[stype]["wins"] += 1 if r["net_pnl_pct"] > 0 else 0
            by_signal_type[stype]["total_pnl"] += r["net_pnl_pct"]

        for stype, data in by_signal_type.items():
            data["win_rate"] = round(data["wins"] / data["count"] * 100, 1)
            data["avg_pnl"] = round(data["total_pnl"] / data["count"], 2)

        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate * 100, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "total_return_pct": round((equity - self.initial_capital) / self.initial_capital * 100, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "avg_holding_days": round(np.mean([r["holding_days"] for r in results]), 1),
            "exit_reasons": exit_reasons,
            "by_signal_type": by_signal_type,
            "trades": results,
        }

    def run_batch(self, signals: List[Dict], config: Optional[Dict] = None) -> Dict:
        """批量回测，支持不同参数对比"""
        results = {}
        if config:
            for config_name, params in config.items():
                self.initial_capital = params.get("initial_capital", self.initial_capital)
                res = self.run(signals, params.get("trading_days", 20))
                results[config_name] = res

        return results if results else self.run(signals)


# 全局实例
backtest_engine = BacktestEngine()
