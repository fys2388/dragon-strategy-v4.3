"""
绩效追踪模块

功能：
- 每日记录组合表现（权益曲线、持仓、交易）
- 计算实时夏普比率、索提诺比率、卡玛比率
- 追踪最大回撤变化
- 策略衰减监测（月度/季度胜率、收益变化）
- 保存绩效历史到 data/performance_history.json

用法：
    from src.risk.performance_tracker import PerformanceTracker
    tracker = PerformanceTracker()
    tracker.record_daily(snapshot)  # 每日记录
    metrics = tracker.get_metrics()  # 获取绩效指标
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """绩效追踪器"""

    def __init__(self, history_file: str = None):
        self.history_file = history_file or str(DATA_DIR / "performance_history.json")
        self.history: Dict = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "daily_records": [],      # 每日快照
            "trades": [],             # 所有交易记录
            "signals": [],            # 所有信号记录
            "metrics": {},            # 当前绩效指标
            "decay_log": [],          # 策略衰减日志
        }
        self._load_history()

    def _load_history(self):
        """加载历史绩效数据"""
        path = Path(self.history_file)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
                logger.info(f"加载绩效历史: {len(self.history['daily_records'])} 天, {len(self.history['trades'])} 笔交易")
            except Exception as e:
                logger.warning(f"加载绩效历史失败: {e}")

    def _save_history(self):
        """保存绩效历史"""
        path = Path(self.history_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"保存绩效历史失败: {e}")

    # ────────────────────────────────────────────
    # 每日记录
    # ────────────────────────────────────────────
    def record_daily(self, snapshot: Dict):
        """
        记录每日快照

        Args:
            snapshot: {
                "date": "2026-10-26",
                "total_equity": 100000.0,
                "total_positions": 2,
                "total_cost": 50000.0,
                "total_pnl": 1200.0,
                "total_pnl_pct": 2.4,
                "market_gate_level": "weak",
                "market_gate_score": 3.1,
                "new_signals": [],       # 当日新信号
                "closed_trades": [],     # 当日平仓交易
                "holdings": []           # 当日持仓
            }
        """
        today = snapshot.get("date", datetime.now().strftime("%Y-%m-%d"))

        # 避免重复记录
        existing = [r for r in self.history["daily_records"] if r["date"] == today]
        if existing:
            self.history["daily_records"] = [r for r in self.history["daily_records"] if r["date"] != today]

        # 添加新记录
        record = {
            "date": today,
            "total_equity": snapshot.get("total_equity", 0),
            "total_positions": snapshot.get("total_positions", 0),
            "total_cost": snapshot.get("total_cost", 0),
            "total_pnl": snapshot.get("total_pnl", 0),
            "total_pnl_pct": snapshot.get("total_pnl_pct", 0),
            "market_gate_level": snapshot.get("market_gate_level", "unknown"),
            "market_gate_score": snapshot.get("market_gate_score", 0),
            "new_signals_count": len(snapshot.get("new_signals", [])),
            "closed_trades_count": len(snapshot.get("closed_trades", [])),
            "holdings": snapshot.get("holdings", []),
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        self.history["daily_records"].append(record)
        self.history["daily_records"].sort(key=lambda r: r["date"])

        # 记录新信号
        for sig in snapshot.get("new_signals", []):
            self.history["signals"].append({
                "date": today,
                "code": sig.get("code", ""),
                "name": sig.get("name", ""),
                "signal_type": sig.get("signal_type", ""),
                "entry_price": sig.get("entry_price", 0),
                "score": sig.get("score", 0),
            })

        # 记录平仓交易
        for trade in snapshot.get("closed_trades", []):
            self.history["trades"].append({
                "date": today,
                "code": trade.get("code", ""),
                "name": trade.get("name", ""),
                "entry_price": trade.get("entry_price", 0),
                "exit_price": trade.get("exit_price", 0),
                "pnl_pct": trade.get("pnl_pct", 0),
                "exit_reason": trade.get("exit_reason", ""),
                "holding_days": trade.get("holding_days", 0),
            })

        # 更新绩效指标
        self._update_metrics()

        # 检测策略衰减
        self._check_strategy_decay()

        self._save_history()
        logger.info(f"绩效记录已更新: {today}, 权益={record['total_equity']:.2f}, 持仓={record['total_positions']}")

    def record_trade(self, trade: Dict):
        """单独记录一笔交易"""
        self.history["trades"].append({
            "date": trade.get("date", datetime.now().strftime("%Y-%m-%d")),
            "code": trade.get("code", ""),
            "name": trade.get("name", ""),
            "entry_price": trade.get("entry_price", 0),
            "exit_price": trade.get("exit_price", 0),
            "pnl_pct": trade.get("pnl_pct", 0),
            "exit_reason": trade.get("exit_reason", ""),
            "holding_days": trade.get("holding_days", 0),
            "signal_type": trade.get("signal_type", ""),
        })
        self._update_metrics()
        self._save_history()

    # ────────────────────────────────────────────
    # 绩效指标计算
    # ────────────────────────────────────────────
    def _update_metrics(self):
        """计算并更新所有绩效指标"""
        daily = self.history["daily_records"]
        trades = self.history["trades"]

        if not daily:
            return

        # 基础指标
        initial_equity = daily[0]["total_equity"] if daily else 0
        current_equity = daily[-1]["total_equity"]
        total_return_pct = (current_equity - initial_equity) / initial_equity * 100 if initial_equity > 0 else 0

        # 权益曲线
        equities = [r["total_equity"] for r in daily]

        # 最大回撤
        max_drawdown = 0
        peak = equities[0] if equities else 0
        drawdown_series = []
        for eq in equities:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            drawdown_series.append(dd)
            max_drawdown = max(max_drawdown, dd)

        # 夏普比率（基于日收益率）
        if len(equities) >= 2:
            daily_returns = [(equities[i] - equities[i-1]) / equities[i-1] for i in range(1, len(equities))]
            if len(daily_returns) > 1 and np.std(daily_returns) > 0:
                sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(250))
            else:
                sharpe = 0
        else:
            sharpe = 0
            daily_returns = []

        # 索提诺比率
        downside_returns = [r for r in daily_returns if r < 0]
        if len(downside_returns) > 0 and np.std(downside_returns) > 0:
            sortino = float(np.mean(daily_returns) / np.std(downside_returns) * np.sqrt(250))
        else:
            sortino = 0

        # 卡玛比率
        annualized_return = total_return_pct * (250 / max(len(daily), 1)) if daily else 0
        calmar = annualized_return / max_drawdown if max_drawdown > 0 else 0

        # 交易统计
        total_trades = len(trades)
        wins = len([t for t in trades if t.get("pnl_pct", 0) > 0])
        losses = total_trades - wins
        win_rate = wins / total_trades * 100 if total_trades > 0 else 0

        win_pnls = [t["pnl_pct"] for t in trades if t.get("pnl_pct", 0) > 0]
        loss_pnls = [t["pnl_pct"] for t in trades if t.get("pnl_pct", 0) <= 0]
        avg_win = float(np.mean(win_pnls)) if win_pnls else 0
        avg_loss = float(np.mean(loss_pnls)) if loss_pnls else 0
        profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # 更新指标
        self.history["metrics"] = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "initial_equity": round(initial_equity, 2),
            "current_equity": round(current_equity, 2),
            "total_return_pct": round(total_return_pct, 2),
            "annualized_return_pct": round(annualized_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "current_drawdown_pct": round(drawdown_series[-1], 2) if drawdown_series else 0,
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "trading_days": len(daily),
        }

    def _check_strategy_decay(self):
        """检测策略衰减"""
        daily = self.history["daily_records"]
        if len(daily) < 20:
            return

        # 最近20天 vs 之前20天
        recent = daily[-20:]
        previous = daily[-40:-20] if len(daily) >= 40 else daily[:20]

        if not recent or not previous:
            return

        # 计算两个时期的表现
        recent_equity_start = previous[-1]["total_equity"] if previous else daily[0]["total_equity"]
        recent_equity_end = recent[-1]["total_equity"]
        recent_return = (recent_equity_end - recent_equity_start) / recent_equity_start * 100 if recent_equity_start > 0 else 0

        prev_equity_start = previous[0]["total_equity"]
        prev_equity_end = previous[-1]["total_equity"]
        prev_return = (prev_equity_end - prev_equity_start) / prev_equity_start * 100 if prev_equity_start > 0 else 0

        # 衰减检测
        decay = False
        decay_reason = ""

        if prev_return > 0 and recent_return < 0:
            decay = True
            decay_reason = f"从 +{prev_return:.1f}% 转为 {recent_return:.1f}%"
        elif prev_return > 5 and recent_return < 0:
            decay = True
            decay_reason = f"从 +{prev_return:.1f}% 转为 {recent_return:.1f}%"
        elif recent_return < -5:
            decay = True
            decay_reason = f"近期大幅回撤 {recent_return:.1f}%"

        if decay:
            decay_entry = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "period": "20天滑动窗口",
                "previous_return_pct": round(prev_return, 2),
                "recent_return_pct": round(recent_return, 2),
                "reason": decay_reason,
                "severity": "high" if recent_return < -10 else "medium",
            }
            self.history["decay_log"].append(decay_entry)
            logger.warning(f"⚠️ 策略衰减检测: {decay_reason}")

    # ────────────────────────────────────────────
    # 查询接口
    # ────────────────────────────────────────────
    def get_metrics(self) -> Dict:
        """获取当前绩效指标"""
        return self.history.get("metrics", {})

    def get_daily_history(self, days: int = 30) -> List[Dict]:
        """获取最近N天的绩效历史"""
        records = self.history.get("daily_records", [])
        return records[-days:]

    def get_trades(self, limit: int = 50) -> List[Dict]:
        """获取最近N笔交易"""
        trades = self.history.get("trades", [])
        return trades[-limit:]

    def get_decay_log(self) -> List[Dict]:
        """获取策略衰减日志"""
        return self.history.get("decay_log", [])

    def get_summary(self) -> Dict:
        """获取绩效摘要"""
        metrics = self.get_metrics()
        decay_log = self.get_decay_log()
        daily = self.get_daily_history(7)

        return {
            "metrics": metrics,
            "recent_daily": daily,
            "decay_warnings": decay_log[-5:],
            "total_records": len(self.history.get("daily_records", [])),
            "total_trades": len(self.history.get("trades", [])),
        }

    # ────────────────────────────────────────────
    # 报告生成
    # ────────────────────────────────────────────
    def generate_report(self) -> str:
        """生成绩效报告文本"""
        m = self.get_metrics()
        if not m:
            return "暂无绩效数据"

        lines = [
            "📊 绩效追踪报告",
            "=" * 50,
            f"记录天数: {m.get('trading_days', 0)}",
            f"初始资金: {m.get('initial_equity', 0):,.2f} 元",
            f"当前资金: {m.get('current_equity', 0):,.2f} 元",
            f"总收益率: {m.get('total_return_pct', 0):+.2f}%",
            f"年化收益: {m.get('annualized_return_pct', 0):+.2f}%",
            "",
            "📈 绩效指标",
            f"  夏普比率:   {m.get('sharpe_ratio', 0):.2f}",
            f"  索提诺比率: {m.get('sortino_ratio', 0):.2f}",
            f"  卡玛比率:   {m.get('calmar_ratio', 0):.2f}",
            f"  最大回撤:   {m.get('max_drawdown_pct', 0):.2f}%",
            f"  当前回撤:   {m.get('current_drawdown_pct', 0):.2f}%",
            "",
            "📋 交易统计",
            f"  总交易: {m.get('total_trades', 0)}",
            f"  胜率:   {m.get('win_rate_pct', 0):.1f}%",
            f"  盈亏比: {m.get('profit_loss_ratio', 0):.2f}",
            f"  平均盈利: {m.get('avg_win_pct', 0):+.2f}%",
            f"  平均亏损: {m.get('avg_loss_pct', 0):+.2f}%",
        ]

        # 衰减警告
        decay = self.get_decay_log()
        if decay:
            lines.append("")
            lines.append("⚠️ 策略衰减警告")
            for d in decay[-3:]:
                lines.append(f"  [{d['severity']}] {d['date']}: {d['reason']}")

        return "\n".join(lines)


# 全局实例
_tracker = None

def get_tracker() -> PerformanceTracker:
    """获取全局绩效追踪器"""
    global _tracker
    if _tracker is None:
        _tracker = PerformanceTracker()
    return _tracker
