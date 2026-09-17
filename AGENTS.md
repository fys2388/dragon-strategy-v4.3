# AGENTS.md — dragon-strategy-v4.3 协作手册

> 本文件是 Codex / 其它编码智能体的项目手册。**动手前先读完整份**。
> 一次性交接背景（并行代理痕迹、未决事项、凭据地图）见 `docs/HANDOFF.md`。

## 1. 项目是什么

A 股 **MACD 多周期共振**短线选股系统（日线 + 60min + 30min + 15min 四周期共振），
云端运行、结果推送飞书。**不做本地部署、不做本地定时任务。**

| 项 | 值 |
|---|---|
| 本地路径 | `E:\AI\策略\dragon-strategy-v4.3` |
| GitHub | `fys2388/dragon-strategy-v4.3`（public，直接推 `main`） |
| Python | 3.12.2 本地 / 3.11 GitHub Actions |
| 依赖 | requests, pandas, numpy, akshare（`requirements.txt`） |
| 测试 | **92 passed / 0 failed**，约 1.6s，**全程 0 次真实网络请求** |

## 2. 铁律（违反会导致推送中断或撞车）

1. **部署只在云端**：所有推送由 GitHub Actions 执行、经飞书 webhook 送达。
2. **交易时段工作流里不要再开 `schedule:`**。GitHub Actions 的 cron 延迟严重且稳定：
   本仓库实测 `daily_position_monitor.yml`（定 06:00 UTC）连续两日在 **10:23 / 10:32 UTC** 才执行，
   即延迟 **4h23m / 4h32m**；历史文档还记录过 5–12h（曾把 9:15 盘前拖到 10:31、盘中拖到半夜）。
   定时由外部调度器 `cloudflare-worker/worker.js`（Cloudflare Cron 每 15 分钟，UTC）
   调用 `workflow_dispatch` 完成 —— 实测调度到运行延迟约 **15 秒**（Worker 远快于 GitHub cron）。
3. **只留 `workflow_dispatch` 的 4 个交易时段工作流**：`strategy_cloud_deploy.yml`、
   `morning_noon_push.yml`、`strategy-push.yml`、`evening_review.yml`。
   `weekly_*`、`daily_position_monitor.yml`、`scheduler_health_check.yml` 保留了 `schedule`，
   属有意为之（它们不发交易推送，延迟几小时可接受），不要动。
   特别注意：`scheduler_health_check.yml` 的 schedule 是**监控系统本身**（见坑 12），删掉就等于取消监控。
4. **报告类型由 `REPORT_MODE` 决定，不要改回硬编码**：
   `premarket`=盘前报告（只发大盘概况+昨日回顾+持仓提醒，**不扫描**）；`scan`=盘中扫描。
5. **飞书 webhook 只允许存在于两处**：GitHub Secrets `FEISHU_WEBHOOK_URL`、`config/feishu_config.json`。
   不要打印、不要新增副本、不要写进日志。

## 3. 架构速查

```
strategies/macd_resonance/   39 个模块，主链路：
  scanner.py                扫描入口（标的池→初筛→硬过滤→共振信号→去重冷却）
  market_gate.py            大盘门控（≥4 分才开仓）
  signal_engine.py          多周期共振信号（多/空/离场）
  filters.py                硬过滤（一票否决）
  data_source.py            多数据源（东财/新浪/腾讯/AkShare + Cloudflare 代理）
  data_validator.py         数据源降级链 + 飞书告警
  portfolio_manager.py      持仓与离场信号
  config.py                 参数集中配置（1 万本金风控）
  breakout.py               趋势突破（第二策略）
  fundamental_filter.py / huangyang_scorer.py   基本面打分
  tracking.py / weekly_optimizer.py / evolution_engine.py   Agent 学习闭环

scripts/
  v43_push.py               ★ 推送入口（云端唯一入口，REPORT_MODE 分派）
  morning_noon_push.py      盘前/午间报告生成（被 v43_push 复用）
  scheduler_health_check.py 调度器健康检查（数 workflow_dispatch 次数，异常才推飞书）

.github/workflows/           10 个工作流
  strategy_cloud_deploy.yml ★ 盘中/盘前/尾盘推送（仅 workflow_dispatch）
  morning_noon_push.yml         已停定时，手动兜底
  strategy-push.yml           旧工作流，已停定时
  evening_review.yml        收盘复盘（已停定时，Worker 15:30 触发）
  daily_position_monitor.yml    14:00 持仓监控（保留 schedule）
  scheduler_health_check.yml    15:00 调度器健康检查（保留 schedule，监控 Worker/GITHUB_TOKEN 停摆）
  weekly_{performance,optimization,training,evolution}.yml  周日任务（保留 schedule）

cloudflare-worker/          外部调度器 + 东财 API 代理
  worker.js                 调度表（北京时间）→ workflow_dispatch；/proxy/* 东财代理
  api-proxy.js              代理实现
  wrangler.toml             ⚠️ 未入库（含 account_id，已 gitignore）；模板见 wrangler.toml.example

config/feishu_config.json   本地飞书配置（含 webhook_url）
data/                       运行产物与 Agent 学习数据
logs/                       运行日志（scanner_YYYYMMDD.log 等）
archive/                    V4.3 旧策略归档
knowledge/                  知识库文档
```

## 4. 环境变量与凭据

| 变量 | 值 / 来源 | 作用 |
|---|---|---|
| `FEISHU_WEBHOOK_URL` | GitHub Secrets；本地兜底 `config/feishu_config.json` | 飞书推送 |
| `IS_CLOUD` | `true`（仅 Actions 设置） | 云端跳过东财直连新浪/腾讯，绕过海外 IP 限流 |
| `TEST_MODE` | `true` | 跳过交易时段检查（手动验证用） |
| `REPORT_MODE` | `premarket` / `scan` / 空(自动) | 报告类型分派（见铁律 4） |
| `TRIGGER` | `schedule` / `workflow_dispatch` | 仅记录用，**守卫已不再依赖它**（见坑 8） |
| `PUSH_FEISHU` / `PUSH_ALL_POSITIONS` | 脚本内读取 | 推送开关 |
| Worker secret `GITHUB_TOKEN` | Cloudflare Worker Secrets，需 `repo` 权限 | 调度器触发 workflow_dispatch |
| Actions `GITHUB_TOKEN` | 工作流内置（`scheduler_health_check.yml` 用，`permissions: actions: read`） | 统计 workflow 运行次数 |

本地 `gh` 已认证（`gh auth token` 可用）；**匿名 API 会限流，一律用 gh**。

## 5. 开发循环（本机必知）

```bash
# 1. 改完先编译 + 跑全量单测
python -m py_compile scripts/v43_push.py strategies/macd_resonance/scanner.py
python -m pytest tests -q            # 当前基线 92 passed / 0 failed，约 1.6s
#    出现任何 failed = 回归；耗时 >10s = 有单测在打真实行情接口（见坑 11）

# 2. 提交（中文提交信息，与现有历史一致）
git add <files> && git commit -m "feat: xxx"

# 3. 推送 —— ★ 本机直连 GitHub 会超时，必须走代理
git -c http.proxy=http://127.0.0.1:7897 push origin main

# 4. 手动触发云端验证（report_mode 可选 premarket / scan）
gh workflow run "V1.0 MACD多周期共振策略云推送" --repo fys2388/dragon-strategy-v4.3 -f report_mode=premarket
gh workflow run "V1.0 MACD多周期共振策略云推送" --repo fys2388/dragon-strategy-v4.3 -f test_mode=true

# 5. 查运行状态
gh api "repos/fys2388/dragon-strategy-v4.3/actions/runs?per_page=20" \
  --jq '.workflow_runs[] | [.id, .status, .conclusion] | @tsv'

# 6. 拉运行日志（gh api 不支持 --output，必须用 Invoke-WebRequest）
$token = gh auth token
Invoke-WebRequest -Uri "https://api.github.com/repos/fys2388/dragon-strategy-v4.3/actions/runs/<RUN_ID>/logs" \
  -Headers @{Authorization="Bearer $token"; "User-Agent"="dsh"; Accept="application/vnd.github+json"} \
  -OutFile "$env:TEMP\run.zip"
Expand-Archive "$env:TEMP\run.zip" "$env:TEMP\runlogs" -Force

# 7. 看远端文件内容（raw 模式；注意加 --jq 会报 invalid character '#'，raw 不是 JSON）
gh api "repos/fys2388/dragon-strategy-v4.3/contents/scripts/v43_push.py" -H "Accept: application/vnd.github.raw"
```

**本地扫描不要用来测性能**：本机有代理问题，AkShare 会 `ProxyError`，完整扫描可能跑 6 分钟以上；
真实性能以云端运行为准（见 §6）。

## 6. 性能基线（改扫描前先对照）

| 项 | 值 | 位置 |
|---|---|---|
| 标的池规模 | 1200 只（按成交额降序） | `v43_push.py SCAN_MAX_STOCKS` |
| 并发 | 12 worker（硬过滤 / 信号分析各 1 个池） | `scanner.py` |
| 扫描硬超时 | 480s（超时告警 + 中断） | `v43_push.py SCAN_TIMEOUT_S` |
| 成交额预过滤 | 金额 > 0 且 < 0.5 直接剔除 | `scanner.py _quick_filter` |
| 云端实测耗时 | 335s ~ 444s | Actions 运行日志 |
| 推送节奏 | 盘中每 30 分钟（10:00/10:30/11:00/11:30、13:00/13:30/14:00/14:30、14:45 尾盘） | `cloudflare-worker/worker.js SCHEDULE` |

节奏从每 10 分钟降到每 30 分钟是为省 GitHub Actions 免费配额（提交 `63df125`）。
**不要把扫描变重到逼近 480s**，否则看门狗会告警并中断。

## 7. 数据源

降级链：**东财 → 新浪 → AkShare**。
- `IS_CLOUD=true` 时跳过东财，直连新浪/腾讯（海外 IP 东财常挂死）。
- GitHub Actions 出网 IP 对东财有限流 → 走 `cloudflare-worker` 的 `/proxy/{sector,moneyflow,fundamental,news}`。
- Yahoo Finance 实测 404 不可用，不要再尝试。
- 连通性验证以 `data_validator.py` 的三源降级 + 飞书告警为准。

## 8. 已知坑（踩过，别重复）

1. **GitHub Actions cron 延迟 4h23m 起步（实测）** → 交易时段一律走外部调度器（见铁律 2）。
2. **AkShare 的 `_em` 底层仍走东财**，不能当独立备用源。
3. **腾讯 K 线第 7 字段可能是 dict/list**，解析前要判类型。
4. **本机 git push 必须带代理**（`-c http.proxy=http://127.0.0.1:7897`），否则 21 秒超时。
5. **`gh api` 匿名请求会 403 限流**；`gh api` 不支持 `--output`，下载用 `Invoke-WebRequest`。
6. **YAML 加 `-H "Accept: application/vnd.github.raw"` 后再用 `--jq` 会报错**（raw 不是 JSON）。
7. **PowerShell 里嵌套双引号正则易解析失败**，复杂表达式改用 Python 或简单 Select-String。
8. **盘前守卫只认时间，窗口外补发要走另一个工作流**：守卫条件是
   `mode == "premarket" and hm >= 945 → skip`，**不看触发来源**
   （早期版本要求 `TRIGGER == "schedule"`，但 schedule 已禁用、Worker 走 workflow_dispatch，
   条件永不成立 = 空转，已修）。
   所以 9:45 之后手动触发 `strategy_cloud_deploy.yml -f report_mode=premarket` 会被跳过；
   **窗口外补发盘前报告**请用 `morning_noon_push.yml`（`workflow_dispatch`，不经守卫）。
9. **调度器是单点，但已有监控（✅ 2026-09-17）**：Cloudflare Worker + 其 `GITHUB_TOKEN` 仍是单点，
   Worker 挂掉或 token 过期 = 静默停推。监控方案是 `scheduler_health_check.yml`
   （`scripts/scheduler_health_check.py`）：用 GitHub `schedule` 每天 15:00 BJT 触发
   （实测约 19:30 才执行，故意晚于当日最后档位 15:30，避免把「还没到点」误判成停推），
   统计最近 3 个完整交易日的 `workflow_dispatch` 运行次数，异常才推飞书，正常时静默。
   为什么必须挂在 `schedule` 上：其它推送工作流本身也是 Worker 触发的，
   用它们监控 Worker 等于用停摆的系统监控停摆的系统。
   改 `worker.js` 的节奏时**同步改** `scheduler_health_check.py` 的
   `EXPECTED_PUSH_PER_DAY` / `EXPECTED_REVIEW_PER_DAY`，否则会出现「实际正常但天天告警」。
10. **`.workbuddy/` 是另一个代理留下的状态目录**（memory/automations），与本项目代码无关，别提交。
11. **单测 mock 必须打到真正的请求入口**：有两处会绕过 `_request_get`——
    `data_source._get_em_limit_pool_count()` 直接 `requests.get`；
    `signal_engine.check_long_entry(mode="auto")` 实时调 `get_market_score()`（→ 东财行情）。
    只 mock `_request_get` 会让单测发起真实 HTTP（实测 72 次/轮，拖慢到 40s）。
    改单测后若 `pytest tests -q` 耗时 >10s，就是漏了 mock（修完见 `docs/HANDOFF.md` §6.0）。
12. **写监控/告警时「查不到」≠「没发生」**：`scheduler_health_check.py` 踩过这个坑 ——
    GitHub API 调用失败（401/限流）时若仍把计数当 0，会半夜误报「Worker 停摆」，
    让人去 Cloudflare 控制台白查一轮。正确做法：API 失败时该条不参与判定（表里显示 ❓），
    并单独出一档「⚠️ 本次未能完整判定」，与真正的 🚨 停推分开。
    另外：**workflow 结论 success 不等于飞书真的收到**（推送失败可能被脚本吞掉），
    现有监控只能保证「调度发生了」，不能保证「消息送达」。

## 9. 常见任务

- **改盘中节奏** → 改 `cloudflare-worker/worker.js` 的 `SCHEDULE` 数组（北京时间），然后重部署 Worker（需要 `wrangler.toml`，见 `docs/HANDOFF.md`）。工作流端不用改。
- **改盘前报告内容** → `scripts/morning_noon_push.py` 的 `build_premarket_report()`。
- **窗口外手动补发盘前报告** → `gh workflow run "Morning & Noon Report Push" --repo fys2388/dragon-strategy-v4.3`
  （走 `morning_noon_push.yml`，不经盘前守卫；`strategy_cloud_deploy.yml` 在 9:45 后会跳过 premarket）。
- **改盘中报告格式** → `scripts/v43_push.py` 的 `build_message()`（实际在 `scanner.py`）。
- **改选股逻辑** → `strategies/macd_resonance/{scanner,filters,signal_engine,market_gate}.py`。
- **加数据源** → `data_source.py` + `data_validator.py` 降级链。
- **回测** → `python -m strategies.macd_resonance.backtest --codes 600519,000001 --days 365`。

## 10. 当前状态（截至本文件写入）

- 远端 `main` 已同步本地。**测试基线 92 passed / 0 failed**（全离线、0 次真实网络请求，约 1.6s）；
  原 11 项失败的根因与修复逐项记录在 `docs/HANDOFF.md` §6.0。
- 盘前报告已并入 `strategy_cloud_deploy.yml` 的 `premarket` 档，`morning_noon_push.yml` 定时已停用。
- 云端双分支已验证：`premarket` 与 `scan` 均推送成功（HTTP 200）。
- 盘前守卫已改为纯时间判断（9:45 后跳过），不再依赖 `TRIGGER`。
- 调度器单点监控已上线（`scheduler_health_check.yml` + `scripts/scheduler_health_check.py`）：
  每天 15:00 BJT 检查最近 3 个完整交易日的 `workflow_dispatch` 次数，异常才推飞书。
  实测 Worker 当前健康（09-14~09-16 各 10+/1 次，调度延迟约 15s）。
  改 `worker.js` 的 `SCHEDULE` 时须同步改脚本里的 `EXPECTED_PUSH_PER_DAY` / `EXPECTED_REVIEW_PER_DAY`。
- 未决事项与未跟踪文件清单 → `docs/HANDOFF.md`。
