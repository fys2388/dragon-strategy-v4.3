# -*- coding: utf-8 -*-
"""信号引擎模块。

A股无做空：所有"做空"逻辑改为「空头规避 AVOID」——仅日志记录、从候选池排除，不推送推荐。

信号优先级：LONG_EXIT > LONG_ENTRY > AVOID > HOLD
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from threading import Lock

import pandas as pd

from . import data_source as ds
from .config import RISK, SIGNAL, TIMEFRAME_ORDER, ZERO_AXIS_EPS, MARKET_GATE
from .trading_calendar import now_bjt

from .macd_indicator import (above_zero_axis, below_zero_axis, calc_macd,
                             check_bullish_divergence, cross_above_zero,
                             is_death_cross, is_golden_cross, red_bar_expanding,
                             recent_golden_cross)


class SignalType(Enum):
    LONG_ENTRY = "LONG_ENTRY"   # 做多入场
    LONG_EXIT = "LONG_EXIT"     # 多头离场（止盈/止损）
    AVOID = "AVOID"             # 空头规避（原做空逻辑）
    HOLD = "HOLD"               # 持有不动


@dataclass
class SignalResult:
    code: str
    name: str
    signal_type: SignalType
    score: float = 0.0
    reason: str = ""
    price: float = 0.0
    dif_daily: Optional[float] = None
    dif_60m: Optional[float] = None
    dif_30m: Optional[float] = None
    dif_15m: Optional[float] = None
    timestamp: str = field(default_factory=lambda: now_bjt().strftime("%Y-%m-%d %H:%M:%S"))
    resonance_levels: List[str] = field(default_factory=list)
    tf_status: Dict[str, bool] = field(default_factory=dict)


class SignalEngine:
    """MACD 多周期共振信号引擎。"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.portfolio_file = os.path.join(self.base_dir, "portfolio_data.json")
        # 逐道闸门拒绝计数：12 个线程并发调用 check_long_entry，需要加锁。
        # 之前只打印「共振信号 0 只」，看不到是哪一道闸门把候选全拒掉了，
        # 排查只能靠猜（2026-09-22 实测就是这样：60min 金叉 6 只、30min 3 只）。
        self._gate_counts: Dict[str, int] = {}
        self._gate_lock = Lock()

    def record_gate(self, gate: str):
        """记录一道闸门拒绝了一个候选。"""
        with self._gate_lock:
            self._gate_counts[gate] = self._gate_counts.get(gate, 0) + 1

    def get_gate_counts(self) -> Dict[str, int]:
        with self._gate_lock:
            return dict(self._gate_counts)

    def reset_gate_counts(self):
        with self._gate_lock:
            self._gate_counts = {}

    # ----------------------------------------------------------
    # 持仓读取
    # ----------------------------------------------------------
    def load_positions(self) -> List[Dict]:
        try:
            with open(self.portfolio_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("positions", [])
        except Exception:
            return []

    def _position_for(self, code: str) -> Optional[Dict]:
        for pos in self.load_positions():
            if str(pos.get("code", "")) == code:
                return pos
        return None

    # ----------------------------------------------------------
    # 多周期 MACD 分析
    # ----------------------------------------------------------
    def _tf_macd(self, code: str, period: str, count: int) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        df = ds.get_kline(code, period, count)
        if df.empty or len(df) < 30:
            return df, pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float)
        df = calc_macd(df)
        return df, df["dif"], df["dea"], df["macd"]

    def _last(self, s: pd.Series) -> Optional[float]:
        if s is None or len(s) == 0 or pd.isna(s.iloc[-1]):
            return None
        return float(s.iloc[-1])

    def _is_dif_dea_bull(self, dif_last: Optional[float], dea_last: Optional[float]) -> bool:
        """DIF>DEA：短期动能优于长期动能（多头状态的通用定义）。"""
        if dif_last is None or dea_last is None:
            return False
        return dif_last > dea_last

    def _tf_status(self, code: str) -> Dict[str, bool]:
        """收集四周期信号状态（用于日志诊断）。"""
        status = {}
        df_d, dif_d, _, _ = self._tf_macd(code, "daily", 120)
        dif_d_last = self._last(dif_d)
        status["daily_above_zero"] = bool(not df_d.empty and dif_d_last is not None and dif_d_last > -ZERO_AXIS_EPS)

        df_60, dif_60, dea_60, _ = self._tf_macd(code, "60m", 200)
        status["tf60_golden"] = bool(not df_60.empty and recent_golden_cross(dif_60, dea_60, lookback=3))

        df_30, dif_30, dea_30, _ = self._tf_macd(code, "30m", 200)
        status["tf30_golden"] = bool(not df_30.empty and recent_golden_cross(dif_30, dea_30, lookback=3))

        df_15, dif_15, _, _ = self._tf_macd(code, "15m", 200)
        status["tf15_cross_zero"] = bool(not df_15.empty and cross_above_zero(dif_15))
        return status

    # ----------------------------------------------------------
    # 入场信号
    # ----------------------------------------------------------
    def check_long_entry(self, code: str, name: str, price: float,
                         mode: str = "auto") -> Optional[SignalResult]:
        """检查做多入场条件（C~H，A/B 由 scanner 前置保证）。

        V2.0 双模式：
        - mode="standard"（大盘≥4分）：严格版，30min要求DIF>0、15min要求上穿零轴、要求价格突破、量比1.2
        - mode="relaxed"（大盘3分）：宽松版，30min仅需金叉、15min仅需金叉、不要求突破、量比1.1
        - mode="auto"：根据当前大盘评分自动选择
        """
        # 自动选择模式
        if mode == "auto":
            try:
                from .market_gate import get_market_score
                score, _, _ = get_market_score()
                mode = "standard" if score >= MARKET_GATE["standard_threshold"] else "relaxed"
            except Exception:
                mode = "relaxed"  # 获取失败时默认宽松，避免错过信号

        mode_cfg = SIGNAL["mode_standard"] if mode == "standard" else SIGNAL["mode_relaxed"]
        vol_min = mode_cfg.get("volume_ratio_min", 1.2)
        vol_max = mode_cfg.get("volume_ratio_max", 3.0)
        min_bull_minute = int(mode_cfg.get("min_bull_minute_tfs", 2))
        reasons = []
        reasons.append(f"模式:{mode}")

        # C. 日线 DIF 在零轴上方或附近（持续状态，必须）
        df_d, dif_d, dea_d, macd_d = self._tf_macd(code, "daily", 120)
        if df_d.empty:
            return None
        dif_d_last = self._last(dif_d)
        if dif_d_last is None or dif_d_last <= -ZERO_AXIS_EPS:
            self.record_gate("C日线DIF零轴下")
            return None
        reasons.append("日线DIF零轴上方/附近")

        # D/E/F. 分钟周期多头状态：DIF > DEA 即算多头（不再要求零轴上方）
        # ⚠️ 2026-09-22 重设计：共振 = "趋势延续"，不再要求突破。
        #   原设计（60min 零轴上方 + 红柱为正、E/F 独立 gate）把候选拒了 60% 在 D 闸门，
        #   剩下的 15 只又被 H 闸门（突破 5 日新高）15/15 全灭——四周期共振（滞后确认）
        #   与突破 5 日新高（领先确认）在时间上互斥，这个逻辑冲突是 0 推荐的最后一层根因。
        #   现在 60/30/15min 统一判定为「DIF>DEA」（短期动能未逆），零轴判定不再要求；
        #   多周期共振核心条件改为「至少 N 个分钟周期多头」（N 由 mode_cfg 决定）。
        #   闸门 H（突破）保留但默认关闭：突破职责完全交给 breakout.py。
        df_60, dif_60, dea_60, macd_60 = self._tf_macd(code, "60m", 200)
        if df_60.empty:
            return None
        dif_60_last = self._last(dif_60)
        dea_60_last = self._last(dea_60)
        tf60_bull = self._is_dif_dea_bull(dif_60_last, dea_60_last)
        tf60_above_zero = bool(dif_60_last is not None and dif_60_last > 0)

        df_30, dif_30, dea_30, _ = self._tf_macd(code, "30m", 200)
        if df_30.empty:
            return None
        dif_30_last = self._last(dif_30)
        dea_30_last = self._last(dea_30)
        tf30_bull = self._is_dif_dea_bull(dif_30_last, dea_30_last)
        tf30_above_zero = bool(dif_30_last is not None and dif_30_last > 0)

        df_15, dif_15, dea_15, _ = self._tf_macd(code, "15m", 200)
        if df_15.empty:
            return None
        dif_15_last = self._last(dif_15)
        dea_15_last = self._last(dea_15)
        tf15_bull = self._is_dif_dea_bull(dif_15_last, dea_15_last)
        tf15_above_zero = bool(dif_15_last is not None and dif_15_last > 0)

        # 多周期共振核心条件：至少 N 个分钟周期多头
        bull_minute_tfs = sum(1 for x in (tf60_bull, tf30_bull, tf15_bull) if x)
        if bull_minute_tfs < min_bull_minute:
            self.record_gate(f"I分钟多头不足{bull_minute_tfs}/{min_bull_minute}")
            return None
        bull_labels = []
        if tf60_bull: bull_labels.append("60min")
        if tf30_bull: bull_labels.append("30min")
        if tf15_bull: bull_labels.append("15min")
        reasons.append("分钟多头:" + "/".join(bull_labels))

        # G. 量能确认：量比必须落在 [vol_min, vol_max] 区间
        # ⚠️ 双向闸门：既要放量（≥vol_min）确认资金进场，又要排除爆量出货（≥vol_max）。
        #   原实现只有下限，一只当日量比 8.0 的爆量出货股会通过闸门。
        if len(df_d) < 6:
            self.record_gate("G量能数据不足")
            return None
        vol_now = float(df_d["volume"].iloc[-1])
        vol_5d = float(df_d["volume"].iloc[-6:-1].mean())
        if vol_5d <= 0:
            self.record_gate("G量能数据不足")
            return None
        vol_ratio_val = vol_now / vol_5d
        if vol_ratio_val < vol_min:
            self.record_gate(f"G量能不足×{vol_min}")
            return None
        if vol_ratio_val > vol_max:
            self.record_gate(f"G爆量×{vol_ratio_val:.1f}")
            return None
        reasons.append(f"量比{vol_ratio_val:.1f}(区间{vol_min}~{vol_max})")

        # H. 价格突破：默认关闭，交给 breakout.py 处理
        if mode_cfg.get("require_breakout", False):
            if len(df_60) < SIGNAL["breakout_lookback_60m"]:
                self.record_gate("H突破数据不足")
                return None
            close_now = float(df_d["close"].iloc[-1])
            high_20 = float(df_60["high"].iloc[-SIGNAL["breakout_lookback_60m"]:].max())
            if close_now <= high_20:
                self.record_gate("H未突破60min平台")
                return None
            reasons.append(f"突破60min平台{high_20:.2f}")

        # I. 共振强度打分（量纲 1.0~3.05，与 adaptive_config.min_score=2.0 同口径）
        # ⚠️ 2026-09-22 重写：打分按**实际确认到的状态**逐项累加。
        #   基础 1.0 = 日线多头（C 闸门已过）。
        #   60min 零轴上方 +0.5 / 仅 DIF>DEA +0.25（零轴判定是加分项，不是门槛）
        #   30min +0.4 / +0.2；15min +0.3 / +0.15
        #   量比在 1.2~2.5 之间 +0.3（健康放量）；否则 +0.15
        #   无顶背离 +0.1
        #   合计范围 1.0~3.05，与 adaptive_config.min_score 量纲一致。
        score = 1.0
        resonance = ["日线"]
        if tf60_bull:
            score += 0.5 if tf60_above_zero else 0.25
            resonance.append("60min零轴上" if tf60_above_zero else "60min多头")
        if tf30_bull:
            score += 0.4 if tf30_above_zero else 0.2
            resonance.append("30min零轴上" if tf30_above_zero else "30min多头")
        if tf15_bull:
            score += 0.3 if tf15_above_zero else 0.15
            resonance.append("15min零轴上" if tf15_above_zero else "15min多头")

        # 量比加分：1.2~2.5 视为健康放量（低于 1.2 已被 G 闸门拒绝，高于 3.0 已拒绝）
        if 1.2 <= vol_ratio_val <= 2.5:
            score += 0.3
        else:
            score += 0.15

        # 无顶背离加分
        try:
            if not check_bullish_divergence(df_d["close"], dif_d):
                score += 0.1
        except Exception:
            pass

        # 宽松档信号略降权
        if mode == "relaxed":
            score *= 0.9

        # tf_status 用于日志与外部读取（含旧字段兼容）
        tf_status_out = {
            "daily_above_zero": bool(dif_d_last is not None and dif_d_last > -ZERO_AXIS_EPS),
            "tf60_bull": tf60_bull, "tf30_bull": tf30_bull, "tf15_bull": tf15_bull,
            "tf60_above_zero": tf60_above_zero, "tf30_above_zero": tf30_above_zero,
            "tf15_above_zero": tf15_above_zero,
            "bull_minute_tfs": bull_minute_tfs,
            # 兼容旧字段（外部可能读）
            "tf60_golden": tf60_bull,
            "tf30_golden": tf30_bull,
            "tf15_cross_zero": tf15_bull,
        }

        return SignalResult(
            code=code, name=name, signal_type=SignalType.LONG_ENTRY, score=round(score, 2),
            reason="；".join(reasons), price=round(price, 2),
            dif_daily=dif_d_last, dif_60m=dif_60_last,
            dif_30m=dif_30_last, dif_15m=dif_15_last,
            resonance_levels=resonance,
            tf_status=tf_status_out,
        )
    # ----------------------------------------------------------
    # 离场信号
    # ----------------------------------------------------------
    def check_long_exit(self, code: str, name: str, price: float, position: Optional[Dict]) -> Optional[SignalResult]:
        """检查多头离场条件（任一满足即离场）。"""
        reasons = []
        entry_price = float(position.get("entry_price", 0)) if position else 0.0

        df_d, dif_d, dea_d, _ = self._tf_macd(code, "daily", 120)
        if df_d.empty:
            return None
        dif_d_last = self._last(dif_d)
        df_60, dif_60, dea_60, _ = self._tf_macd(code, "60m", 200)
        dif_60_last = self._last(dif_60)

        # A. 日线零轴上方死叉
        if dif_d_last and dif_d_last > 0 and is_death_cross(dif_d, dea_d):
            reasons.append("日线零轴上死叉")

        # B. 60分钟死叉 + 顶背离
        if not df_60.empty and is_death_cross(dif_60, dea_60):
            if check_bullish_divergence(df_60["close"], dif_60):
                reasons.append("60min死叉+顶背离")

        # C. 止盈：浮盈≥10% 卖50%；≥15% 清仓
        if entry_price > 0:
            profit = (price - entry_price) / entry_price
            if profit >= RISK["take_profit_2_pct"]:
                reasons.append(f"浮盈{profit * 100:.1f}%≥{RISK['take_profit_2_pct'] * 100:.0f}%清仓")
            elif profit >= RISK["take_profit_1_pct"]:
                reasons.append(f"浮盈{profit * 100:.1f}%≥{RISK['take_profit_1_pct'] * 100:.0f}%减半仓")

            # D. 硬性止损
            if profit <= -RISK["stop_loss_pct"]:
                reasons.append(f"浮亏{profit * 100:.1f}%≤-{RISK['stop_loss_pct'] * 100:.0f}%硬止损")

        # E. 日线 DIF 跌破 -0.05
        if dif_d_last and dif_d_last < -ZERO_AXIS_EPS:
            reasons.append(f"日线DIF{dif_d_last:.3f}跌破零轴")

        if not reasons:
            return None
        return SignalResult(
            code=code, name=name, signal_type=SignalType.LONG_EXIT,
            reason="；".join(reasons), price=round(price, 2),
            dif_daily=dif_d_last, dif_60m=dif_60_last,
        )

    # ----------------------------------------------------------
    # 空头规避（原做空逻辑）
    # ----------------------------------------------------------
    def check_avoid(self, code: str) -> bool:
        """日线 DIF<-0.05 或 60min 死叉且 DIF<0 → 规避。"""
        _, dif_d, _, _ = self._tf_macd(code, "daily", 120)
        _, dif_60, dea_60, _ = self._tf_macd(code, "60m", 200)
        if below_zero_axis(self._last(dif_d)):
            return True
        if not dif_60.empty and is_death_cross(dif_60, dea_60):
            if self._last(dif_60) and self._last(dif_60) < 0:
                return True
        return False

    # ----------------------------------------------------------
    # 主分析入口
    # ----------------------------------------------------------
    def analyze_stock(self, code: str, name: str = "", price: float = 0.0) -> SignalResult:
        """分析单只股票，返回综合信号。

        优先级：LONG_EXIT > LONG_ENTRY > AVOID > HOLD
        """
        if price <= 0:
            quotes = ds.get_realtime_quotes([code])
            price = quotes.get(code, {}).get("price", 0.0)
        if not name:
            quotes = ds.get_realtime_quotes([code])
            name = quotes.get(code, {}).get("name", code)

        position = self._position_for(code)
        tf_status = self._tf_status(code)

        # 1. 持仓中优先检查离场
        if position:
            exit_sig = self.check_long_exit(code, name, price, position)
            if exit_sig:
                exit_sig.tf_status = tf_status
                return exit_sig

        # 2. 入场
        entry_sig = self.check_long_entry(code, name, price)
        if entry_sig:
            entry_sig.tf_status = tf_status
            return entry_sig

        # 3. 空头规避
        if self.check_avoid(code):
            return SignalResult(code=code, name=name, signal_type=SignalType.AVOID,
                                reason="空头规避：日线DIF零轴下方/60min死叉", price=round(price, 2),
                                tf_status=tf_status)

        # 4. 持有/无信号
        return SignalResult(code=code, name=name, signal_type=SignalType.HOLD,
                            reason="无共振信号", price=round(price, 2), tf_status=tf_status)
