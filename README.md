# V1.0 MACD多周期共振策略 — 量化选股与监控系统

## 📋 系统概述

基于 **日线 + 60min + 30min + 15min 四周期 MACD 共振** 的 A 股沪深主板中短线量化选股系统，支持 **飞书机器人实时推送 + GitHub Actions 自动运行**。

⚠️ **本仓库已从 V4.3 旧策略迁移到 MACD 多周期共振策略 V1.0**，旧代码归档于 `archive/`。

---

## 🏗️ 架构

```
dragon-strategy-v4.3/
├── strategies/macd_resonance/      # 新策略核心
│   ├── config.py                   # 参数集中配置（含1万本金风控）
│   ├── macd_indicator.py           # MACD指标(10,20,7) pandas标准实现
│   ├── data_source.py              # 多周期数据源(统一https+单位修复)
│   ├── filters.py                  # 硬过滤层（一票否决）
│   ├── market_gate.py              # 大盘门控（7分制）
│   ├── signal_engine.py            # 信号引擎（多空/规避/离场）
│   ├── scanner.py                  # 主扫描入口（并发+去重冷却）
│   └── backtest.py                 # 回测模块
├── scripts/v43_push.py             # 推送入口（调用新策略）
├── tests/                          # 单元测试
├── archive/                        # 旧策略归档
└── .github/workflows/              # GitHub Actions
```

## 🎯 选股逻辑

**做多入场（四周期共振，必须全部满足）：**
- 大盘门控 ≥4 分（可开仓）+ 硬过滤全部通过
- 日线：DIF > -0.05（零轴上方/附近）
- 60min：金叉 + DIF>0 + 红柱放大
- 30min：金叉 + DIF>0
- 15min：金叉 + DIF 上穿零轴
- 量能：当日量 > 前5日均量×1.3
- 价格：收盘价突破近20根60分钟K线最高价

**离场（任一触发）：**
- 日线零轴上方死叉 / 60min死叉+顶背离
- 止盈：浮盈≥10%减半，≥15%清仓
- 止损：浮亏≥5%硬止损 / 日线DIF跌破零轴

**空头规避：** A股无做空，日线DIF<-0.05或60min死叉且DIF<0 → 仅日志记录、从候选池排除，不推送。

## 💼 风控（按 1 万本金）

| 项目 | 数值 |
|------|------|
| 单票最大仓位 | 30%（约3000元） |
| 最大同时持仓 | 3 只 |
| 保留现金 | ≥10% |
| 止盈 | +10%减半 / +15%清仓 |
| 硬止损 | -5%（单票最大亏损约150元） |

## 🚀 部署

1. GitHub Secrets 配置 `FEISHU_WEBHOOK_URL`（飞书机器人 webhook）
2. 推送代码到 main，工作流自动运行（`strategy-push.yml` / `strategy_cloud_deploy.yml`）
3. 手动触发：Actions → Run workflow（可开 `test_mode` 跳过交易时段检查）

## 🧪 测试与回测

```bash
python -m unittest discover -s tests          # 单元测试（26项）
python -m strategies.macd_resonance.backtest --codes 600519,000001 --days 365   # 回测
python scripts/v43_push.py                    # 本地扫描+推送（需联网）
```

## ⚠️ 免责声明

仅供个人学习研究使用，不构成任何投资建议。投资有风险，决策需谨慎。
