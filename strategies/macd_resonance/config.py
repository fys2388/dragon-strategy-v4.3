# -*- coding: utf-8 -*-
"""MACD 多周期共振策略 V2.0 — 集中配置。

V2.0 阶段一优化：
- 大盘开仓阈值降至 3 分（宽松档）
- 量比阈值降至 1.1
- 15 分钟仅需金叉（不要求上穿零轴）
- 30 分钟仅需金叉（不要求 DIF>0）
- 取消价格突破强制要求
- 新增 standard / relaxed 双模式，按大盘评分自动切换

所有策略参数、风控参数、数据源参数统一在此维护。
"""
from __future__ import annotations

# ============================================================
# MACD 参数（固定，全局唯一）
# ============================================================
MACD_FAST = 10
MACD_SLOW = 20
MACD_SIGNAL = 7
ZERO_AXIS_EPS = 0.05  # 零轴判定阈值

# ============================================================
# 多周期定义
# ============================================================
TIMEFRAMES = ["daily", "60m", "30m", "15m"]
TIMEFRAME_ORDER = {"daily": 4, "60m": 3, "30m": 2, "15m": 1}

# ============================================================
# 硬过滤层参数
# ============================================================
HARD_FILTERS = {
    "price_min": 3.5,        # 现价下限（元）
    "price_max": 30.0,       # 现价上限（元）
    "cap_min_yi": 40.0,      # 流通市值下限（亿）
    "cap_max_yi": 500.0,     # 流通市值上限（亿）
    "amount_20d_min": 8000.0, # 近20日日均成交额下限（万元）
    "amplitude_20d_max": 40.0, # 近20日累计振幅上限（%）
}

# ============================================================
# 大盘门控（7 分制）
# ============================================================
MARKET_GATE = {
    "open_threshold": 3.0,   # ≥3 允许开仓（宽松档），≥4 为标准档
    "standard_threshold": 4.0,  # ≥4 使用标准档严格信号
    "total_score": 7.0,
}

# ============================================================
# 信号引擎参数
# ============================================================
SIGNAL = {
    "daily_dif_floor": -ZERO_AXIS_EPS,     # 日线 DIF 不得低于该值
    "volume_ratio_min": 1.1,               # 量能确认：当日量 ≥ 前5日均量 × 1.1（V2.0放宽）
    "breakout_lookback_60m": 20,           # 突破确认：近20根60分钟K线最高价（V2.0宽松档不强制）
    "cooldown_hours": 6,                   # 同一标的推送冷却期（小时）
    # V2.0 双模式：standard(大盘≥4分) / relaxed(大盘3分)
    #
    # ⚠️ 瞬时事件 vs 持续状态（2026-09-22 修正，见 docs/HANDOFF.md §6.4.1）：
    #   MACD 金叉是瞬时事件，日线多空是持续状态。原实现要求 60/30/15min
    #   同时处于「刚发生金叉」，多个瞬时事件在同一时段命中的概率极低。
    #   2026-09-21 只修了 15min，60/30min 仍是瞬时口径，实测 104 只候选里
    #   60min 金叉 6 只、30min 金叉 3 只，交集为空 → 共振仍然 0 推荐。
    #   现在 60/30min 统一改为「多头状态（DIF 在零轴上方）或近 N 根金叉」，
    #   仍保留多周期同向这个核心，只是不再赌多个瞬时事件撞在同一根 K 线上。
    "mode_standard": {
        "tf30_require_dif_above_zero": True,   # 30分钟要求DIF>0
        "tf15_require_cross_zero": True,       # 15分钟要求DIF在零轴上方（多头状态）
        "require_breakout": True,              # 要求价格突破
        "volume_ratio_min": 1.2,                # 标准档量比1.2
        # 60/30min 多头状态判定：DIF>0 或近 N 根金叉，满足其一即可
        "tf60_state_or_cross": True,
        "tf30_state_or_cross": True,
        "tf60_golden_lookback": 8,              # 8 根 60min ≈ 2 个交易日
        "tf30_golden_lookback": 8,              # 8 根 30min ≈ 1 个交易日
        # 红柱：标准档只要红柱为正（DIF>DEA，多头状态），不要求逐根放大
        "require_red_bar_expanding": False,
    },
    "mode_relaxed": {
        "tf30_require_dif_above_zero": False,  # 30分钟仅需多头状态
        # 15分钟放宽为「零轴上方 或 近3根金叉」：不再要求瞬时上穿零轴
        #（瞬时事件与日线持续状态要求同时成立，是共振长期 0 推荐的成因之一）
        "tf15_require_cross_zero": False,      # 15分钟零轴上方 或 金叉
        "require_breakout": False,             # 不要求突破
        "volume_ratio_min": 1.1,                # 宽松档量比1.1
        "tf60_state_or_cross": True,
        "tf30_state_or_cross": True,
        "tf60_golden_lookback": 12,             # 宽松档回看更宽（≈3 个交易日）
        "tf30_golden_lookback": 12,
        "require_red_bar_expanding": False,
    },
}

# ============================================================
# 超跌反弹模式参数（捕捉天通股份8月这类暴利机会）
# ============================================================
OVERSOLD_REBOUND = {
    "drop_20d_min": 25.0,        # 20日跌幅≥25%（超跌）
    "consolidate_days": 5,         # 底部横盘天数
    "consolidate_amplitude_max": 12.0,  # 横盘期振幅≤12%
    "today_gain_min": 4.0,         # 当日涨幅≥4%（启动信号）
    "volume_ratio_min": 1.8,       # 量比≥1.8（放量确认）
    "daily_dif_floor": -0.8,       # 日线DIF下限（放宽，允许零轴下方）
    "tf60_require_golden": True,   # 60分钟必须金叉
    "tf30_require_golden": False,  # 30分钟金叉（可选）
    "max_recommendations": 5,      # 最多推荐5只
    "cooldown_hours": 12,          # 冷却期12小时
}

# ============================================================
# 止盈止损（1 万本金风控）
# ============================================================
RISK = {
    "total_capital": 10000.0,        # 总本金（元）
    "max_positions": 3,              # 最大同时持仓数
    "position_pct": 0.30,            # 单票最大仓位 30%
    "reserve_cash_pct": 0.10,        # 保留现金 ≥10%
    "take_profit_1_pct": 0.10,       # 浮盈 +10% 卖出 50%
    "take_profit_2_pct": 0.15,       # 浮盈 +15% 清仓
    "stop_loss_pct": 0.05,           # 硬性止损 -5%
    "commission_rate": 0.00025,      # 佣金（万2.5，双边）
    "stamp_tax_rate": 0.001,         # 印花税（卖出，千1）
}

# ============================================================
# 数据源（东方财富）
# ============================================================
DATA_SOURCE = {
    "base_url": "https://push2.eastmoney.com",
    "kline_url": "https://push2his.eastmoney.com",
    "timeout": 5,
    "retry": 2,
    "ut": "bd1d9ddb04089700cf9c27f6f74271dc3",
}

# 东财 K 线周期参数
KLT_MAP = {"daily": 101, "60m": 60, "30m": 30, "15m": 15}

# ============================================================
# LLM 智能分析配置（OpenAI 兼容接口，支持 DeepSeek / SenseNova / OpenAI 等）
# ============================================================
# API Key 通过环境变量 LLM_API_KEY 传入（GitHub Secrets），
# 也可直接在 config/llm_config.json 中写入（本地调试用）。
#
# 可用 provider 对照：
#   sensenova   → https://token.sensenova.cn/v1        (商汤 SenseNova 平台)
#   deepseek    → https://api.deepseek.com/v1          (免费 100 万 token)
#   openai      → https://api.openai.com/v1            (付费)
#   openrouter  → https://openrouter.ai/api/v1         (聚合平台，有免费模型)
LLM = {
    "enabled": True,               # 总开关：false 时完全跳过 LLM，纯规则降级
    "provider": "sensenova",       # sensenova / deepseek / openai / openrouter / 自定义
    "model": "sensenova-6.8-flash-lite",  # sensenova-6.8-flash-lite / deepseek-chat / gpt-4o-mini 等
    "api_base": "https://token.sensenova.cn/v1",  # OpenAI 兼容 API 地址
    "timeout": 30,                  # 请求超时（秒）— SenseNova 云端响应较慢，15s 不够
    "max_tokens": 500,              # 单次回复最大 token
    "temperature": 0.3,             # 低温度=更稳定，分析类建议 0.3
    "retry": 1,                     # 失败重试次数
    "fallback_to_rules": True,     # LLM 失败时自动降级到规则方案
    "batch_delay_s": 0.3,           # 批量调用间隔（秒），防限流
}
