# V1.0 MACD 多周期共振策略 — A 股量化选股与飞书推送

**日线 + 60min + 30min + 15min 四周期 MACD 共振**的 A 股沪深主板中短线选股系统，
云端运行、结果推送飞书。**不做本地部署、不做本地定时任务**（见 `AGENTS.md` 铁律 1）。

> ⚠️ **最容易误解的一点：把代码推到 `main` 不会触发任何推送。**
> 所有交易时段工作流的 `schedule` 已禁用，唯一自动触发源是 Cloudflare Worker（见「部署与推送链路」）。

⚠️ 目录名沿用 `dragon-strategy-v4.3`，但内部策略已迁移到 MACD 多周期共振 V1.0，旧代码归档于 `archive/`。

---

## 📖 文档地图

| 文件 | 用途 |
|---|---|
| **`AGENTS.md`** | ★ **权威协作手册**：架构速查、5 条铁律、已知坑、开发循环命令。**改代码前先读全文** |
| `docs/HANDOFF.md` | 交接背景、未决事项、凭据地图 |
| `strategies/macd_resonance/config.py` | **所有策略与风控参数的唯一来源**（本文件刻意不重复这些数字，避免再次过期） |
| `README.md`（本文件） | 系统是什么、怎么跑 |
| `archive/` | 已废弃的策略代码与文档 |

## 🏗️ 架构

```
dragon-strategy-v4.3/
├── strategies/macd_resonance/     40 个模块
│   ├── config.py                  参数集中配置（策略 / 风控 / 数据源）
│   ├── scanner.py                 ① MACD 多周期共振主扫描（并发 + 去重冷却）
│   ├── oversold_rebound.py        ② 超跌反弹扫描
│   ├── breakout.py                ③ 趋势突破扫描
│   ├── signal_engine.py           多周期共振信号引擎（多 / 空 / 离场）
│   ├── market_gate.py             大盘门控（7 分制）+ 市场环境接入
│   ├── market_regime.py           市场环境 5 档（牛 / 熊 / 强反弹 / 震荡 / 极端）
│   ├── filters.py                 硬过滤层（一票否决）
│   ├── data_source.py             东财 / 新浪 / 腾讯 / AkShare 多数据源
│   ├── data_validator.py          三源校验降级链 + 飞书告警
│   ├── portfolio_manager.py       持仓与离场信号
│   ├── strategy_gate.py           多策略注册表
│   ├── tracking.py / weekly_optimizer.py / evolution_engine.py   Agent 学习闭环
│   └── backtest.py / backtest_engine.py   回测
├── scripts/
│   ├── v43_push.py                ★ 云端唯一推送入口（三个扫描器串行 + AI 打分过滤）
│   ├── morning_noon_push.py       盘前 / 午间报告
│   └── scheduler_health_check.py  调度器健康检查（监控 Worker 停摆）
├── cloudflare-worker/             外部调度器 + 东财 API 代理（唯一自动触发源）
├── .github/workflows/             10 个工作流
├── data/                          Agent 学习数据（已入库）
├── knowledge/                     知识库文档
└── archive/                       已废弃代码与文档
```

## 🎯 三个扫描器（`scripts/v43_push.py` 串行执行）

| # | 策略 | 模块 | 说明 |
|---|---|---|---|
| 1 | MACD 多周期共振 | `scanner.py` | 大盘门控 + 四周期共振，主力策略 |
| 2 | 超跌反弹 | `oversold_rebound.py` | 20 日大幅回撤 + 底部横盘 + 当日启动信号 |
| 3 | 趋势突破 | `breakout.py` | 震荡市补充策略 |

每个扫描器独立超时（480s）、独立异常兜底，输出统一走
**AI 打分过滤 → 生成飞书消息 → 记录绩效跟踪（`tracking.py`）**。
任一扫描器挂掉只影响它自己，不会中断整条推送链路。

> 具体入场 / 离场条件与阈值请读 `config.py` 的 `MARKET_GATE` / `SIGNAL` /
> `OVERSOLD_REBOUND` / `RISK`。**本文件只讲结构，参数以代码为准。**

## 💼 风控（1 万本金）

| 项目 | 数值 |
|---|---|
| 单票最大仓位 | 30%（约 3000 元） |
| 最大同时持仓 | 3 只 |
| 保留现金 | ≥10% |
| 止盈 | +10% 减半 / +15% 清仓 |
| 硬止损 | -5%（单票最大亏损约 150 元） |

来源：`config.py` 的 `RISK`。

## 🚀 部署与推送链路（重要，别搞错）

```
Cloudflare Worker（macd-strategy-scheduler）
  Cron */15 * * * MON-FRI（UTC），Worker 内把 UTC 转北京时间再比对调度表
  Secret: GITHUB_TOKEN（需 repo 权限）
        │  POST /repos/{owner}/{repo}/actions/workflows/{file}/dispatches
        ▼
GitHub Actions（4 个交易时段工作流，只有 workflow_dispatch，无 schedule）
        │
        ▼
scripts/v43_push.py  ──►  飞书 webhook（GitHub Secret FEISHU_WEBHOOK_URL）
```

- **推 `main` 不会触发推送。** 交易时段工作流的 `schedule` 全部禁用 ——
  GitHub Actions cron 实测延迟 **4h23m 起**（曾把 9:15 盘前报告拖到 10:31、盘中推送拖到半夜）。
- 节奏：9:15 盘前报告 + 10:00~14:30 每 30 分钟共 8 档 + 14:45 尾盘 + 15:30 收盘复盘。
  改节奏**只改 `cloudflare-worker/worker.js` 的 `SCHEDULE` 数组**，工作流端不用动
  （改完需重部署 Worker）。
- **Worker 是唯一自动触发源，挂了会静默停推**，已有监控兜底：
  `scheduler_health_check.yml` 每天 15:00 BJT 检查最近 3 个完整交易日，
  停推会推飞书 🚨 并让该工作流变红。
- **本地不做定时推送。** `python scripts/v43_push.py` 可手动跑一次用于验证链路，
  但本机有代理问题、AkShare 会 `ProxyError`，**不要用本地扫描评估性能**（真实性能看云端日志）。

## 🧪 测试与回测

```bash
python -m pytest tests -q                                                        # 单元测试
python -m strategies.macd_resonance.backtest --codes 600519,000001 --days 365    # 回测
python scripts/v43_push.py                                                       # 本地手动扫描一次（需联网，仅验证用）
```

基线：**92 passed / 0 failed，约 1.6s，全程 0 次真实网络请求。**
出现任何 failed = 回归；耗时 >10s = 有单测漏了 mock、在打真实行情接口（见 `AGENTS.md` 坑 11）。

## ⚠️ 免责声明

仅供个人学习研究使用，不构成任何投资建议。投资有风险，决策需谨慎。
