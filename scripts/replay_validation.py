# -*- coding: utf-8 -*-
"""历史回放验证脚本。

用replay_engine对三策略在过去1年的数据上进行回放验证，
输出各策略的胜率、收益、回撤等指标，推送报告到飞书。
"""
from __future__ import annotations

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance.replay_engine import init_replay_engine
from strategies.macd_resonance import data_source as ds
import pandas as pd
import numpy as np


def macd_cross_signal(history_df: pd.DataFrame, idx: int) -> tuple:
    """MACD金叉买入信号，死叉卖出。"""
    if idx < 35:
        return False, False
    close = history_df["close"].astype(float).values
    # 计算MACD
    ema12 = pd.Series(close).ewm(span=12).mean().values
    ema26 = pd.Series(close).ewm(span=26).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9).mean().values
    macd = (dif - dea) * 2

    # 金叉：DIF上穿DEA
    golden_cross = dif[idx-1] < dea[idx-1] and dif[idx] > dea[idx]
    # 死叉：DIF下穿DEA
    death_cross = dif[idx-1] > dea[idx-1] and dif[idx] < dea[idx]
    # 价格在MA20上方
    ma20 = pd.Series(close).rolling(20).mean().values
    above_ma20 = close[idx] > ma20[idx] if not np.isnan(ma20[idx]) else False

    should_buy = golden_cross and above_ma20
    should_sell = death_cross
    return should_buy, should_sell


def oversold_signal(history_df: pd.DataFrame, idx: int) -> tuple:
    """超跌反弹信号：20日跌20%+RSI<30买入，反弹10%卖出。"""
    if idx < 25:
        return False, False
    close = history_df["close"].astype(float).values
    # 20日跌幅
    drop_20d = (close[idx] / close[idx-20] - 1) * 100
    # RSI
    delta = pd.Series(close).diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean().values
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().values
    rs = gain / (loss + 1e-10)
    rsi = 100 - 100 / (1 + rs)

    should_buy = drop_20d < -20 and rsi[idx] < 35
    should_sell = False  # 用止盈止损代替
    return should_buy, should_sell


def breakout_signal(history_df: pd.DataFrame, idx: int) -> tuple:
    """突破信号：突破20日新高+放量买入，跌破MA10卖出。"""
    if idx < 25:
        return False, False
    close = history_df["close"].astype(float).values
    high = history_df["high"].astype(float).values
    volume = history_df["volume"].astype(float).values

    # 突破20日新高
    high_20d = high[idx-20:idx].max()
    breakout = close[idx] > high_20d
    # 放量（5日均量>20日均量1.5倍）
    vol_5 = volume[idx-5:idx].mean()
    vol_20 = volume[idx-20:idx].mean()
    volume_surge = vol_5 > vol_20 * 1.5 if vol_20 > 0 else False
    # 均线多头
    ma5 = pd.Series(close).rolling(5).mean().values
    ma10 = pd.Series(close).rolling(10).mean().values
    ma20 = pd.Series(close).rolling(20).mean().values
    bullish = ma5[idx] > ma10[idx] > ma20[idx] if not np.isnan(ma20[idx]) else False

    should_buy = breakout and volume_surge and bullish
    # 跌破MA10卖出
    should_sell = close[idx] < ma10[idx] if not np.isnan(ma10[idx]) else False
    return should_buy, should_sell


def run_replay_for_strategy(stock_codes: list, signal_func, strategy_name: str,
                            position_pct: float = 0.3, stop_loss: float = 0.05,
                            take_profit: float = 0.10) -> dict:
    """对多只股票运行回放，汇总结果。"""
    engine = init_replay_engine(initial_capital=10000)
    all_trades = []
    total_return = 0
    count = 0

    for code in stock_codes:
        try:
            df = ds.get_kline_daily(code, count=300)
            if df.empty or len(df) < 60:
                continue
            result = engine.replay(code, df, signal_func,
                                   position_pct=position_pct,
                                   stop_loss_pct=stop_loss,
                                   take_profit_pct=take_profit,
                                   max_holding_days=15)
            if result.get("total_trades", 0) > 0:
                all_trades.extend(result.get("trades", []))
                total_return += result.get("total_return_pct", 0)
                count += 1
        except Exception as e:
            print(f"  {code} 回放失败: {e}")

    if not all_trades:
        return {"strategy": strategy_name, "total_trades": 0, "message": "无交易"}

    returns = [t["return_pct"] for t in all_trades]
    wins = [r for r in returns if r > 0]

    return {
        "strategy": strategy_name,
        "stocks_tested": count,
        "total_trades": len(all_trades),
        "win_rate": round(len(wins) / len(all_trades) * 100, 1),
        "avg_return_pct": round(sum(returns) / len(returns), 2),
        "max_return_pct": round(max(returns), 2),
        "min_return_pct": round(min(returns), 2),
        "avg_holding_days": round(sum(t["holding_days"] for t in all_trades) / len(all_trades), 1),
        "total_cost": round(sum(t["total_cost"] for t in all_trades), 2),
    }


def send_feishu(text: str):
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL")
        return
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
        print(f"✅ 飞书推送完成 HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


def main():
    print("=" * 50)
    print("🔄 历史回放验证")
    print("=" * 50)

    # 加载优质股票池，取前20只
    pool_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "quality_pool.json")
    try:
        with open(pool_file, "r", encoding="utf-8") as f:
            pool = json.load(f)
        test_codes = [item["code"] for item in pool[:20]]
    except Exception:
        test_codes = ["600519", "000858", "601318", "000333", "600036",
                      "002594", "601012", "002475", "600276", "601888",
                      "000651", "600887", "002304", "603288", "000568",
                      "600030", "601398", "600000", "000001", "600036"]

    print(f"回测股票数：{len(test_codes)}只")

    # 三策略回放
    strategies = [
        ("MACD金叉", macd_cross_signal, 0.3, 0.05, 0.10),
        ("超跌反弹", oversold_signal, 0.25, 0.04, 0.08),
        ("趋势突破", breakout_signal, 0.3, 0.04, 0.08),
    ]

    results = []
    for name, signal_func, pos, sl, tp in strategies:
        print(f"\n{'='*50}")
        print(f"运行策略：{name}")
        print(f"{'='*50}")
        result = run_replay_for_strategy(test_codes, signal_func, name, pos, sl, tp)
        results.append(result)
        print(f"  交易次数：{result.get('total_trades', 0)}")
        print(f"  胜率：{result.get('win_rate', 0)}%")
        print(f"  平均收益：{result.get('avg_return_pct', 0)}%")

    # 生成报告
    lines = [
        "🔄 历史回放验证报告",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"回测股票：{len(test_codes)}只 | 回测周期：约1年（300交易日）",
        f"交易成本：佣金万2.5(最低5元) + 印花税千1(卖出) + 滑点0.1%",
        "",
    ]

    for r in results:
        if r.get("total_trades", 0) == 0:
            lines.append(f"【{r['strategy']}】无交易信号")
            continue
        lines.append(f"【{r['strategy']}】")
        lines.append(f"  交易次数：{r['total_trades']}次")
        lines.append(f"  胜率：{r['win_rate']}%")
        lines.append(f"  平均收益：{r['avg_return_pct']}%")
        lines.append(f"  最佳单笔：{r['max_return_pct']}%")
        lines.append(f"  最差单笔：{r['min_return_pct']}%")
        lines.append(f"  平均持仓：{r['avg_holding_days']}天")
        lines.append(f"  总交易成本：{r['total_cost']}元")
        lines.append("")

    # 策略对比结论
    valid_results = [r for r in results if r.get("total_trades", 0) > 0]
    if valid_results:
        best = max(valid_results, key=lambda x: x.get("avg_return_pct", 0))
        most_trades = max(valid_results, key=lambda x: x.get("total_trades", 0))
        lines.append("📊 结论：")
        lines.append(f"  收益最优：{best['strategy']}（平均{best['avg_return_pct']}%）")
        lines.append(f"  信号最多：{most_trades['strategy']}（{most_trades['total_trades']}次）")
        if best["win_rate"] < 50:
            lines.append(f"  ⚠️ {best['strategy']}胜率{best['win_rate']}%<50%，需优化入场条件")

    report = "\n".join(lines)
    print("\n" + report)
    send_feishu(report)


if __name__ == "__main__":
    main()
