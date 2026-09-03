# -*- coding: utf-8 -*-
"""修改backtest_engine.py，加入滑点和手续费模拟。

A股交易成本：
- 佣金：万2.5（买卖都收，最低5元）
- 印花税：千1（卖出时收）
- 滑点：0.1%（模拟实际成交价格偏差）
"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\backtest_engine.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在BacktestEngine类的__init__中添加交易成本配置
old = '''class BacktestEngine:
    """回测引擎。"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))'''

new = '''class BacktestEngine:
    """回测引擎。"""

    # A股交易成本配置
    COMMISSION_RATE = 0.00025    # 佣金万2.5
    COMMISSION_MIN = 5.0         # 最低佣金5元
    STAMP_TAX_RATE = 0.001       # 印花税千1（卖出）
    SLIPPAGE_RATE = 0.001        # 滑点0.1%

    def __init__(self, enable_cost: bool = True):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.enable_cost = enable_cost  # 是否启用交易成本模拟'''

if old in content:
    content = content.replace(old, new, 1)
    print("✅ 交易成本配置添加成功")
else:
    print("❌ 未找到BacktestEngine类定义")

# 2. 添加计算交易成本的辅助方法（在__init__之后）
old2 = '''    def backtest_strategy(self, stock_code: str, strategy_func, days: int = 60) -> Dict:'''

new2 = '''    def _calc_buy_cost(self, price: float, shares: int) -> Dict:
        """计算买入成本。

        Returns:
            {actual_price, commission, total_cost}
        """
        if not self.enable_cost:
            return {"actual_price": price, "commission": 0, "total_cost": price * shares}

        # 滑点：买入价更高
        actual_price = price * (1 + self.SLIPPAGE_RATE)
        # 佣金
        commission = max(actual_price * shares * self.COMMISSION_RATE, self.COMMISSION_MIN)
        total_cost = actual_price * shares + commission
        return {
            "actual_price": round(actual_price, 3),
            "commission": round(commission, 2),
            "total_cost": round(total_cost, 2),
        }

    def _calc_sell_cost(self, price: float, shares: int) -> Dict:
        """计算卖出成本。

        Returns:
            {actual_price, commission, stamp_tax, total_revenue}
        """
        if not self.enable_cost:
            return {"actual_price": price, "commission": 0, "stamp_tax": 0, "total_revenue": price * shares}

        # 滑点：卖出价更低
        actual_price = price * (1 - self.SLIPPAGE_RATE)
        # 佣金
        commission = max(actual_price * shares * self.COMMISSION_RATE, self.COMMISSION_MIN)
        # 印花税（卖出）
        stamp_tax = actual_price * shares * self.STAMP_TAX_RATE
        total_revenue = actual_price * shares - commission - stamp_tax
        return {
            "actual_price": round(actual_price, 3),
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "total_revenue": round(total_revenue, 2),
        }

    def backtest_strategy(self, stock_code: str, strategy_func, days: int = 60) -> Dict:'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("✅ 交易成本计算方法添加成功")
else:
    print("❌ 未找到backtest_strategy方法")

# 3. 修改开仓逻辑：使用实际买入价和成本
old3 = '''                        entry_price = closes[i + 1]
                        position = int(capital * 0.3 / entry_price)  # 30%仓位
                        if position > 0:
                            capital -= entry_price * position
                            entry_date = dates[i + 1]'''

new3 = '''                        signal_price = closes[i + 1]
                        buy_info = self._calc_buy_cost(signal_price, int(capital * 0.3 / signal_price))
                        entry_price = buy_info["actual_price"]
                        position = int(capital * 0.3 / entry_price)  # 30%仓位
                        if position > 0:
                            buy_info = self._calc_buy_cost(signal_price, position)
                            entry_price = buy_info["actual_price"]
                            capital -= buy_info["total_cost"]
                            entry_date = dates[i + 1]
                            entry_commission = buy_info["commission"]'''

if old3 in content:
    content = content.replace(old3, new3, 1)
    print("✅ 开仓成本模拟添加成功")
else:
    print("❌ 未找到开仓逻辑")

# 4. 修改止损平仓逻辑
old4 = '''                if lows[i + 1] <= entry_price * 0.95:  # 止损-5%
                    exit_price = entry_price * 0.95
                    pnl = (exit_price - entry_price) * position
                    capital += exit_price * position
                    trades.append({
                        "entry_date": str(entry_date),
                        "exit_date": str(dates[i + 1]),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "return_pct": round((exit_price - entry_price) / entry_price * 100, 2),
                        "pnl": round(pnl, 2),
                        "reason": "stop_loss",
                    })'''

new4 = '''                if lows[i + 1] <= entry_price * 0.95:  # 止损-5%
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
                    })'''

if old4 in content:
    content = content.replace(old4, new4, 1)
    print("✅ 止损平仓成本模拟添加成功")
else:
    print("❌ 未找到止损平仓逻辑")

# 5. 修改止盈平仓逻辑
old5 = '''                elif highs[i + 1] >= entry_price * 1.10:  # 止盈+10%
                    exit_price = entry_price * 1.10
                    pnl = (exit_price - entry_price) * position
                    capital += exit_price * position
                    trades.append({
                        "entry_date": str(entry_date),
                        "exit_date": str(dates[i + 1]),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "return_pct": round((exit_price - entry_price) / entry_price * 100, 2),
                        "pnl": round(pnl, 2),
                        "reason": "take_profit",
                    })'''

new5 = '''                elif highs[i + 1] >= entry_price * 1.10:  # 止盈+10%
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
                    })'''

if old5 in content:
    content = content.replace(old5, new5, 1)
    print("✅ 止盈平仓成本模拟添加成功")
else:
    print("❌ 未找到止盈平仓逻辑")

# 6. 修改最后平仓逻辑
old6 = '''        if position > 0:
            exit_price = closes[-1]
            pnl = (exit_price - entry_price) * position
            capital += exit_price * position
            trades.append({
                "entry_date": str(entry_date),
                "exit_date": str(dates[-1]),
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "return_pct": round((exit_price - entry_price) / entry_price * 100, 2),
                "pnl": round(pnl, 2),
                "reason": "end",
            })'''

new6 = '''        if position > 0:
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
            })'''

if old6 in content:
    content = content.replace(old6, new6, 1)
    print("✅ 最后平仓成本模拟添加成功")
else:
    print("❌ 未找到最后平仓逻辑")

# 7. 在绩效统计中加入总交易成本
old7 = '''        return {
            "status": "ok",
            "stock_code": stock_code,
            "total_trades": len(trades),
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "max_return_pct": round(max_return, 2),
            "min_return_pct": round(min_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_return_pct": round(total_return, 2),
            "initial_capital": initial_capital,
            "final_capital": round(final_capital, 2),
            "trades": trades,
        }'''

new7 = '''        # 统计总交易成本
        total_commission = sum(t.get("buy_commission", 0) + t.get("sell_commission", 0) for t in trades)
        total_stamp_tax = sum(t.get("stamp_tax", 0) for t in trades)
        total_cost = total_commission + total_stamp_tax

        return {
            "status": "ok",
            "stock_code": stock_code,
            "total_trades": len(trades),
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "max_return_pct": round(max_return, 2),
            "min_return_pct": round(min_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_return_pct": round(total_return, 2),
            "initial_capital": initial_capital,
            "final_capital": round(final_capital, 2),
            "total_commission": round(total_commission, 2),
            "total_stamp_tax": round(total_stamp_tax, 2),
            "total_trading_cost": round(total_cost, 2),
            "cost_enabled": self.enable_cost,
            "trades": trades,
        }'''

if old7 in content:
    content = content.replace(old7, new7, 1)
    print("✅ 交易成本统计添加成功")
else:
    print("❌ 未找到绩效统计返回")

# 8. 在回测报告中加入交易成本展示
old8 = '''    lines.append(f"  平均收益：{result.get('avg_return_pct', result.get('avg_return_pct', 0))}%")
    lines.append(f"  最大回撤：{result.get('avg_max_drawdown_pct', result.get('max_drawdown_pct', 0))}%")
    lines.append(f"  最佳单笔：{result.get('max_return_pct', 0)}%")
    lines.append(f"  最差单笔：{result.get('min_return_pct', 0)}%")
    lines.append("")'''

new8 = '''    lines.append(f"  平均收益：{result.get('avg_return_pct', result.get('avg_return_pct', 0))}%")
    lines.append(f"  最大回撤：{result.get('avg_max_drawdown_pct', result.get('max_drawdown_pct', 0))}%")
    lines.append(f"  最佳单笔：{result.get('max_return_pct', 0)}%")
    lines.append(f"  最差单笔：{result.get('min_return_pct', 0)}%")
    if result.get("cost_enabled"):
        lines.append(f"  总交易成本：佣金{result.get('total_commission', 0)}元 + 印花税{result.get('total_stamp_tax', 0)}元 = {result.get('total_trading_cost', 0)}元")
    lines.append("")'''

if old8 in content:
    content = content.replace(old8, new8, 1)
    print("✅ 回测报告成本展示添加成功")
else:
    print("❌ 未找到回测报告位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ backtest_engine.py 修改完成")
