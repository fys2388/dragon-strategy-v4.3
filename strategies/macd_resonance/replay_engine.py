# -*- coding: utf-8 -*-
"""历史回放引擎。

比普通回测更真实的验证方式：
- 逐交易日推进，每天只使用当天及之前的数据
- 模拟当时看到什么数据、当时如何产生信号
- 模拟当时执行（含滑点、手续费、T+1约束）
- 记录完整的交易日志和资金曲线

这是视频中强调的"历史数据回放"步骤，比普通回测更接近真实实盘。
普通回测的问题：可能无意中使用了未来信息（未来函数）。
回放引擎严格保证：第i天的决策只能用第i天及之前的数据。
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Callable, Optional
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPLAY_LOG_DIR = os.path.join(BASE_DIR, "data", "replay_logs")
os.makedirs(REPLAY_LOG_DIR, exist_ok=True)


class ReplayEngine:
    """历史回放引擎。"""

    def __init__(self, initial_capital: float = 10000.0,
                 commission_rate: float = 0.00025,
                 stamp_tax_rate: float = 0.001,
                 slippage_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage_rate = slippage_rate
        self.positions = {}  # {code: {shares, entry_price, entry_date}}
        self.trades = []
        self.daily_values = []  # 每日总资产
        self.signals = []  # 每日信号记录

    def _calc_buy_cost(self, price: float, shares: int) -> Dict:
        """计算买入成本（含滑点、佣金）。"""
        actual_price = price * (1 + self.slippage_rate)
        commission = max(actual_price * shares * self.commission_rate, 5.0)
        total_cost = actual_price * shares + commission
        return {"actual_price": actual_price, "commission": commission, "total_cost": total_cost}

    def _calc_sell_revenue(self, price: float, shares: int) -> Dict:
        """计算卖出收入（含滑点、佣金、印花税）。"""
        actual_price = price * (1 - self.slippage_rate)
        commission = max(actual_price * shares * self.commission_rate, 5.0)
        stamp_tax = actual_price * shares * self.stamp_tax_rate
        total_revenue = actual_price * shares - commission - stamp_tax
        return {"actual_price": actual_price, "commission": commission,
                "stamp_tax": stamp_tax, "total_revenue": total_revenue}

    def replay(self, stock_code: str, df: pd.DataFrame,
               signal_func: Callable,
               start_idx: int = 30,
               position_pct: float = 0.3,
               stop_loss_pct: float = 0.05,
               take_profit_pct: float = 0.10,
               max_holding_days: int = 10) -> Dict[str, Any]:
        """执行历史回放。

        Args:
            stock_code: 股票代码
            df: 完整K线数据
            signal_func: 信号函数，输入(history_df, current_idx)返回(should_buy, should_sell)
            start_idx: 从第几天开始（预热期）
            position_pct: 单票仓位比例
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
            max_holding_days: 最大持仓天数

        Returns:
            回放结果
        """
        if df.empty or len(df) < start_idx + 10:
            return {"status": "error", "message": "数据不足"}

        closes = df["close"].astype(float).values
        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        dates = df["date"].values if "date" in df.columns else list(range(len(df)))

        self.capital = self.initial_capital
        self.positions = {}
        self.trades = []
        self.daily_values = []
        self.signals = []

        print(f"[回放] {stock_code} 开始回放，{len(df)}天数据，从第{start_idx}天开始")

        for i in range(start_idx, len(df)):
            current_date = str(dates[i])
            current_price = closes[i]

            # ===== 1. 检查持仓的止损止盈（用当天的high/low）=====
            if stock_code in self.positions:
                pos = self.positions[stock_code]
                entry_price = pos["entry_price"]
                holding_days = i - pos["entry_idx"]

                # 检查止损（当天最低价触发）
                if lows[i] <= entry_price * (1 - stop_loss_pct):
                    sell_info = self._calc_sell_revenue(entry_price * (1 - stop_loss_pct), pos["shares"])
                    self._close_position(stock_code, sell_info, current_date, "stop_loss", i)
                # 检查止盈（当天最高价触发）
                elif highs[i] >= entry_price * (1 + take_profit_pct):
                    sell_info = self._calc_sell_revenue(entry_price * (1 + take_profit_pct), pos["shares"])
                    self._close_position(stock_code, sell_info, current_date, "take_profit", i)
                # 超过最大持仓天数，收盘价卖出
                elif holding_days >= max_holding_days:
                    sell_info = self._calc_sell_revenue(current_price, pos["shares"])
                    self._close_position(stock_code, sell_info, current_date, "timeout", i)

            # ===== 2. 产生信号（只使用到第i天为止的数据）=====
            history_df = df.iloc[:i+1].copy()  # 关键：只用到当天及之前的数据
            try:
                should_buy, should_sell = signal_func(history_df, i)
            except Exception as e:
                should_buy, should_sell = False, False
                print(f"[回放] 第{i}天信号函数异常: {e}")

            self.signals.append({
                "date": current_date,
                "idx": i,
                "price": current_price,
                "should_buy": should_buy,
                "should_sell": should_sell,
            })

            # ===== 3. 执行卖出信号 =====
            if should_sell and stock_code in self.positions:
                sell_info = self._calc_sell_revenue(current_price, self.positions[stock_code]["shares"])
                self._close_position(stock_code, sell_info, current_date, "signal_sell", i)

            # ===== 4. 执行买入信号（T+1：当天买入，第二天才能卖）=====
            if should_buy and stock_code not in self.positions:
                max_amount = self.capital * position_pct
                buy_info = self._calc_buy_cost(current_price, int(max_amount / current_price))
                shares = int(max_amount / buy_info["actual_price"])
                if shares > 0 and buy_info["total_cost"] <= self.capital:
                    buy_info = self._calc_buy_cost(current_price, shares)
                    self.capital -= buy_info["total_cost"]
                    self.positions[stock_code] = {
                        "shares": shares,
                        "entry_price": buy_info["actual_price"],
                        "entry_date": current_date,
                        "entry_idx": i,
                        "buy_commission": buy_info["commission"],
                    }

            # ===== 5. 记录每日总资产 =====
            position_value = sum(
                pos["shares"] * current_price for pos in self.positions.values()
            )
            total_value = self.capital + position_value
            self.daily_values.append({
                "date": current_date,
                "idx": i,
                "capital": round(self.capital, 2),
                "position_value": round(position_value, 2),
                "total_value": round(total_value, 2),
                "return_pct": round((total_value / self.initial_capital - 1) * 100, 2),
            })

        # 最后平仓
        if stock_code in self.positions:
            last_price = closes[-1]
            sell_info = self._calc_sell_revenue(last_price, self.positions[stock_code]["shares"])
            self._close_position(stock_code, sell_info, str(dates[-1]), "end", len(df) - 1)

        return self._build_result(stock_code)

    def _close_position(self, code: str, sell_info: Dict, date: str, reason: str, idx: int):
        """平仓。"""
        pos = self.positions.pop(code)
        pnl = sell_info["total_revenue"] - pos["entry_price"] * pos["shares"] - pos["buy_commission"]
        return_pct = pnl / (pos["entry_price"] * pos["shares"]) * 100

        self.capital += sell_info["total_revenue"]

        # 计算MAE/MFE（持仓期间最大浮亏浮盈）
        # 简化：用entry到exit之间的价格波动估算
        trade = {
            "code": code,
            "entry_date": pos["entry_date"],
            "exit_date": date,
            "entry_price": round(pos["entry_price"], 2),
            "exit_price": round(sell_info["actual_price"], 2),
            "shares": pos["shares"],
            "return_pct": round(return_pct, 2),
            "pnl": round(pnl, 2),
            "reason": reason,
            "holding_days": idx - pos["entry_idx"],
            "buy_commission": pos["buy_commission"],
            "sell_commission": sell_info["commission"],
            "stamp_tax": sell_info["stamp_tax"],
            "total_cost": round(pos["buy_commission"] + sell_info["commission"] + sell_info["stamp_tax"], 2),
        }
        self.trades.append(trade)

    def _build_result(self, stock_code: str) -> Dict[str, Any]:
        """构建回放结果。"""
        if not self.trades:
            return {
                "status": "ok",
                "stock_code": stock_code,
                "total_trades": 0,
                "message": "无交易",
                "final_capital": self.capital,
                "total_return_pct": 0,
            }

        returns = [t["return_pct"] for t in self.trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        # 计算最大回撤
        values = [d["total_value"] for d in self.daily_values]
        peak = values[0] if values else self.initial_capital
        max_drawdown = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_drawdown:
                max_drawdown = dd

        # 总交易成本
        total_cost = sum(t["total_cost"] for t in self.trades)

        final_value = self.daily_values[-1]["total_value"] if self.daily_values else self.capital

        result = {
            "status": "ok",
            "stock_code": stock_code,
            "total_trades": len(self.trades),
            "win_trades": len(wins),
            "loss_trades": len(losses),
            "win_rate": round(len(wins) / len(self.trades) * 100, 1),
            "avg_return_pct": round(sum(returns) / len(returns), 2),
            "max_return_pct": round(max(returns), 2),
            "min_return_pct": round(min(returns), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "total_return_pct": round((final_value / self.initial_capital - 1) * 100, 2),
            "initial_capital": self.initial_capital,
            "final_capital": round(final_value, 2),
            "total_trading_cost": round(total_cost, 2),
            "avg_holding_days": round(sum(t["holding_days"] for t in self.trades) / len(self.trades), 1),
            "trades": self.trades,
            "daily_values": self.daily_values[-100:],  # 只保留最后100天
        }

        # 保存回放日志
        log_file = os.path.join(REPLAY_LOG_DIR, f"replay_{stock_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        result["log_file"] = log_file

        return result

    def build_replay_report(self, result: Dict) -> str:
        """生成回放报告。"""
        lines = [
            f"🔄 历史回放报告：{result.get('stock_code', '')}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"交易次数：{result.get('total_trades', 0)}次",
            f"胜率：{result.get('win_rate', 0)}%（{result.get('win_trades', 0)}胜/{result.get('loss_trades', 0)}负）",
            f"平均收益：{result.get('avg_return_pct', 0)}%",
            f"最佳单笔：{result.get('max_return_pct', 0)}%",
            f"最差单笔：{result.get('min_return_pct', 0)}%",
            f"最大回撤：{result.get('max_drawdown_pct', 0)}%",
            f"总收益：{result.get('total_return_pct', 0)}%",
            f"总交易成本：{result.get('total_trading_cost', 0)}元",
            f"平均持仓天数：{result.get('avg_holding_days', 0)}天",
            f"初始资金：{result.get('initial_capital', 0)}元 → 最终：{result.get('final_capital', 0)}元",
        ]

        # 最近5笔交易
        trades = result.get("trades", [])[-5:]
        if trades:
            lines.append("")
            lines.append("最近交易：")
            for t in trades:
                emoji = "🟢" if t["return_pct"] > 0 else "🔴"
                lines.append(f"  {emoji} {t['entry_date']}→{t['exit_date']} {t['return_pct']}% ({t['reason']})")

        return "\n".join(lines)


def init_replay_engine() -> ReplayEngine:
    """初始化回放引擎。"""
    return ReplayEngine()
