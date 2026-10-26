"""
历史回测引擎

回放过去250个交易日的所有信号，计算：
- 胜率、盈亏比、总收益率
- 最大回撤、夏普比率、年化收益
- 按信号类型/市场环境的分类统计
- 策略衰减分析

用法：python backtest.py [--days 250] [--output report]
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# Windows UTF-8 输出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import DATA_DIR, REPORT_DIR
from src.data.cache import cache
from src.signals.entry import signal_detector
from src.risk.market_gate import market_gate

# ─── 参数 ─────────────────────────────────────────────
BACKTEST_DAYS = 250          # 回测天数
HOLDING_DAYS = 15            # 持仓天数
STOP_LOSS_PCT = 0.07         # 止损 7%
TAKE_PROFIT_PCT = 0.15       # 止盈 15%
TAKE_PROFIT_2_PCT = 0.25     # 第二止盈 25%
INITIAL_CAPITAL = 100000     # 初始资金 10万
COMMISSION_RATE = 0.00025    # 佣金 0.025%
STAMP_TAX = 0.001            # 印花税 0.1%（卖出）
SLIPPAGE = 0.001             # 滑点 0.1%


class BacktestResult:
    """回测结果容器"""

    def __init__(self):
        self.signals = []        # 所有信号
        self.trades = []         # 所有交易
        self.daily_equity = []   # 每日权益曲线
        self.metrics = {}        # 绩效指标
        self.by_type = {}        # 按信号类型统计
        self.by_month = {}       # 按月份统计
        self.errors = []
        self.walk_forward = {}   # Walk-Forward 分析结果

    def add_trade(self, trade: dict):
        self.trades.append(trade)

    def calculate_metrics(self):
        """计算所有绩效指标"""
        if not self.trades:
            self.metrics = {"error": "no trades"}
            return

        pnls = np.array([t["pnl_pct"] for t in self.trades])
        returns = np.array([t["return_pct"] for t in self.trades])
        holding_days_arr = np.array([t["holding_days"] for t in self.trades])

        # 基础统计
        total_trades = len(self.trades)
        wins = int(np.sum(pnls > 0))
        losses = int(np.sum(pnls < 0))
        win_rate = wins / total_trades * 100 if total_trades > 0 else 0

        # 盈亏分析
        win_pnls = pnls[pnls > 0]
        loss_pnls = pnls[pnls < 0]
        avg_win = float(np.mean(win_pnls)) * 100 if len(win_pnls) > 0 else 0
        avg_loss = float(np.mean(loss_pnls)) * 100 if len(loss_pnls) > 0 else 0
        profit_loss_ratio = abs(float(np.mean(win_pnls)) / float(np.mean(loss_pnls))) if avg_loss != 0 else 0

        # 期望值（单笔）
        expected_value = float(np.mean(returns)) * 100

        # 简单总收益（不复合，按单笔平均）
        total_return_simple = expected_value * total_trades

        # 组合模拟：最多5个持仓槽位，基于时间线逐日追踪
        MAX_SLOTS = 5
        slot_size = INITIAL_CAPITAL / MAX_SLOTS
        all_trades_sorted = sorted(self.trades, key=lambda t: t["signal_date"])

        if not all_trades_sorted:
            self.metrics = {"error": "no trades"}
            return

        # 收集所有交易日期，构建时间线
        all_dates = set()
        for t in all_trades_sorted:
            entry = t["signal_date"]
            exit_d = t.get("exit_date", entry)
            all_dates.add(entry)
            all_dates.add(exit_d)
        
        # 按日期排序，生成连续时间线
        timeline = sorted(all_dates)
        
        # 槽位状态: [exit_date, return_pct] 或 None（空闲）
        slots = [None] * MAX_SLOTS
        equity = INITIAL_CAPITAL
        daily_equity_curve = []
        trades_executed = 0
        trade_events = []  # 记录所有交易事件
        
        # 构建事件列表：每个交易日的新信号和平仓事件
        # 信号事件（开仓）
        entry_events = {}  # date -> [trades]
        exit_events = {}   # date -> [trades]
        
        for t in all_trades_sorted:
            entry_date = t["signal_date"]
            exit_date = t.get("exit_date", entry_date)
            
            if entry_date not in entry_events:
                entry_events[entry_date] = []
            entry_events[entry_date].append(t)
            
            if exit_date not in exit_events:
                exit_events[exit_date] = []
            exit_events[exit_date].append(t)
        
        # 逐日模拟
        for date in timeline:
            # 1. 处理当日平仓（先平仓，释放槽位）
            if date in exit_events:
                for t in exit_events[date]:
                    slot_pnl = slot_size * t["return_pct"]
                    equity += slot_pnl
                    trade_events.append({
                        "date": date,
                        "type": "exit",
                        "code": t["code"],
                        "pnl_pct": t["return_pct"],
                    })
                    # 释放槽位
                    for i, slot in enumerate(slots):
                        if slot is not None and slot[1] == t:
                            slots[i] = None
                            break
        
            # 2. 处理当日开仓（按信号时间顺序）
            if date in entry_events:
                for t in entry_events[date]:
                    # 找空槽位
                    slot_idx = None
                    for i, slot in enumerate(slots):
                        if slot is None:
                            slot_idx = i
                            break
                    
                    if slot_idx is not None:
                        slots[slot_idx] = (t.get("exit_date", date), t)
                        trades_executed += 1
                        trade_events.append({
                            "date": date,
                            "type": "entry",
                            "code": t["code"],
                            "return_pct": t["return_pct"],
                        })
        
            # 3. 记录每日权益
            daily_equity_curve.append((date, equity))
        
        # 计算最终指标
        total_return_pct = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

        # 最大回撤（基于逐日权益曲线）
        max_drawdown = 0
        peak = daily_equity_curve[0][1] if daily_equity_curve else equity
        drawdown_series = []
        for date, val in daily_equity_curve:
            peak = max(peak, val)
            dd = (peak - val) / peak * 100
            drawdown_series.append((date, dd))
            max_drawdown = max(max_drawdown, dd)

        # 日收益率序列（用于夏普比率）
        daily_returns = []
        for i in range(1, len(daily_equity_curve)):
            prev_eq = daily_equity_curve[i-1][1]
            curr_eq = daily_equity_curve[i][1]
            if prev_eq > 0:
                daily_returns.append((curr_eq - prev_eq) / prev_eq)

        # 夏普比率（基于日收益率，年化）
        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(250))
        else:
            sharpe = 0

        # 索提诺比率（基于日收益率）
        downside_returns = [r for r in daily_returns if r < 0]
        if len(downside_returns) > 0 and np.std(downside_returns) > 0:
            sortino = float(np.mean(daily_returns) / np.std(downside_returns) * np.sqrt(250))
        else:
            sortino = 0

        # 年化收益率（基于实际交易日数）
        trading_days = len(daily_equity_curve)
        if trading_days > 0:
            annualized_return = ((equity / INITIAL_CAPITAL) ** (250 / trading_days) - 1) * 100
        else:
            annualized_return = 0

        # 卡玛比率
        calmar = annualized_return / max_drawdown if max_drawdown > 0 else 0

        # 平均持仓天数
        avg_holding_days = float(np.mean(holding_days_arr)) if len(holding_days_arr) > 0 else 0

        # 连续亏损（按时间顺序）
        max_consecutive_losses = 0
        current_losses = 0
        exit_trades = [t for t in trade_events if t["type"] == "exit"]
        for t in exit_trades:
            if t["pnl_pct"] < 0:
                current_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
            else:
                current_losses = 0

        # 最大盈利/亏损
        max_profit = float(np.max(returns)) * 100
        max_loss = float(np.min(returns)) * 100

        self.metrics = {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "expected_value_pct": round(expected_value, 4),
            "total_return_pct": round(total_return_pct, 2),
            "annualized_return_pct": round(annualized_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
            "avg_holding_days": round(avg_holding_days, 1),
            "max_consecutive_losses": max_consecutive_losses,
            "max_single_profit_pct": round(max_profit, 2),
            "max_single_loss_pct": round(max_loss, 2),
            "final_equity": round(equity, 2),
            "initial_capital": INITIAL_CAPITAL,
            "max_slots": MAX_SLOTS,
            "trades_executed": trades_executed,
            "trades_per_slot": round(trades_executed / MAX_SLOTS, 1),
            "trading_days": trading_days,
            "daily_equity_points": len(daily_equity_curve),
        }

        # 按信号类型统计
        for t in self.trades:
            stype = t["signal_type"]
            if stype not in self.by_type:
                self.by_type[stype] = {"count": 0, "wins": 0, "total_return": 0, "pnls": []}
            self.by_type[stype]["count"] += 1
            self.by_type[stype]["wins"] += 1 if t["pnl_pct"] > 0 else 0
            self.by_type[stype]["total_return"] += t["return_pct"]
            self.by_type[stype]["pnls"].append(t["pnl_pct"])

        for stype, data in self.by_type.items():
            data["win_rate_pct"] = round(data["wins"] / data["count"] * 100, 2)
            data["total_return_pct"] = round(data["total_return"] * 100, 2)
            data["avg_pnl_pct"] = round(float(np.mean(data["pnls"])) * 100, 2)

        # 按月份统计
        for t in self.trades:
            month_key = t["signal_date"][:7]  # YYYY-MM
            if month_key not in self.by_month:
                self.by_month[month_key] = {"count": 0, "wins": 0, "total_return": 0}
            self.by_month[month_key]["count"] += 1
            self.by_month[month_key]["wins"] += 1 if t["pnl_pct"] > 0 else 0
            self.by_month[month_key]["total_return"] += t["return_pct"]

        for mk, data in self.by_month.items():
            data["win_rate_pct"] = round(data["wins"] / data["count"] * 100, 2)
            data["total_return_pct"] = round(data["total_return"] * 100, 2)

        # 权益曲线（采样）
        if len(daily_equity_curve) > 100:
            step = max(1, len(daily_equity_curve) // 100)
            self.daily_equity = [{"date": daily_equity_curve[i][0], "equity": round(daily_equity_curve[i][1], 2)}
                                 for i in range(0, len(daily_equity_curve), step)]
        else:
            self.daily_equity = [{"date": d, "equity": round(e, 2)} for d, e in daily_equity_curve]


def simulate_trade(code: str, signal_date: str, signal_price: str,
                   kline: pd.DataFrame, holding_days: int = HOLDING_DAYS,
                   stop_loss: float = STOP_LOSS_PCT,
                   take_profit: float = TAKE_PROFIT_PCT,
                   take_profit_2: float = TAKE_PROFIT_2_PCT) -> dict:
    """
    模拟单笔交易

    从 signal_date 开始，跟踪后续 holding_days 天：
    - 每日检查止损/止盈/时间止损
    - 返回交易结果
    """
    if kline is None or len(kline) == 0:
        return None

    # 找到信号日在K线中的位置
    date_col = kline.index[0] if isinstance(kline.index, pd.MultiIndex) else "date"
    kline_copy = kline.copy()
    if "date" in kline_copy.columns:
        kline_copy["date"] = pd.to_datetime(kline_copy["date"])
        date_idx = kline_copy[kline_copy["date"] == pd.to_datetime(signal_date)].index
        if len(date_idx) == 0:
            return None
        start_idx = date_idx[0]
    else:
        return None

    if start_idx + holding_days >= len(kline_copy):
        return None

    # 获取交易窗口
    trade_window = kline_copy.iloc[start_idx:start_idx + holding_days + 1]
    if len(trade_window) < 2:
        return None

    # 入场价（含滑点）
    entry_price = float(signal_price) * (1 + SLIPPAGE)
    actual_entry = entry_price

    # 止损价和目标价
    stop_price = entry_price * (1 - stop_loss)
    target1 = entry_price * (1 + take_profit)
    target2 = entry_price * (1 + take_profit_2)

    # 模拟交易
    exit_price = entry_price
    exit_reason = "time_stop"
    exit_idx = holding_days

    for i in range(1, min(len(trade_window), holding_days + 1)):
        row = trade_window.iloc[i]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        # 止损
        if low <= stop_price:
            exit_price = stop_price * (1 - SLIPPAGE)
            exit_reason = "stop_loss"
            exit_idx = i
            break

        # 止盈1（减半）- 简化为一次性止盈
        if high >= target2:
            exit_price = target2 * (1 - SLIPPAGE)
            exit_reason = "take_profit_2"
            exit_idx = i
            break
        elif high >= target1:
            exit_price = target1 * (1 - SLIPPAGE)
            exit_reason = "take_profit_1"
            exit_idx = i
            break

    else:
        # 时间止损 - 最后收盘价
        exit_price = float(trade_window.iloc[-1]["close"]) * (1 - SLIPPAGE)
        exit_reason = "time_stop"
        exit_idx = min(len(trade_window) - 1, holding_days)

    # 计算盈亏
    gross_return = (exit_price - actual_entry) / actual_entry
    commission = actual_entry * COMMISSION_RATE + exit_price * COMMISSION_RATE
    tax = exit_price * STAMP_TAX
    net_return = (exit_price - actual_entry - commission - tax) / actual_entry
    pnl_pct = (exit_price - actual_entry) / actual_entry

    # 最大回撤（MAE）和最大盈利（MFE）
    prices = trade_window["low"].iloc[:exit_idx + 1]
    mae = (float(prices.min()) - actual_entry) / actual_entry
    prices_high = trade_window["high"].iloc[:exit_idx + 1]
    mfe = (float(prices_high.max()) - actual_entry) / actual_entry

    return {
        "code": code,
        "signal_date": signal_date,
        "entry_price": round(actual_entry, 4),
        "exit_price": round(exit_price, 4),
        "exit_reason": exit_reason,
        "pnl_pct": round(pnl_pct, 4),
        "return_pct": round(net_return, 4),
        "holding_days": exit_idx,
        "mae_pct": round(mae * 100, 2),
        "mfe_pct": round(mfe * 100, 2),
        "entry_date": signal_date,
        "exit_date": str(trade_window.iloc[exit_idx]["date"])[:10] if "date" in trade_window.columns else signal_date,
    }


def check_historical_signals(kline: pd.DataFrame, code: str) -> list:
    """
    扫描K线历史，检测所有信号

    对每一天的数据检查是否满足信号条件，返回信号列表
    """
    signals = []

    if kline is None or len(kline) < 60:
        return signals

    kline = kline.copy()
    if "date" in kline.columns:
        kline["date"] = pd.to_datetime(kline["date"])

    # 计算指标
    kline["ma5"] = kline["close"].rolling(5).mean()
    kline["ma10"] = kline["close"].rolling(10).mean()
    kline["ma20"] = kline["close"].rolling(20).mean()
    kline["ma60"] = kline["close"].rolling(60).mean()

    ema12 = kline["close"].ewm(span=12, adjust=False).mean()
    ema26 = kline["close"].ewm(span=26, adjust=False).mean()
    kline["macd"] = ema12 - ema26
    kline["macd_signal"] = kline["macd"].ewm(span=9, adjust=False).mean()
    kline["macd_hist"] = kline["macd"] - kline["macd_signal"]

    kline["vol_ma5"] = kline["volume"].rolling(5).mean()
    kline["vol_ratio"] = kline["volume"] / kline["vol_ma5"]

    # RSI
    delta = kline["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    kline["rsi"] = 100 - (100 / (1 + rs))

    # 逐日扫描
    for i in range(20, len(kline) - HOLDING_DAYS):
        row = kline.iloc[i]
        prev_row = kline.iloc[i - 1]

        signal_date = str(row["date"])[:10] if "date" in kline.columns else str(kline.index[i])[:10]
        close = float(row["close"])
        macd_hist = float(row["macd_hist"])
        vol_ratio = float(row["vol_ratio"]) if not np.isnan(row["vol_ratio"]) else 1.0
        rsi = float(row["rsi"]) if not np.isnan(row["rsi"]) else 50
        ma20 = float(row["ma20"]) if not np.isnan(row["ma20"]) else 0
        ma60 = float(row["ma60"]) if not np.isnan(row["ma60"]) else 0

        # 跳过数据不足
        if ma20 <= 0 or ma60 <= 0:
            continue

        signal_type = None
        signal_desc = None

        # 回踩企稳
        if close > ma20 > ma60:
            deviation = abs(close - ma20) / ma20
            recent_vol = kline["volume"].iloc[i-4:i+1].mean()
            prev_vol = kline["volume"].iloc[i-9:i-4].mean()
            vol_shrink = recent_vol / prev_vol if prev_vol > 0 else 1.0
            if 0.03 <= deviation <= 0.08 and vol_shrink < 0.85 and 30 <= rsi <= 55:
                if macd_hist < 0 and macd_hist > -0.02 * close:
                    signal_type = "pullback_stabilize"
                    signal_desc = "回踩企稳"

        # 放量突破
        if not signal_type:
            high_20 = kline["high"].iloc[i-20:i].max()
            if close >= high_20 and vol_ratio >= 1.8 and macd_hist > 0:
                if macd_hist > float(prev_row["macd_hist"]):
                    signal_type = "breakout"
                    signal_desc = "放量突破"

        # 弱信号-接近突破
        if not signal_type:
            high_20 = kline["high"].iloc[i-20:i].max()
            if close >= high_20 * 0.98 and 1.0 <= vol_ratio < 1.8 and close > ma20:
                signal_type = "weak_breakout"
                signal_desc = "接近突破"

        if signal_type:
            signals.append({
                "code": code,
                "signal_date": signal_date,
                "signal_type": signal_type,
                "signal_desc": signal_desc,
                "entry_price": close,
                "close": close,
            })

    return signals


def run_backtest(days: int = BACKTEST_DAYS, output_report: bool = True):
    """
    执行完整回测

    1. 加载所有缓存K线数据
    2. 对每只股票扫描历史信号
    3. 模拟每笔交易
    4. 计算绩效指标
    5. 生成报告
    """
    print("=" * 70)
    print(f"  alpha-pick 历史回测 - {days}个交易日")
    print(f"  持仓{HOLDING_DAYS}天 | 止损{STOP_LOSS_PCT*100:.0f}% | 止盈{TAKE_PROFIT_PCT*100:.0f}%/{TAKE_PROFIT_2_PCT*100:.0f}%")
    print(f"  初始资金 {INITIAL_CAPITAL:,.0f}元 | 佣金{COMMISSION_RATE*100:.3f}% | 滑点{SLIPPAGE*100:.1f}%")
    print("=" * 70)

    result = BacktestResult()
    kline_cache_dir = Path(DATA_DIR) / "cache"

    # 加载所有缓存的K线数据（优先pkl，其次csv）
    kline_files = sorted(kline_cache_dir.glob("kline_filter_*.pkl"))
    if not kline_files:
        kline_files = sorted(kline_cache_dir.glob("kline_*.pkl"))
    if not kline_files:
        kline_files = sorted(kline_cache_dir.glob("kline_*.csv"))
    print(f"\n找到 {len(kline_files)} 只股票的K线数据")

    if len(kline_files) == 0:
        print("错误：无K线数据。请先运行 python cli.py scan --no-push")
        return result

    # 处理每只股票
    total_signals = 0
    total_trades = 0

    for idx, kline_file in enumerate(kline_files):
        if (idx + 1) % 20 == 0:
            print(f"  进度: {idx+1}/{len(kline_files)} 只股票")

        try:
            code = kline_file.stem.replace("kline_filter_", "").replace("kline_", "").split("_")[0]
            if kline_file.suffix == ".pkl":
                import pickle
                with open(kline_file, "rb") as f:
                    kline = pickle.load(f)
            else:
                kline = pd.read_csv(kline_file)

            if len(kline) < 80:
                continue

            # 1. 扫描历史信号
            signals = check_historical_signals(kline, code)
            total_signals += len(signals)

            # 2. 对每个信号模拟交易
            for sig in signals:
                trade = simulate_trade(
                    code=code,
                    signal_date=sig["signal_date"],
                    signal_price=sig["entry_price"],
                    kline=kline,
                    holding_days=HOLDING_DAYS,
                )
                if trade:
                    trade["signal_type"] = sig["signal_type"]
                    trade["signal_desc"] = sig["signal_desc"]
                    result.add_trade(trade)
                    total_trades += 1

        except Exception as e:
            result.errors.append(f"{kline_file.name}: {e}")
            continue

    print(f"\n扫描完成: {len(kline_files)} 只股票, {total_signals} 个信号, {total_trades} 笔交易")

    # 计算指标
    print("\n计算绩效指标...")
    result.calculate_metrics()

    # 输出报告
    if output_report:
        print_report(result)

    # Walk-Forward 分析
    if result.trades:
        wf_result = run_walk_forward(result.trades, n_periods=3)
        result.walk_forward = wf_result

    # 保存结果
    save_report(result)

    return result


def print_report(result: BacktestResult):
    """打印回测报告"""
    m = result.metrics

    if "error" in m:
        print(f"\n❌ 回测失败: {m['error']}")
        return

    print("\n" + "=" * 70)
    print("📊  回测绩效报告")
    print("=" * 70)

    print(f"\n💰 资金表现")
    print(f"   初始资金:    {m['initial_capital']:>12,.2f} 元")
    print(f"   期末资金:    {m['final_equity']:>12,.2f} 元")
    print(f"   总收益率:    {m['total_return_pct']:>+12.2f} %")
    print(f"   年化收益率:  {m['annualized_return_pct']:>+12.2f} %")

    print(f"\n📈 交易统计")
    print(f"   总交易数:    {m['total_trades']:>10}")
    print(f"   盈利/亏损:   {m['wins']:>5} / {m['losses']}")
    print(f"   胜率:        {m['win_rate_pct']:>10.2f} %")
    print(f"   平均盈利:    {m['avg_win_pct']:>+10.2f} %")
    print(f"   平均亏损:    {m['avg_loss_pct']:>+10.2f} %")
    print(f"   盈亏比:      {m['profit_loss_ratio']:>10.2f}")
    print(f"   期望值:      {m['expected_value_pct']:>+10.4f} %")
    if m.get('trades_executed'):
        print(f"   执行交易:    {m['trades_executed']:>10} 笔 (5槽位)")
    if m.get('trading_days'):
        print(f"   交易日数:    {m['trading_days']:>10} 天")

    print(f"\n📉 风险控制")
    print(f"   最大回撤:    {m['max_drawdown_pct']:>10.2f} %")
    print(f"   夏普比率:    {m['sharpe_ratio']:>10.2f}")
    print(f"   索提诺比率:  {m['sortino_ratio']:>10.2f}")
    print(f"   卡玛比率:    {m['calmar_ratio']:>10.2f}")
    print(f"   最大连续亏损:{m['max_consecutive_losses']:>10}")

    print(f"\n⏱️  持仓特征")
    print(f"   平均持仓天数:{m['avg_holding_days']:>10.1f}")
    print(f"   最大单笔盈利:{m['max_single_profit_pct']:>+10.2f} %")
    print(f"   最大单笔亏损:{m['max_single_loss_pct']:>+10.2f} %")

    # 按信号类型
    if result.by_type:
        print(f"\n📋 按信号类型")
        print(f"   {'类型':<20} {'笔数':>6} {'胜率%':>8} {'均盈亏%':>8} {'总收益%':>10}")
        print(f"   {'-'*52}")
        for stype, data in sorted(result.by_type.items(), key=lambda x: x[1]["count"], reverse=True):
            print(f"   {stype:<20} {data['count']:>6} {data['win_rate_pct']:>8.1f} {data['avg_pnl_pct']:>+8.2f} {data['total_return_pct']:>+10.2f}")

    # 按月份
    if result.by_month:
        print(f"\n📅 月度表现")
        print(f"   {'月份':<10} {'笔数':>6} {'胜率%':>8} {'收益%':>10}")
        print(f"   {'-'*34}")
        for mk in sorted(result.by_month.keys()):
            data = result.by_month[mk]
            print(f"   {mk:<10} {data['count']:>6} {data['win_rate_pct']:>8.1f} {data['total_return_pct']:>+10.2f}")

    # 权益曲线摘要
    if result.daily_equity:
        print(f"\n📈 权益曲线（采样{len(result.daily_equity)}点）")
        equities = [d["equity"] for d in result.daily_equity]
        print(f"   最低: {min(equities):,.2f} | 最高: {max(equities):,.2f} | 当前: {equities[-1]:,.2f}")

    # 评估
    print(f"\n{'='*70}")
    print("🏆 综合评估")
    print(f"{'='*70}")

    score = 0
    reasons = []

    if m["win_rate_pct"] >= 55:
        score += 25
        reasons.append("✅ 胜率优秀 (≥55%)")
    elif m["win_rate_pct"] >= 45:
        score += 15
        reasons.append("⚠️ 胜率一般 (45-55%)")
    else:
        reasons.append("❌ 胜率偏低 (<45%)")

    if m["profit_loss_ratio"] >= 2.0:
        score += 25
        reasons.append("✅ 盈亏比优秀 (≥2.0)")
    elif m["profit_loss_ratio"] >= 1.5:
        score += 15
        reasons.append("⚠️ 盈亏比一般 (1.5-2.0)")
    else:
        reasons.append("❌ 盈亏比偏低 (<1.5)")

    if m["max_drawdown_pct"] <= 15:
        score += 25
        reasons.append("✅ 回撤可控 (≤15%)")
    elif m["max_drawdown_pct"] <= 25:
        score += 15
        reasons.append("⚠️ 回撤偏高 (15-25%)")
    else:
        reasons.append("❌ 回撤过大 (>25%)")

    if m["sharpe_ratio"] >= 1.5:
        score += 25
        reasons.append("✅ 夏普优秀 (≥1.5)")
    elif m["sharpe_ratio"] >= 1.0:
        score += 15
        reasons.append("⚠️ 夏普一般 (1.0-1.5)")
    else:
        reasons.append("❌ 夏普偏低 (<1.0)")

    print(f"\n   回测得分: {score}/100")
    for r in reasons:
        print(f"   {r}")

    if score >= 75:
        print(f"\n   🟢 结论: 策略表现良好，可考虑模拟盘验证")
    elif score >= 55:
        print(f"\n   🟡 结论: 策略表现一般，建议优化参数后再验证")
    else:
        print(f"\n   🔴 结论: 策略表现不佳，需要重新设计")

    if result.errors:
        print(f"\n⚠️ 错误: {len(result.errors)} 个")
        for e in result.errors[:5]:
            print(f"   {e}")


def save_report(result: BacktestResult):
    """保存回测结果到文件"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # 保存指标
    metrics_path = REPORT_DIR / f"backtest_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump({
            "metrics": result.metrics,
            "by_type": result.by_type,
            "by_month": result.by_month,
            "trades_count": len(result.trades),
            "errors": result.errors,
            "backtest_params": {
                "days": BACKTEST_DAYS,
                "holding_days": HOLDING_DAYS,
                "stop_loss": STOP_LOSS_PCT,
                "take_profit": TAKE_PROFIT_PCT,
                "initial_capital": INITIAL_CAPITAL,
            }
        }, f, ensure_ascii=False, indent=2)

    print(f"\n💾 回测结果已保存: {metrics_path}")

    # 保存交易明细
    trades_path = REPORT_DIR / f"backtest_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    if result.trades:
        trades_df = pd.DataFrame(result.trades)
        trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
        print(f"💾 交易明细已保存: {trades_path}")


def run_walk_forward(trades: list, n_periods: int = 3, overlap_days: int = 30) -> dict:
    """
    Walk-Forward 分析
    
    将回测期分为多个训练/测试窗口，验证策略稳定性
    
    Args:
        trades: 交易列表
        n_periods: 窗口数量
        overlap_days: 窗口重叠天数
    
    Returns:
        walk-forward 分析结果
    """
    # 收集所有交易日期
    all_dates = sorted(set(t.get("signal_date", "") for t in trades if t.get("signal_date")))
    
    if not all_dates:
        return {"error": "no trades with dates"}
    
    total_days = len(all_dates)
    period_size = (total_days - overlap_days * (n_periods - 1)) // n_periods
    
    print(f"\n{'='*70}")
    print(f"🔄 Walk-Forward 分析 ({n_periods}个窗口, 重叠{overlap_days}天)")
    print(f"{'='*70}")
    
    results = []
    
    for i in range(n_periods):
        # 计算窗口日期范围
        train_start_idx = max(0, i * period_size - 60)
        train_end_idx = i * period_size
        test_start_idx = i * period_size
        test_end_idx = min(total_days - 1, (i + 1) * period_size + overlap_days)
        
        train_start_date = all_dates[train_start_idx] if train_start_idx < total_days else all_dates[0]
        train_end_date = all_dates[min(train_end_idx, total_days - 1)]
        test_start_date = all_dates[min(test_start_idx, total_days - 1)]
        test_end_date = all_dates[min(test_end_idx, total_days - 1)]
        
        print(f"\n--- 窗口 {i+1}/{n_periods} ---")
        print(f"   测试期: {test_start_date} ~ {test_end_date}")
        print(f"   训练期: {train_start_date} ~ {train_end_date}")
        
        # 筛选该时间窗口内的交易
        window_trades = [
            t for t in trades 
            if t.get("signal_date", "") >= test_start_date and t.get("signal_date", "") <= test_end_date
        ]
        
        if not window_trades:
            print(f"   ⚠️  无交易数据")
            continue
        
        # 计算窗口指标
        pnls = [t["pnl_pct"] for t in window_trades]
        wins = sum(1 for p in pnls if p > 0)
        total = len(pnls)
        win_rate = wins / total * 100 if total > 0 else 0
        avg_pnl = np.mean(pnls) * 100 if pnls else 0
        total_return = sum(pnls) * 100
        
        result = {
            "period": i + 1,
            "test_start": test_start_date,
            "test_end": test_end_date,
            "train_start": train_start_date,
            "train_end": train_end_date,
            "trades": total,
            "wins": wins,
            "win_rate_pct": round(win_rate, 2),
            "avg_pnl_pct": round(avg_pnl, 2),
            "total_return_pct": round(total_return, 2),
        }
        results.append(result)
        
        print(f"   交易数: {total}")
        print(f"   胜率: {win_rate:.1f}%")
        print(f"   平均盈亏: {avg_pnl:+.2f}%")
        print(f"   总收益: {total_return:+.2f}%")
    
    # 分析稳定性
    if results:
        win_rates = [r["win_rate_pct"] for r in results]
        returns = [r["total_return_pct"] for r in results]
        
        print(f"\n{'='*70}")
        print(f"📊 Walk-Forward 稳定性分析")
        print(f"{'='*70}")
        print(f"   胜率范围: {min(win_rates):.1f}% - {max(win_rates):.1f}%")
        print(f"   收益范围: {min(returns):+.1f}% - {max(returns):+.1f}%")
        
        win_rate_std = np.std(win_rates)
        return_std = np.std(returns)
        
        print(f"   胜率标准差: {win_rate_std:.2f}%")
        print(f"   收益标准差: {return_std:.2f}%")
        
        # 稳定性评分
        stability_score = 100
        
        if win_rate_std > 20:
            stability_score -= 30
            print(f"   ⚠️  胜率波动过大 (>{win_rate_std:.0f}%)")
        elif win_rate_std > 10:
            stability_score -= 15
            print(f"   ⚡  胜率有一定波动")
        
        if min(returns) < -50:
            stability_score -= 30
            print(f"   ⚠️  存在大幅亏损窗口")
        elif min(returns) < -20:
            stability_score -= 15
            print(f"   ⚡  存在亏损窗口")
        
        # 一致性
        profitable_periods = sum(1 for r in results if r["total_return_pct"] > 0)
        if profitable_periods < len(results) * 0.6:
            stability_score -= 20
            print(f"   ⚠️  多数窗口亏损 ({profitable_periods}/{len(results)})")
        
        stability_score = max(0, min(100, stability_score))
        print(f"\n   📈 稳定性评分: {stability_score}/100")
        
        if stability_score >= 80:
            print(f"   🟢 结论: 策略表现稳定，可考虑实盘")
        elif stability_score >= 60:
            print(f"   🟡 结论: 策略有一定波动，建议继续观察")
        else:
            print(f"   🔴 结论: 策略不稳定，需要优化")
        
        return {
            "results": results,
            "stability_score": stability_score,
            "win_rate_range": [min(win_rates), max(win_rates)],
            "return_range": [min(returns), max(returns)],
            "profitable_periods": profitable_periods,
            "total_periods": len(results),
        }
    
    return {"error": "no results"}


if __name__ == "__main__":
    # 解析参数
    days = BACKTEST_DAYS
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--days" and i + 2 < len(sys.argv):
            days = int(sys.argv[i + 2])

    result = run_backtest(days=days)

    # 打印退出码
    m = result.metrics
    if "error" not in m:
        sys.exit(0)
    else:
        sys.exit(1)
