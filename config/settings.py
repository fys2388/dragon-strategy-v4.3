"""
alpha-pick 全局配置

所有可调参数集中在此，其他模块从这里导入。
修改参数只需改这一个文件。
"""

import os
from pathlib import Path

# ─── 路径 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "reports"

for _d in [DATA_DIR, CACHE_DIR, LOG_DIR, REPORT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ─── 用户画像（按你的参数设定）────────────────────────
USER_PROFILE = {
    "market": "A股",              # A股 / 港股 / 美股
    "style": "中线波段",           # 持仓 1-4 周
    "max_drawdown_pct": 0.15,     # 组合最大回撤容忍 15%
    "capital": 500000,            # 总资金（元），<50万
    "single_stock_max_pct": 0.20, # 单只最大仓位 20%
    "max_holdings": 5,            # 同时持有最多 5 只
    "max_industry_count": 3,      # 最多同时持有 3 个行业
}

# ─── 选股池筛选参数 ───────────────────────────────────
UNIVERSE_FILTERS = {
    # 基本面门槛
    "min_market_cap": 30e8,       # 最小市值 30 亿
    "max_market_cap": 300e8,      # 最大市值 300 亿（<50万资金，300亿以内流动性够）
    "min_daily_amount": 5000e4,   # 日均成交额 > 5000 万
    "min_roe": 8.0,               # ROE > 8%
    "min_revenue_growth": 0.0,    # 营收同比增长 > 0%
    "exclude_st": True,           # 排除 ST / *ST
    "exclude_new_stock_days": 365,# 排除上市不满 1 年的次新股
    "exclude_suspended": True,    # 排除停牌股

    # 技术面门槛
    "above_ma60": True,           # 收盘价必须在 60 日线上方
    "ma60_upward": True,          # 60 日线必须向上
    "min_price": 5.0,             # 股价 > 5 元（避免低价股）
    "max_price": 100.0,           # 股价 < 100 元（<50万资金可承受）

    # 回撤参数（中线波段核心）
    "pullback_min_pct": 0.05,     # 从近期高点回撤至少 5%
    "pullback_max_pct": 0.30,     # 回撤不超过 30%（超过说明趋势坏了）
    "pullback_lookback_days": 60, # 从 60 日高点计算回撤

    # 企稳参数
    "consolidation_days": 5,      # 最近 5 日缩量企稳
    "volume_shrink_ratio": 0.85,  # 缩量比例：近期均量 < 前期均量的 85%
}

# ─── 信号参数 ─────────────────────────────────────────
SIGNAL_PARAMS = {
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # 均线
    "ma_short": 5,
    "ma_mid": 10,
    "ma_long": 20,
    "ma_trend": 60,

    # 买点类型及权重
    "entry_types": {
        "pullback_stabilize": {"weight": 1.0, "desc": "回踩企稳：缩量回踩均线+MACD低位金叉"},
        "breakout":           {"weight": 1.2, "desc": "放量突破：突破平台+量比>2"},
        "sector_leader":      {"weight": 1.1, "desc": "板块启动：板块轮动+龙头领涨"},
    },

    # 止损止盈
    "stop_loss_pct": 0.07,        # 硬止损 -7%
    "take_profit_1_pct": 0.15,    # 第一止盈 +15%（减半）
    "take_profit_2_pct": 0.25,    # 第二止盈 +25%（清仓）
    "time_stop_days": 10,         # 时间止损：10 个交易日不涨则减半
    "trailing_stop_ma": 10,       # 跌破 10 日线清仓

    # 打分权重
    "score_weights": {
        "trend": 0.25,            # 趋势强度
        "momentum": 0.20,         # 动量
        "volume": 0.15,           # 量价配合
        "fundamental": 0.20,      # 基本面
        "capital_flow": 0.10,     # 资金流
        "sector_heat": 0.10,      # 板块热度
    },
}

# ─── 大盘闸门参数 ────────────────────────────────────
MARKET_GATE = {
    # 大盘指数（用沪深300做基准）
    "benchmark_code": "000300",
    "benchmark_name": "沪深300",

    # 闸门评分（0-10 分）
    "gate_thresholds": {
        "strong": 7,    # ≥7 分：标准仓位，可满仓操作
        "normal": 5,    # ≥5 分：半仓操作
        "weak": 3,      # ≥3 分：轻仓（30%）
        "closed": 0,    # <3 分：空仓观望
    },

    # 评分维度
    "gate_indicators": [
        # (名称, 权重, 条件描述)
        {"name": "benchmark_trend", "weight": 0.30, "desc": "基准指数在60日线上方且60日线向上"},
        {"name": "volume_situation", "weight": 0.25, "desc": "市场成交额放大（近5日均量>20日均量）"},
        {"name": "breadth", "weight": 0.20, "desc": "上涨家数占比>50%"},
        {"name": "northbound_flow", "weight": 0.15, "desc": "北向资金净流入"},
        {"name": "sentiment", "weight": 0.10, "desc": "涨停家数>跌停家数"},
    ],
}

# ─── 数据源配置 ──────────────────────────────────────
DATA_SOURCE = {
    # 降级链：AkShare → 东方财富直连 → 新浪直连
    "sources": ["akshare", "eastmoney", "sina"],
    "cache_ttl_days": 1,          # 数据缓存有效期（天）
    "kline_days": 250,            # 拉取 K 线天数（约 1 年）
    "request_timeout": 15,        # 请求超时（秒）
    "request_retry": 2,           # 请求重试次数
    "proxy": None,                # 代理设置，如 "http://127.0.0.1:7897"
}

# ─── 飞书推送配置 ───────────────────────────────────
FEISHU = {
    "enabled": True,
    "webhook_url": os.environ.get("FEISHU_WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/4a232fcd-b7f0-401f-b26a-d8b03c87b6ee"),
    # 本地调试可在此填入实际 webhook，生产环境用环境变量
    # "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx",

    "message_types": {
        "premarket": "📊【{date} 中线波段选股推荐】",
        "alert": "🚨【盘中异动预警】",
        "review": "📋【{date} 盘后复盘】",
        "weekly": "📈【周度策略回顾】",
    },

    # 推送时间（北京时间）
    "schedule": {
        "premarket": "09:00",     # 盘前选股
        "alert_interval_min": 5,  # 盘中预警间隔（分钟）
        "review": "15:30",        # 盘后复盘
    },
}

# ─── 测试配置 ────────────────────────────────────────
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
IS_CLOUD = os.environ.get("IS_CLOUD", "false").lower() == "true"
