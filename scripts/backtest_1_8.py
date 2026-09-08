# -*- coding: utf-8 -*-
"""1-8月策略回测演算（本金5000元）。

回测周期：2026年1月1日 - 2026年8月31日（约160个交易日）
本金：5000元
策略：趋势突破策略（融合熊猫有财+黄阳体系）
  - 突破20日新高 + 量比>1.5 + 收盘价>20日均线 + 均线多头
  - 位置判断：低位突破加分，高位突破减分
  - 量价配合：放量上涨加分，缩量上涨减分
  - 三分仓位：底仓30%(1500元) + 加仓30%(1500元) + 备用40%(2000元)
  - 止损：-4%或支撑位下方2%
  - 止盈：+8%
股票池：优质股票池（214只）
"""
from __future__ import annotations

import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import data_source as ds

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 回测参数
INITIAL_CAPITAL = 5000.0
BASE_POSITION_PCT = 0.30   # 底仓30% = 1500元
ADD_POSITION_PCT = 0.30    # 加仓30% = 1500元
STOP_LOSS_PCT = 0.04       # 止损-4%
TAKE_PROFIT_PCT = 0.08     # 止盈+8%
MAX_POSITIONS = 2          # 最多持仓2只
COMMISSION_RATE = 0.00025  # 佣金万2.5
COMMISSION_MIN = 5.0       # 最低佣金5元
STAMP_TAX_RATE = 0.001     # 印花税千1（卖出）
SLIPPAGE_RATE = 0.001      # 滑点0.1%


def load_quality_pool() -> List[Dict]:
    """加载优质股票池。"""
    pool_file = os.path.join(BASE_DIR, "data", "quality_pool.json")
    try:
        with open(pool_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def calc_breakout_signal(closes: list, highs: list, volumes: list, idx: int) -> Dict:
    """计算趋势突破信号（融合熊猫有财体系）。

    Returns:
        {signal: bool, score: float, position_type: str, vol_health: str}
    """
    if idx < 25:
        return {"signal": False, "score": 0}

    current_price = closes[idx]
    ma5 = sum(closes[idx-4:idx+1]) / 5
    ma10 = sum(closes[idx-9:idx+1]) / 10
    ma20 = sum(closes[idx-19:idx+1]) / 20

    # 突破20日新高（前20日最高，不含当日）
    recent_high = max(highs[idx-20:idx])
    is_breakout = current_price > recent_high

    # 量比
    if idx >= 5:
        avg_vol_5d = sum(volumes[idx-5:idx]) / 5
        today_vol = volumes[idx]
        volume_ratio = today_vol / avg_vol_5d if avg_vol_5d > 0 else 0
    else:
        volume_ratio = 0

    # 均线多头 + 20日均线（熊猫有财核心规则）
    ma_bullish = ma5 > ma10 > ma20
    above_ma20 = current_price > ma20

    # 突破条件
    if not (is_breakout and volume_ratio >= 1.5 and above_ma20 and ma_bullish):
        return {"signal": False, "score": 0}

    # 位置判断（60日）
    if idx >= 60:
        low_60d = min(closes[idx-59:idx+1])
        high_60d = max(closes[idx-59:idx+1])
        gain_from_low = (current_price - low_60d) / low_60d * 100 if low_60d > 0 else 0
        distance_from_high = (high_60d - current_price) / high_60d * 100 if high_60d > 0 else 0
        if gain_from_low < 30:
            position_type = "low"
            position_score = 20
        elif gain_from_low > 50 or distance_from_high < 10:
            position_type = "high"
            position_score = -20
        else:
            position_type = "mid"
            position_score = 0
    else:
        position_type = "unknown"
        position_score = 0

    # 量价配合
    today_gain = (closes[idx] - closes[idx-1]) / closes[idx-1] * 100 if idx > 0 else 0
    if idx >= 10 and today_gain > 0:
        recent_5d_vol = sum(volumes[idx-4:idx+1]) / 5
        prev_5d_vol = sum(volumes[idx-9:idx-4]) / 5
        vol_trend = (recent_5d_vol - prev_5d_vol) / prev_5d_vol * 100 if prev_5d_vol > 0 else 0
        if vol_trend > 10:
            vol_health = "healthy"
            vol_score = 15
        elif vol_trend < -10:
            vol_health = "weak"
            vol_score = -10
        else:
            vol_health = "normal"
            vol_score = 0
    else:
        vol_health = "unknown"
        vol_score = 0

    # 综合打分（技术面）
    today_gain_pct = (closes[idx] - closes[idx-1]) / closes[idx-1] * 100 if idx > 0 else 0
    tech_score = today_gain_pct * 3 + volume_ratio * 5 + vol_score + position_score + (5 if above_ma20 else 0)
    tech_score = max(0, min(100, tech_score))

    return {
        "signal": True,
        "score": tech_score,
        "position_type": position_type,
        "vol_health": vol_health,
        "today_gain": today_gain_pct,
        "volume_ratio": volume_ratio,
        "breakout_high": recent_high,
    }


def run_backtest():
    """运行1-8月回测。"""
    print("=" * 60)
    print("📊 1-8月策略回测演算（本金5000元）")
    print("=" * 60)

    # 加载股票池
    pool = load_quality_pool()
    if not pool:
        print("❌ 优质股票池为空")
        return

    print(f"股票池：{len(pool)}只")
    print(f"本金：{INITIAL_CAPITAL}元")
    print(f"底仓：{INITIAL_CAPITAL * BASE_POSITION_PCT:.0f}元 | 加仓：{INITIAL_CAPITAL * ADD_POSITION_PCT:.0f}元 | 备用：{INITIAL_CAPITAL * 0.4:.0f}元")
    print(f"止损：-{STOP_LOSS_PCT*100:.0f}% | 止盈：+{TAKE_PROFIT_PCT*100:.0f}% | 最多持仓：{MAX_POSITIONS}只")
    print()

    # 获取所有股票的历史数据（取250天，覆盖1-8月+预热）
    print("正在获取历史K线数据...")
    stock_data = {}
    for i, stock in enumerate(pool[:50]):  # 取前50只进行回测（控制耗时）
        code = stock["code"]
        try:
            df = ds.get_kline_daily(code, count=250)
            if df is not None and not df.empty and len(df) >= 100:
                stock_data[code] = {
                    "name": stock.get("name", code),
                    "closes": df["close"].astype(float).tolist(),
                    "highs": df["high"].astype(float).tolist(),
                    "lows": df["low"].astype(float).tolist(),
                    "volumes": df["volume"].astype(float).tolist(),
                    "dates": df["date"].tolist() if "date" in df.columns else list(range(len(df))),
                }
        except Exception as e:
            pass
        if (i + 1) % 10 == 0:
            print(f"  已获取 {i+1}/{min(50, len(pool))} 只")

    print(f"成功获取 {len(stock_data)} 只股票数据")
    if not stock_data:
        print("❌ 无可用数据")
        return

    # 确定回测时间范围（取所有股票共同的日期范围）
    # 假设数据从2025年底开始，取最后160个交易日（约1-8月）
    min_len = min(len(d["closes"]) for d in stock_data.values())
    # 从第60天开始（预热期），到最后一天
    start_idx = max(60, min_len - 165)
    end_idx = min_len - 1
    print(f"回测区间：第{start_idx}天 - 第{end_idx}天（共{end_idx - start_idx + 1}个交易日）")
    print()

    # 回测主循环
    capital = INITIAL_CAPITAL
    positions = {}  # {code: {shares, entry_price, entry_idx, base_filled, add_filled}}
    trades = []
    daily_values = []  # 每日总资产

    for day_idx in range(start_idx, end_idx + 1):
        # 1. 检查持仓止损止盈（用当日最低价/最高价模拟）
        to_sell = []
        for code, pos in positions.items():
            if code not in stock_data:
                continue
            data = stock_data[code]
            if day_idx >= len(data["closes"]):
                continue
            current_price = data["closes"][day_idx]
            day_low = data["lows"][day_idx]
            day_high = data["highs"][day_idx]
            entry_price = pos["entry_price"]

            # 止损
            if day_low <= entry_price * (1 - STOP_LOSS_PCT):
                sell_price = entry_price * (1 - STOP_LOSS_PCT)
                to_sell.append((code, sell_price, "stop_loss"))
            # 止盈
            elif day_high >= entry_price * (1 + TAKE_PROFIT_PCT):
                sell_price = entry_price * (1 + TAKE_PROFIT_PCT)
                to_sell.append((code, sell_price, "take_profit"))

        # 执行卖出
        for code, sell_price, reason in to_sell:
            pos = positions.pop(code, None)
            if not pos:
                continue
            shares = pos["shares"]
            # 卖出成本
            actual_price = sell_price * (1 - SLIPPAGE_RATE)
            commission = max(actual_price * shares * COMMISSION_RATE, COMMISSION_MIN)
            stamp_tax = actual_price * shares * STAMP_TAX_RATE
            revenue = actual_price * shares - commission - stamp_tax
            capital += revenue
            pnl = revenue - pos["cost"]
            pnl_pct = pnl / pos["cost"] * 100 if pos["cost"] > 0 else 0
            trades.append({
                "code": code,
                "name": stock_data[code]["name"],
                "entry_price": round(pos["entry_price"], 2),
                "exit_price": round(actual_price, 2),
                "shares": shares,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "reason": reason,
                "entry_day": pos["entry_idx"],
                "exit_day": day_idx,
            })

        # 2. 检查加仓条件（持仓中，涨幅>3%且站稳20日均线）
        for code, pos in positions.items():
            if pos.get("add_filled") or code not in stock_data:
                continue
            data = stock_data[code]
            if day_idx >= len(data["closes"]):
                continue
            current_price = data["closes"][day_idx]
            if day_idx >= 20:
                ma20 = sum(data["closes"][day_idx-19:day_idx+1]) / 20
            else:
                ma20 = 0
            entry_price = pos["entry_price"]
            # 加仓条件：涨幅>3%且站稳20日均线
            if current_price >= entry_price * 1.03 and current_price > ma20:
                add_amount = INITIAL_CAPITAL * ADD_POSITION_PCT
                if capital >= add_amount and add_amount > 0:
                    actual_price = current_price * (1 + SLIPPAGE_RATE)
                    add_shares = int(add_amount / actual_price / 100) * 100  # 整手
                    if add_shares >= 100:
                        commission = max(actual_price * add_shares * COMMISSION_RATE, COMMISSION_MIN)
                        total_cost = actual_price * add_shares + commission
                        capital -= total_cost
                        # 更新持仓（加权平均成本）
                        total_shares = pos["shares"] + add_shares
                        total_cost_all = pos["cost"] + total_cost
                        pos["entry_price"] = total_cost_all / total_shares
                        pos["shares"] = total_shares
                        pos["cost"] = total_cost_all
                        pos["add_filled"] = True
                        trades.append({
                            "code": code,
                            "name": stock_data[code]["name"],
                            "entry_price": round(pos["entry_price"], 2),
                            "exit_price": 0,
                            "shares": add_shares,
                            "pnl": 0,
                            "pnl_pct": 0,
                            "reason": "add_position",
                            "entry_day": day_idx,
                            "exit_day": 0,
                        })

        # 3. 扫描买入信号（空仓或持仓<2只时）
        if len(positions) < MAX_POSITIONS:
            candidates = []
            for code, data in stock_data.items():
                if code in positions or day_idx >= len(data["closes"]):
                    continue
                signal = calc_breakout_signal(
                    data["closes"], data["highs"], data["volumes"], day_idx
                )
                if signal["signal"]:
                    candidates.append((code, signal["score"], signal))

            # 按打分排序，取最高分
            candidates.sort(key=lambda x: x[1], reverse=True)
            for code, score, signal in candidates[:MAX_POSITIONS - len(positions)]:
                if len(positions) >= MAX_POSITIONS:
                    break
                data = stock_data[code]
                current_price = data["closes"][day_idx]
                # 底仓买入
                base_amount = INITIAL_CAPITAL * BASE_POSITION_PCT
                if capital >= base_amount and base_amount > 0:
                    actual_price = current_price * (1 + SLIPPAGE_RATE)
                    shares = int(base_amount / actual_price / 100) * 100  # 整手
                    if shares >= 100:
                        commission = max(actual_price * shares * COMMISSION_RATE, COMMISSION_MIN)
                        total_cost = actual_price * shares + commission
                        capital -= total_cost
                        positions[code] = {
                            "shares": shares,
                            "entry_price": actual_price,
                            "entry_idx": day_idx,
                            "cost": total_cost,
                            "base_filled": True,
                            "add_filled": False,
                            "signal_score": score,
                            "position_type": signal.get("position_type", "unknown"),
                        }

        # 4. 记录每日总资产
        position_value = 0
        for code, pos in positions.items():
            if code in stock_data and day_idx < len(stock_data[code]["closes"]):
                position_value += pos["shares"] * stock_data[code]["closes"][day_idx]
        total_value = capital + position_value
        daily_values.append({
            "day": day_idx,
            "capital": round(capital, 2),
            "position_value": round(position_value, 2),
            "total_value": round(total_value, 2),
            "positions": len(positions),
        })

    # 最后平仓
    for code, pos in list(positions.items()):
        if code not in stock_data:
            continue
        data = stock_data[code]
        last_idx = min(end_idx, len(data["closes"]) - 1)
        sell_price = data["closes"][last_idx]
        actual_price = sell_price * (1 - SLIPPAGE_RATE)
        shares = pos["shares"]
        commission = max(actual_price * shares * COMMISSION_RATE, COMMISSION_MIN)
        stamp_tax = actual_price * shares * STAMP_TAX_RATE
        revenue = actual_price * shares - commission - stamp_tax
        capital += revenue
        pnl = revenue - pos["cost"]
        pnl_pct = pnl / pos["cost"] * 100 if pos["cost"] > 0 else 0
        trades.append({
            "code": code,
            "name": data["name"],
            "entry_price": round(pos["entry_price"], 2),
            "exit_price": round(actual_price, 2),
            "shares": shares,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "reason": "end_close",
            "entry_day": pos["entry_idx"],
            "exit_day": last_idx,
        })
    positions = {}

    # 计算绩效指标
    closed_trades = [t for t in trades if t["reason"] != "add_position"]
    win_trades = [t for t in closed_trades if t["pnl"] > 0]
    loss_trades = [t for t in closed_trades if t["pnl"] <= 0]

    total_pnl = capital - INITIAL_CAPITAL
    total_return_pct = total_pnl / INITIAL_CAPITAL * 100

    # 最大回撤
    peak = INITIAL_CAPITAL
    max_drawdown = 0
    for dv in daily_values:
        peak = max(peak, dv["total_value"])
        drawdown = (peak - dv["total_value"]) / peak * 100 if peak > 0 else 0
        max_drawdown = max(max_drawdown, drawdown)

    # 胜率
    win_rate = len(win_trades) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = sum(t["pnl"] for t in win_trades) / len(win_trades) if win_trades else 0
    avg_loss = sum(t["pnl"] for t in loss_trades) / len(loss_trades) if loss_trades else 0
    profit_factor = abs(sum(t["pnl"] for t in win_trades) / sum(t["pnl"] for t in loss_trades)) if loss_trades and sum(t["pnl"] for t in loss_trades) != 0 else float('inf')

    # 输出报告
    print("=" * 60)
    print("📊 回测结果")
    print("=" * 60)
    print(f"初始资金：{INITIAL_CAPITAL:.2f}元")
    print(f"最终资金：{capital:.2f}元")
    print(f"总盈亏：{total_pnl:+.2f}元（{total_return_pct:+.2f}%）")
    print(f"最大回撤：{max_drawdown:.2f}%")
    print()
    print(f"交易次数：{len(closed_trades)}次（不含加仓）")
    print(f"胜率：{win_rate:.1f}%（{len(win_trades)}胜 / {len(loss_trades)}负）")
    print(f"平均盈利：{avg_win:+.2f}元")
    print(f"平均亏损：{avg_loss:+.2f}元")
    print(f"盈亏比：{profit_factor:.2f}" if profit_factor != float('inf') else "盈亏比：∞（无亏损交易）")
    print()

    # 交易明细
    print("📋 交易明细：")
    print("-" * 60)
    for i, t in enumerate(closed_trades, 1):
        reason_map = {"stop_loss": "止损", "take_profit": "止盈", "end_close": "期末平仓"}
        reason = reason_map.get(t["reason"], t["reason"])
        pnl_color = "🟢" if t["pnl"] > 0 else "🔴"
        print(f"  {i:2d}. {t['name']}({t['code']}) "
              f"买入{t['entry_price']:.2f}→卖出{t['exit_price']:.2f} "
              f"{t['shares']}股 {pnl_color}{t['pnl']:+.2f}元({t['pnl_pct']:+.1f}%) [{reason}]")

    # 资金曲线关键点
    print()
    print("📈 资金曲线（每20天）：")
    print("-" * 60)
    for i in range(0, len(daily_values), max(1, len(daily_values) // 8)):
        dv = daily_values[i]
        ret = (dv["total_value"] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        print(f"  第{dv['day']}天：总资产{dv['total_value']:.0f}元 "
              f"({ret:+.1f}%) 持仓{dv['positions']}只 现金{dv['capital']:.0f}元")

    # 保存结果
    result = {
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": round(capital, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "total_trades": len(closed_trades),
        "win_rate": round(win_rate, 1),
        "win_trades": len(win_trades),
        "loss_trades": len(loss_trades),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else None,
        "trades": closed_trades,
        "daily_values": daily_values[::10],  # 每10天保存一个点
    }

    result_file = os.path.join(BASE_DIR, "data", "backtest_1_8_result.json")
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 回测结果已保存：{result_file}")

    return result


if __name__ == "__main__":
    run_backtest()
