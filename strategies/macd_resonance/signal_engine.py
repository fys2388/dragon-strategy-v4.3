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
        vol_min = mode_cfg["volume_ratio_min"]
        reasons = []
        reasons.append(f"模式:{mode}")

        # C. 日线 DIF 在零轴上方或附近（持续状态）
        df_d, dif_d, dea_d, macd_d = self._tf_macd(code, "daily", 120)
        if df_d.empty:
            return None
        dif_d_last = self._last(dif_d)
        if dif_d_last is None or dif_d_last <= -ZERO_AXIS_EPS:
            self.record_gate("C日线DIF零轴下")
            return None
        reasons.append("日线DIF零轴上方/附近")

        # D. 60分钟多头状态：DIF 在零轴上方 或 近 N 根金叉（不再要求瞬时金叉）
        # ⚠️ 原实现要求 recent_golden_cross(lookback=3) + DIF>0 + 红柱逐根放大，
        #   三个条件里两个是瞬时事件。实测 104 只候选中 60min 瞬时金叉仅 6 只，
        #   与日线持续状态取交集后必然为空。见 docs/HANDOFF.md §6.4.1。
        df_60, dif_60, dea_60, macd_60 = self._tf_macd(code, "60m", 200)
        if df_60.empty:
            return None
        dif_60_last = self._last(dif_60)
        tf60_golden = bool(recent_golden_cross(dif_60, dea_60,
                                                lookback=mode_cfg.get("tf60_golden_lookback", 3)))
        tf60_above_zero = bool(dif_60_last is not None and dif_60_last > 0)
        if mode_cfg.get("tf60_state_or_cross", True):
            # 多头状态：零轴上方 或 近 N 根金叉
            if not (tf60_above_zero or tf60_golden):
                self.record_gate("D60min非多头")
                return None
            reasons.append("60min零轴上方" if tf60_above_zero else f"60min近{mode_cfg.get('tf60_golden_lookback', 3)}根金叉")
        else:
            # 旧口径：必须刚发生金叉
            if not (tf60_golden and tf60_above_zero):
                self.record_gate("D60min非多头")
                return None
            reasons.append("60min金叉")

        # 红柱：标准口径要求逐根放大（瞬时），状态口径只要红柱为正（DIF>DEA）
        macd_60_last = self._last(macd_60)
        if mode_cfg.get("require_red_bar_expanding", False):
            if not red_bar_expanding(macd_60):
                self.record_gate("D60min红柱未放大")
                return None
            reasons.append("60min红柱放大")
        else:
            if macd_60_last is None or macd_60_last <= 0:
                self.record_gate("D60min红柱未放大")
                return None
            reasons.append("60min红柱为正")

        # E. 30分钟多头状态：同 60min，标准档偏好零轴上方，宽松档接受金叉
        df_30, dif_30, dea_30, _ = self._tf_macd(code, "30m", 200)
        if df_30.empty:
            return None
        dif_30_last = self._last(dif_30)
        tf30_golden = bool(recent_golden_cross(dif_30, dea_30,
                                                lookback=mode_cfg.get("tf30_golden_lookback", 3)))
        tf30_above_zero = bool(dif_30_last is not None and dif_30_last > 0)
        if mode_cfg.get("tf30_state_or_cross", True):
            # 标准档：零轴上方（更稳）或近 N 根金叉；宽松档同样接受二者其一
            if not (tf30_above_zero or tf30_golden):
                self.record_gate("E30min非多头")
                return None
            reasons.append("30min零轴上方" if tf30_above_zero else f"30min近{mode_cfg.get('tf30_golden_lookback', 3)}根金叉")
        else:
            if not tf30_golden:
                self.record_gate("E30min非多头")
                return None
            if mode_cfg["tf30_require_dif_above_zero"] and not tf30_above_zero:
                self.record_gate("E30min非多头")
                return None
            reasons.append("30min金叉零轴上" if tf30_above_zero else "30min金叉")

        # F. 15分钟：标准档要求零轴上方，宽松档「零轴上方 或 金叉」即可
        # ★ 时间尺度错配修复（docs/HANDOFF.md §6.4.1 遗留项）：
        #   日线 MACD 是持续状态，分钟级金叉/上穿零轴是瞬时事件。原实现要求
        #   60/30/15min 同时处于金叉态，三个瞬时事件在同一时段同时命中的概率极低——
        #   实测 80 只候选里 60min 金叉仅 5 只、30min 仅 4 只、15min 上穿零轴仅 3 只，
        #   交集必然为空 → 共振策略长期 0 推荐（另一个独立根因是 min_score 量纲错位，
        #   已在 adaptive_config.MACD_PARAMS 修掉）。
        #   现在把「必须刚发生金叉/上穿」改成「处于多头状态」，
        #   仍保留多周期同向这个核心，只是不再赌三个瞬时事件撞在同一根 K 线上。
        df_15, dif_15, dea_15, _ = self._tf_macd(code, "15m", 200)
        if df_15.empty:
            return None
        dif_15_last = self._last(dif_15)
        tf15_golden = bool(recent_golden_cross(dif_15, dea_15, lookback=3))
        tf15_above_zero = bool(dif_15_last is not None and dif_15_last > 0)

        if mode_cfg["tf15_require_cross_zero"]:
            # 标准档：15min DIF 必须已在零轴上方
            if not tf15_above_zero:
                self.record_gate("F15min非多头")
                return None
            reasons.append("15min零轴上方")
        else:
            # 宽松档：零轴上方 或 近3根金叉，满足其一即可
            if not (tf15_above_zero or tf15_golden):
                self.record_gate("F15min非多头")
                return None
            reasons.append("15min零轴上方" if tf15_above_zero else "15min金叉")

        # G. 量能确认：当日成交量 > 前5日均量 × 模式对应阈值
        if len(df_d) < 6:
            self.record_gate("G量能数据不足")
            return None
        vol_now = float(df_d["volume"].iloc[-1])
        vol_5d = float(df_d["volume"].iloc[-6:-1].mean())
        if vol_5d <= 0 or vol_now <= vol_5d * vol_min:
            self.record_gate(f"G量能不足×{vol_min}")
            return None
        reasons.append(f"量能{vol_now / vol_5d:.1f}倍(阈值{vol_min})")

        # H. 价格突破：标准档强制，宽松档跳过
        if mode_cfg["require_breakout"]:
            if len(df_60) < SIGNAL["breakout_lookback_60m"]:
                self.record_gate("H突破数据不足")
                return None
            close_now = float(df_d["close"].iloc[-1])
            high_20 = float(df_60["high"].iloc[-SIGNAL["breakout_lookback_60m"]:].max())
            if close_now <= high_20:
                self.record_gate("H未突破60min平台")
                return None
            reasons.append(f"突破60min平台{high_20:.2f}")

        # 共振强度打分（量纲 1.0~4.0，与 adaptive_config.min_score 同口径）
        # ⚠️ 2026-09-22 重写：原打分硬编码「60min 共振 +1.5」，
        #   但闸门已改成状态型（零轴上方 或 近期金叉），两个都算通过——
        #   于是无论实际共振多弱，标准档信号都恒打 3.5 分，min_score 过滤形同虚设。
        #   现在按各周期**实际确认到的状态**逐项加分：
        #   - 零轴上方（真多头状态）= 0.5，仅近期金叉（较弱）= 0.25
        #   - 放量 / 突破 各 0.5，未确认各 0.25
        score = 1.0  # 基础分：日线多头（C 闸门已通过）
        resonance = ["日线"]
        for label, above_zero, golden in (
            ("60min", tf60_above_zero, tf60_golden),
            ("30min", tf30_above_zero, tf30_golden),
            ("15min", tf15_above_zero, tf15_golden),
        ):
            if above_zero:
                score += 0.5
                resonance.append(f"{label}零轴上")
            else:
                score += 0.25
                resonance.append(f"{label}近期金叉")

        vol_ratio_val = vol_now / vol_5d if vol_5d > 0 else 0.0
        score += 0.5 if vol_ratio_val >= 1.5 else 0.25

        if mode_cfg["require_breakout"]:
            score += 0.5  # H 闸门已通过：价格突破 60min 平台
        if mode == "relaxed":
            score *= 0.9  # 宽松档信号略降权

        return SignalResult(
            code=code, name=name, signal_type=SignalType.LONG_ENTRY, score=round(score, 2),
            reason="；".join(reasons), price=round(price, 2),
            dif_daily=dif_d_last, dif_60m=self._last(dif_60),
            dif_30m=self._last(dif_30), dif_15m=self._last(dif_15),
            resonance_levels=resonance,
            tf_status={"daily_above_zero": True, "tf60_golden": tf60_golden,
                       "tf30_golden": tf30_golden, "tf15_cross_zero": tf15_above_zero,
                       "tf60_above_zero": tf60_above_zero, "tf30_above_zero": tf30_above_zero},
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
