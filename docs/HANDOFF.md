# HANDOFF.md — 交接给 Codex 的背景说明（一次性阅读）

> 日常开发请读根目录 `AGENTS.md`（协作手册 + 已知坑）。
> 本文件只讲「交接这个时点发生了什么、有什么坑、接手第一天该做什么」。**处理完未决事项后可归档到 `archive/`。**

---

## 1. 交接时点

| 项 | 值 |
|---|---|
| 远端主分支 | `main`（直接推 main，无 PR 流程） |
| 本地与远端 | 已同步，无未提交改动 |
| 测试 | **92 passed / 0 failed**（§6.0 的 11 项已修完，全程 0 次真实网络请求，~1.6s） |
| 仓库可见性 | **public**（注意：不要把新凭据写进仓库） |
| 本地代理 | 本机 git 推送必须 `-c http.proxy=http://127.0.0.1:7897` |
| gh CLI | 已登录，token scope 含 `repo`，可读写私有仓库 API |

---

## 2. 接手前必须知道：这个仓库被两个流程并行改过

本仓库不是单一代理独占的。**在交接方（DSH）的改动之后，另一个代理流程连续推了 30+ 个提交**，
其中包含**架构级变更**。接手方如果不了解，会做出与现状冲突的决定。

### 交接方（DSH）做的（提交 `656c140` → `3ab56fe` → `6302bf1` → `d198f77`）

- `v43_push.py` 增加 `REPORT_MODE` 分派：`premarket`（盘前报告，不扫描）/ `scan`（盘中扫描）。
- `strategy_cloud_deploy.yml` 增加 `report_mode` 手动输入 + `REPORT_MODE` / `TRIGGER` 环境变量。
- `morning_noon_push.yml` **停用定时**（删除 `schedule:`，只留 `workflow_dispatch`），盘前报告并入云端 9:15 档。
- 盘前守卫：定时档若被 GitHub 延迟到 9:45 后，跳过盘前报告，避免与盘中撞车。
- 云端双分支已验证成功：运行 `32803531452`（premarket）、`32803646853`（scan），均 `HTTP 200`。

### 并行代理做的（提交 `63df125` → `3dff734`，**这是当前现状**）

| 提交 | 内容 |
|---|---|
| `63df125` | 盘中节奏从每 10 分钟**降为每 30 分钟**（省 GitHub Actions 免费配额） |
| `49e6688` | **禁用所有交易时段工作流的 `schedule:`**，理由：GitHub cron 延迟 5–12 小时，推送被拖到半夜 |
| `e8e18bc` / `dab5b6f` | 调度逻辑内置到 Cloudflare Worker，**只保留一个每 15 分钟的 Cron**，Worker 内部判断交易时段 |
| `3cfad01` | 新增 `cloudflare-worker/api-proxy.js`：Cloudflare 代理解决 GitHub Actions IP 被东财限制 |
| `e40f084` | 动态股票池 153 → 214 只 |
| `51809dd` / `cd42bd3` | Agent 学习数据持久化、用户反馈通道 |
| `4a5294d` | Agent 自主优化闭环（周度优化器 + 参数进化 + 冷却期自适应） |
| `84a6ef8` / `d95accc` / `d318e82` / `1012a79` / `3407f72` | 基本面打分、知识库融合、止盈止损、冷却期 |
| `e1ceb9c` … `77a0d50` | `knowledge/` 知识库批次文档 |
| `7826353` / `211b1c6` / `b4b496d` / `47749ab` / `3dff734` | 股票池周更、推荐逻辑修复、饥饿度自适应、门控修复 |

**并行代理留下了本地状态目录 `.workbuddy/`**（`memory/`、`automations/`），未被 git 跟踪。
它不属于本项目代码，**不要提交**，也不需要清理。

---

## 3. 当前真实架构（重要：不是「GitHub 定时」了）

```
                 ┌─────────────────────────────┐
                 │  Cloudflare Worker           │
                 │  macd-strategy-scheduler     │
                 │  Cron: */15 * * * MON-FRI    │
                 │  (UTC，Worker 内判北京时间)   │
                 │  Secret: GITHUB_TOKEN        │
                 └──────────────┬──────────────┘
                                │ POST /actions/workflows/{file}/dispatches
                                │   body.inputs.report_mode
                                ▼
   09:15 premarket ─┐
   10:00/10:30/...  │   ┌─────────────────────────┐
   13:00/13:30/...  ├─▶│ strategy_cloud_deploy.yml │──▶ v43_push.py
   14:45 scan       │   │ (仅 workflow_dispatch)    │     ├ premarket → morning_noon_push.build_premarket_report()
   15:30 review  ───┘   └─────────────────────────┘     └ scan      → Scanner.run() → build_message()
                        evening_review.yml
                                │
                                ▼
                        飞书 webhook (GitHub Secret FEISHU_WEBHOOK_URL)
```

**GitHub Actions 上没有任何 `schedule` 在跑交易时段推送。** 唯一自动触发源是 Cloudflare Worker。

保留 `schedule` 的工作流（有意为之，延迟可接受）：
- `daily_position_monitor.yml` — `0 6 * * 1-5`（14:00 BJT）
- `weekly_performance.yml` `0 12 * * 0` / `weekly_optimization.yml` `0 13 * * 0` /
  `weekly_model_training.yml` `0 13 * * 0` / `weekly_evolution.yml` `0 14 * * 0`

---

## 4. 凭据与账号地图（**不要把密钥写进仓库**）

| 凭据 | 存放位置 | 备注 |
|---|---|---|
| 飞书 webhook | GitHub Secrets `FEISHU_WEBHOOK_URL`；`config/feishu_config.json`（已入库） | 本地推送用后者 |
| Cloudflare `account_id` | 本地 `cloudflare-worker/wrangler.toml`（已 gitignore，**不入库**）；模板 `wrangler.toml.example` 已入库 | 重部署 Worker 前必须把真实值填进本地 wrangler.toml |
| GitHub token（Worker 用） | Cloudflare Worker Secrets `GITHUB_TOKEN`，需 `repo` 权限 | 失效则静默停推 |
| gh CLI 登录态 | 本机 `gh auth`（scope 含 `repo`） | 换机器需重新 `gh auth login` |
| 本地代理 | `127.0.0.1:7897`（系统代理，ProxyServer） | git 直连 GitHub 会 21s 超时 |

**`wrangler.toml` 已处理**：加入 `.gitignore`（真实值不入库），
`wrangler.toml.example` 已入库并写明 `account_id` 的获取路径与部署命令。
新 clone 仓库后可照模板补齐再部署。

---

## 5. 调度器细节（`cloudflare-worker/worker.js`）

- Cron：`*/15 * * * MON,TUE,WED,THU,FRI`（UTC）；Worker 内把 UTC 时间 +8h 转北京时间，与调度表比对，**容差 ±2 分钟**。
- 调度表（北京时间）：`9:15 premarket`、`10:00/10:30/11:00/11:30 scan`、`13:00/13:30/14:00/14:30 scan`、`14:45 scan（尾盘）`、`15:30 review`。
- 周末不触发；非调度时间静默跳过。
- 触发 `evening_review.yml` 用 `report_mode=""`（不带 inputs）。
- 手动入口：浏览器访问 Worker URL → `?mode=scan` 触发一次。
- `/proxy/{sector,moneyflow,fundamental,news}`：东财 API 代理，`cacheTtl=30`。
- **改节奏只改 `SCHEDULE` 数组**，工作流端不用动。改完需重部署 Worker。

---

## 6. 未决事项（按优先级）

### P0 — 建议接手第一天就确认

**6.0 测试套件已修绿：92 passed / 0 failed — ✅ 已修（2026-09-17）**
接手时是 71 passed / 11 failed，全部是「代码改了、测试没跟」，**不是代码回归**。已逐项修完。

| 失败用例 | 根因 | 实际修复 |
|---|---|---|
| `TestLimitUpDown`（3 项） | **mock 目标漂移**：`get_limit_up_down_count()` 新增第 1 步 `_get_em_limit_pool_count()` 直接调 `requests.get`，**绕过** `_request_get`。测试只 mock 了 `_request_get`，第 1 步打到真实东财（返回 47/0）并提前 return，后续断言全废 | 新增 `_no_em_limit_pool()` 统一屏蔽第 1 步，让这 3 项回归它们原本要测的第 3 步（东财全A列表遍历）；**另补 2 项新用例**专测第 1 步（涨跌停池优先级 / 池失败降级），该函数此前零覆盖 |
| `TestRegime`（4 项） | **口径整体替换**：`classify_regime()` 已从 `strong_trend/weak_trend/range_bound` 改为 `bull_market/bear_market/strong_rebound/sideways/extreme`，旧三档在 `REGIME_LABELS` 中不存在 | 按当前 5 档重写为 9 项，覆盖全部分支 + `None` 输入 + `abs(chg)>3.5` 严格大于的边界 |
| `TestScannerIntegration`（2 项） | `regime` 实际值随新口径变为 `bull_market` | 断言改为 `bull_market`；「双源失败」用例补断言 `regime == "sideways"`（见下方代码修正） |
| `TestScannerDiagnosticLine`（1 项） | **断言过期**：`build_message()` 在提交 `1fdc849`「推送极简版」中被**有意**精简，触发时间/扫描耗时/涨停跌停/数据源/校验/诊断行全部移除 | 重写为 `TestBuildMessage` 5 项，钉住极简版契约（🔴可开仓/🟡宽松/🟢观望三档、每只 1 行推荐、刻意不含诊断信息）。**未改 `scanner.py` 恢复旧文案**——那是用户自己的文案决定 |
| `TestBuildMessageDataSourceLine`（1 项） | 同上，断言的是已被移除的三行 | 其「极简版不含数据源/校验行」契约并入 `TestBuildMessage.test_minimal_format_omits_diagnostics`；数据源/校验状态/regime 的产出契约由 `TestScannerIntegration` 覆盖。原类已删除（用例数 82 → 92） |

**顺带修的一处代码**：`scanner.py` 初始结果模板里 `"regime": "range_bound"` 是过期默认值（该字符串已不在 `REGIME_LABELS`），改为 `"sideways"`。
只影响「数据异常提前返回」的路径；正常扫描路径在 `run()` 内会被 `classify_regime()` 覆盖。

**额外发现并修复：单测原本在打真实行情接口**
逐文件封锁 `requests.get/post` 审计发现：`tests/test_signal_engine.py` 单独发起 **72 次真实 HTTP**（打东财）——
`check_long_entry(mode="auto")` 会实时调 `get_market_score()`，而该测试没 mock。断网时该文件耗时 60s。
已在 `TestSignalEngine.setUp` 固定 `get_market_score() → (5.0, …, True)`（标准档），
并给 `TestScannerGate` 补 `PortfolioManager.check_exit_signals` mock。
现在 **`tests/` 全程 0 次真实请求，92 项 1.6s 跑完**（原 40s）。

回归判据（任一不满足 = 有 mock 漏了或改坏了）：
```bash
python -m pytest tests -q          # 应为 92 passed，耗时 ~1.6s
# 出现任何 failed = 回归；耗时 >10s = 有单测在打真实行情接口
```

**6.1 盘前守卫空转 — ✅ 已修**
守卫已从 `TRIGGER == "schedule" and hm >= 945` 改为纯时间判断 `mode == "premarket" and hm >= 945 → skip`，
不再依赖 `TRIGGER`（schedule 已禁用、Worker 走 `workflow_dispatch`，旧条件永不成立 = 空转）。
「两个报告」撞车风险已消除。

副作用：9:45 之后手动触发 `strategy_cloud_deploy.yml -f report_mode=premarket` 会被跳过；
窗口外补发盘前报告请走 `morning_noon_push.yml`（`workflow_dispatch`，不经守卫）。
可选加固：在 Worker 侧 `handleTrigger` 里也判断一次时间（修复 B），双保险。

**6.2 调度器无监控（单点静默失败）— ✅ 已加监控（2026-09-17）**
Cloudflare Worker 挂掉、或其 `GITHUB_TOKEN` 过期 → **完全停推**。原方案没有任何告警，现已补齐。

新增 `.github/workflows/scheduler_health_check.yml` + `scripts/scheduler_health_check.py`：

| 设计点 | 选择 | 理由（都是实测出来的） |
|---|---|---|
| 触发源 | GitHub `schedule`（**必须**） | `evening_review.yml` 等推送工作流本身也是 Worker 触发的，用它们监控 Worker = 用停摆的系统监控停摆的系统。`schedule` 是本仓库唯一不依赖 Worker 的自动触发源 |
| cron 时间 | `0 7 * * 1-5`（15:00 BJT） | 本仓库 `schedule` 实测延迟 **4h23m / 4h32m**（`daily_position_monitor.yml` 定 06:00 UTC，连续两日 10:23 / 10:32 UTC 才执行）。15:00 BJT 定、约 19:30 BJT 执行，此时当日最后档位 15:30 已过去，不会把「还没到点」误判成停推 |
| 判定口径 | 数 `workflow_dispatch` 运行次数 | 对节假日免疫（Worker 不检查 A 股休市日历，节假日照样触发）；对检查自身延迟免疫（只看已结束的交易日） |
| 期望值 | 盘中 10 次/天 + 复盘 1 次/天 | 与 `cloudflare-worker/worker.js` 的 `SCHEDULE` 一一对应。**改节奏时必须同步改** `EXPECTED_PUSH_PER_DAY` / `EXPECTED_REVIEW_PER_DAY` |
| 回看窗口 | 最近 3 个**完整**交易日（不含当天，自动跳周末） | 只要检查被延迟到次日，结论依然成立 |
| 推送策略 | 正常时**静默**，异常才推飞书 + 工作流变红 | 每天一条「正常」是噪音；变红是兜底信号（飞书万一也挂了） |

告警分三档标题，避免误报浪费排查时间：
- `✅ 正常` —— 不推送
- `🚨 检测到停推风险` —— 某交易日 0 次调度（Worker 停摆 / token 失效）、工作流文件被删（404）、部分档位缺失、有 run 非 success
- `⚠️ 本次未能完整判定（检查自身问题，非停推）` —— GitHub API 调用失败。**这一档是刻意加的**：
  首版把 API 失败当成 0 次，会半夜误报「Worker 停摆」让人去 Cloudflare 控制台白查一轮。
  现在 API 失败的日期不参与判定、表里显示 `❓API失败`。

### 6.2.1 盲区已封堵：飞书送达判定（2026-09-17）

首版的盲区是「workflow 结论 `success` 不等于飞书真的收到」。根因查出来有两条：

1. `v43_push.py` 的 `_send_text` 只要 `requests.post` 不抛异常就 `return True`，
   **完全忽略 HTTP 状态码和飞书正文的 `StatusCode`**。而飞书自定义机器人 webhook 被删除/停用时
   HTTP 仍是 200，只有正文里的状态码非 0 —— 所以会打出「✅ 飞书推送完成，HTTP 200」却没送达。
2. `main()` **从不读 `_send_text` 的返回值**，也没有任何 `sys.exit(1)`。

即：webhook 失效 → 飞书返回 200 → workflow 绿 → 健康检查数到 10 次成功运行 → 报「✅ 正常」。
用户可能连着几天一条都没收到，全程零告警。

仓库里一共有 **4 个**推送函数踩了同一个坑，全部修掉：

| 函数 | 触发路径 |
|---|---|
| `v43_push._send_text` | 盘中扫描报告（合并三策略为一条） |
| `v43_push.send_feishu_alert` | 扫描超时 / 策略异常告警 |
| `morning_noon_push.send_to_feishu` | 盘前 / 午盘报告，也是 9:45 守卫的**补发通道** |
| `scheduler_health_check.push_feishu` | 健康检查自己的告警（监控本身也踩了同一个坑） |

修法（不需要任何外部配置，仓库内改动即生效）：
- 新增 `scripts/feishu_client.py` 的 `check_feishu(resp)`：同时校验 HTTP 200 + 正文
  `StatusCode == 0`（v2）或 `code == 0`（v1）。零依赖、不 import requests，
  `v43_push.py` 与 `morning_noon_push.py` 共用它，避免三份实现各自漂移。
  `scheduler_health_check.py` 保留一份独立副本并加注释说明 —— 它的工作流只装 requests，
  刻意不依赖策略代码，监控脚本不能因为策略包导入失败而失效。
  **保守原则**：正文不是 JSON、或没有可识别的状态码字段时视为成功 —— 只在「确定失败了」时才失败，
  避免飞书改格式造成误报中断推送。
- `main()` 推送失败 → `_exit_on_push_failure()` → `sys.exit(1)` → workflow 变红。
  退出调用**刻意放在 `main()` 末尾**（绩效跟踪更新之后）：那是当天唯一一次的更新，不能因推送失败被跳过。
- `send_feishu_alert` / `push_premarket_report` 同样改为返回 bool。
- `scheduler_health_check.py` 的 `push_feishu` 有**完全相同**的缺陷，一并修了 ——
  它自己是监控，这条链断了等于静默失效。

现在：推送失败 → 非零退出 → Actions 红点 + 健康检查的 `failed_run` 告警，双通道兜底。

已核实工作流不会被非零退出拖坏（`.github/workflows/strategy_cloud_deploy.yml`）：
`运行MACD多周期共振策略推送` 步骤没有 `|| true` 也没有 `continue-on-error`，
所以 exit 1 会让 workflow 结论为 `failure`；而后面「上传运行日志」「回传学习数据」
两个步骤都是 `if: always()`，**当天唯一一次的绩效跟踪更新不会因为推送失败被跳过**。

### 6.2.2 已加：Worker KV 心跳比对（2026-09-17）

`worker.js` 在每次 dispatch 成功/失败后往 Cloudflare KV 写一条 `{ts_ms, workflow, status}`，
新增 `GET /health` 端点返回；`scheduler_health_check.py` 每天比对这份心跳与 GitHub 运行记录。

这让三种**都表现为 `runs == 0`**、原来只能猜的故障第一次能被区分：

| 告警分类 | 含义 | 去哪查 |
|---|---|---|
| `heartbeat_stale` | Worker 最近 6 小时内没有成功 dispatch 记录 | Worker 被暂停/删除，或 Cron 触发器丢失 |
| `dispatch_no_run` | Worker 声称 dispatch 成功了，但 GitHub 侧 0 次运行 | GitHub 侧未接单（Actions 配额耗尽/服务异常），**Worker 不用动** |
| `dispatch_failed` | dispatch 调用本身失败，心跳里带 HTTP 状态码 | 401/403 = `Secrets.GITHUB_TOKEN` 失效；404 = 工作流文件被改名 |

配套改动：
- `wrangler.toml.example` 增加 `kv_namespaces` 绑定 + 创建步骤 + `WORKER_HEALTH_URL` 说明。
- `.github/workflows/scheduler_health_check.yml` 增加可选 env `WORKER_HEALTH_URL`。
- KV 写失败**只记日志、不阻断主流程**（`recordHeartbeat` 内部吞异常）——
  观测手段不能反过来导致当天交易推送丢失。
- 未配 KV 时 `/health` 仍正常响应（`kvConfigured: false`），
  所以「还没升级 KV」和「Worker 挂了」也能区分开。

手动验证：
```bash
python scripts/scheduler_health_check.py --dry-run            # 只打印不推送（本地需 GITHUB_TOKEN）
python scripts/scheduler_health_check.py --selftest           # 打印模拟告警文案，含心跳分支，无网络请求
gh workflow run "调度器健康检查" --repo fys2388/dragon-strategy-v4.3 -f always_report=true
```

⚠️ 心跳比对需要你手动完成两步（需要 Cloudflare 控制台权限，仓库里做不到）：
```bash
npx wrangler kv namespace create HEARTBEAT --config wrangler.toml   # 把打印的 UUID 填进 kv_namespaces.id
npx wrangler deploy --config wrangler.toml
# GitHub Settings → Secrets and variables → Actions → 新建
#   WORKER_HEALTH_URL = https://<你的-worker-子域名>.workers.dev   （根 URL，不带 /health）
```
阈值 `MAX_HEARTBEAT_AGE_H` 默认 6.0 小时（可用同名环境变量覆盖）。本工作流约 19:30 BJT 执行，
最后档位 15:30，6.0h 意味着「最后成功 dispatch 在 13:30 BJT 之后」就算新鲜；
Worker 在 13:30 之前挂掉会被判为陈旧。想更早发现就调小。

#### 已部署状态（2026-09-17）

Cloudflare 侧三步已全部完成并端到端验证：

| 项 | 值 |
|---|---|
| Worker URL | `https://macd-strategy-scheduler.fys2388.workers.dev` |
| KV namespace | `HEARTBEAT`（binding 名与 `worker.js` 里的 `env.HEARTBEAT` 对应） |
| 部署版本 | `9305d0db-f3e3-4df4-b986-3f1ad0f5f621` |
| Cron | `*/15 * * * MON,TUE,WED,THU,FRI`（与改动前一致，未变） |
| GitHub Secret | `WORKER_HEALTH_URL` 已建 |

部署用的是仓库里已有的 wrangler CLI 凭据（`~/.wrangler/config/default.toml`，
`wrangler whoami` 显示 account `Fys2388@gmail.com`）。`wrangler.toml` 已被 `.gitignore`
排除（第 22 行），含真实 `account_id` 与 KV `id`，**不入库**。

验证方式：往 KV 临时写一个 `last_dispatch` 键 → `GET /health` 读到 → 删掉 → 再读为 `null`，
确认写入/读取/删除三段链路在**生产环境**都通。全程只用了临时键，不留脏数据。

⚠️ **第一条真实心跳要等到下一个 9:15 档**（北京时间工作日）。在此之前 KV 是空的，
`/health` 返回 `last_dispatch: null`。脚本已对此做了区分，不会误报：

- `last_dispatch == null` → 只打印一条提示并跳过陈旧判定。**不能在这里报 🚨**，
  否则「刚部署完」会被误报成「Worker 停摆」，半夜白查一轮控制台。
  「Worker 从来没 dispatch 过」由 `silent` 分支（按 GitHub 运行次数判定）兜住，不依赖心跳。
- `dispatch_no_run` 只在**确实查到了可信的 GitHub 运行记录**时才判：
  若回看窗口内的日期全部是 `push_error`（GitHub API 调用失败），说明是检查器自己查不到，
  此时判定 `dispatch_no_run` 就是把「检查器坏了」误报成「GitHub 未接单」。
  与全脚本一贯的「查不到 ≠ 没推送」原则一致。

**6.3 未跟踪文件（21 项）— ✅ 已处理（2026-08-25）**

| 类型 | 实际处理 | 数量 |
|---|---|---|
| 调度器配置 `cloudflare-worker/wrangler.toml` | **加入 `.gitignore`**（含 `account_id`，不入库）；新增 `wrangler.toml.example` 已入库，写明获取路径与部署命令 | 1 文件 |
| Agent 学习数据 `data/*.json` | **入库**（`51809dd` 的目的就是持久化学习数据，丢弃等于 Agent 失忆） | 4 文件 |
| 一次性补丁脚本 `scripts/patch_*.py`、`scripts/_patch_*.py`、`scripts/_check_learning.py` | **移到 `archive/patch_scripts/`**。功能已应用到主代码，留着只会误导后续代理。移动前已确认无任何代码引用 | 23 文件 |
| 上传的二进制 `user_upload*.bin` | **加入 `.gitignore`**（真实知识文档在 `knowledge/` 下） | 3 文件 |
| 其它代理状态目录 `.workbuddy/` | **加入 `.gitignore`**，避免被误提交 | 1 目录 |

> 移动是可逆的（git 历史保留），删除类操作均未做。

**6.4 Agent 学习链死结：数据从未落库 — ✅ 已修（2026-09-18）**

**现象**：`tracking.py` 每次运行都正确写入 `data/tracking.jsonl`（日志 `[跟踪] 新记录 N 只推荐股`），
但远端仓库里 `tracking.jsonl` / `evolution_log.jsonl` / `user_feedback.jsonl` **全部不存在**，
`strategy_history.jsonl` 是 **0 字节**，`optimization_state.json` 停在 2026-09-08 不再更新。
周度优化每周只推一句「累计样本：0只，本周不做参数优化，继续收集数据」。

**根因**：`strategy_cloud_deploy.yml` 回传步骤把 7 个路径写在一行，再套 `2>/dev/null || true`：
```bash
# 旧写法（已废）
git add data/tracking.jsonl data/optimization_state.json data/evolution_log.jsonl \
        data/performance_summary.json data/weekly_optimization_report.json data/user_feedback.jsonl 2>/dev/null || true
```
`git add` **只要有一个 pathspec 不存在就整批失败**（exit 128），连已存在的文件也不会被 stage。
干净 checkout 里 `evolution_log.jsonl` / `user_feedback.jsonl` / `performance_summary.json` 不存在
→ 整条 `git add` 失败 → 被 `2>/dev/null || true` 吞掉 → `git diff --cached --quiet` 返回 0
→ 每次都走「无学习数据变化，跳过提交」分支。

本机实测（临时仓库，`git add 存在.txt 不存在.jsonl`）：

| 观测项 | 结果 |
|---|---|
| `git add` 退出码 | **128**，`fatal: pathspec '...' did not match any files` |
| 存在的文件有没有被 stage | **没有**，仍是 `??` 未跟踪 |
| `git diff --cached --quiet` | exit **0**（报无变化） |

**连带失效的机制**（都依赖 tracking 数据）：

| 机制 | 位置 | 实际表现 |
|---|---|---|
| 周度参数优化 | `weekly_optimization.py` | 累计样本恒为 0 → 永不优化 |
| 系统健康度自放宽 | `health_monitor.py`（`v43_push.py:234`） | `🟢 正常（Level 0）`、`连续0推荐：0天`；其状态文件 `data/system_health.json` **不在仓库也不在 git add 列表**，每次运行都是全新状态 |
| 趋势突破饥饿度放宽 | `breakout.py`（连续 3/5/7 天 0 推荐逐级放宽） | 读不到 tracking → 永不触发 |
| 用户反馈通道 | `user_feedback.jsonl` | 文件不存在 → 永远「暂无」 |

**修复**：改为逐文件存在性判断（`if` 语句显式豁免 `set -e`，不会误中断步骤），
并把 `data/system_health.json` 补进列表：
```bash
for f in data/tracking.jsonl \
         data/system_health.json \
         data/optimization_state.json \
         data/evolution_log.jsonl \
         data/performance_summary.json \
         data/weekly_optimization_report.json \
         data/user_feedback.jsonl; do
  if [ -f "$f" ]; then
    git add "$f"
    echo "已暂存学习数据: $f"
  fi
done
```

**验证方法**：下一次运行后日志应出现 `已暂存学习数据: data/tracking.jsonl` 与 `学习数据已回传仓库`，
且 `git log -- data/tracking.jsonl` 能看到提交。
⚠️ 修好之后样本才开始积累，**短期 1–2 周周度优化仍会因样本不足而不做参数调整**，这是正常的。

### 6.4.1 遗留：为什么长期「无推荐」（本次未改，属策略行为变更）

2026-09-18 11:30 一次运行的真实漏斗：

| 策略 | 漏斗 | 卡点 |
|---|---|---|
| MACD共振 | 1200 → 初筛107 → 硬过滤80 → **共振0** | 80 只候选里 日线零轴上方 52 只，但 60min金叉仅 5 只、30min金叉 4 只、15min上穿 3 只；共振要求 4 周期同时满足，3~5 只的交集必然为空。另有 28 只被「空头规避」排除 |
| 超跌反弹 | 1200 → 96 → **超跌0** | 自适应选了「牛市配置」：`drop_20d_min=20%` + `today_gain_min=3%`。当天涨停 63、跌停 0，牛市里要求个股先跌 20% 才配做超跌反弹 = 结构性不可能命中（`adaptive_config.py OVERSOLD_PARAMS`） |
| 趋势突破 | 1200 → 96 → 突破1 → **推荐1** | 唯一产出，且日志 `基本面硬过滤降级：一般及以上无标的，放宽到偏弱及以上`，故标的标「基本面偏弱」 |

共振根因是**时间尺度错配**：日线 MACD 是持续状态，分钟级金叉是瞬时事件，要求 60/30/15min
同时处于金叉态在实盘极罕见。若要放宽，考虑 15min 条件从「必须金叉」改为「金叉或零轴上方」。

**另一个自相矛盾**：报告头部 `🧠 AI市场状态：震荡下行（sideways_down）`、`仓位25%` 来自
`market_cluster.py`（且 `scikit-learn` 未安装、走规则降级分支）；选股参数用的却是
`market_regime.py` 的 `bull_market`（牛市配置）。**仓位按震荡下行给，选股按牛市跑**。
统一两个判定器需要一次口径决策，未在本次处理。

### P1 — 一周内

**6.4 `README.md` 已过期 — ✅ 已修（2026-09-17）**
原 README 有 5 处事实性错误，其中「部署」章节最危险：

| 原文 | 实际 | 危害 |
|---|---|---|
| 「推送代码到 main，工作流自动运行（`strategy-push.yml` / `strategy_cloud_deploy.yml`）」 | 交易时段工作流的 `schedule` **全部禁用**，推 main 不触发任何推送；唯一自动触发源是 Cloudflare Worker | 最危险：会让人以为改完代码自动生效，排查半天 |
| 「`python -m unittest discover -s tests`（26 项）」 | `python -m pytest tests -q`，**92 项** | 用错命令 + 严重误判覆盖度 |
| 「大盘门控 ≥4 分（可开仓）」 | `MARKET_GATE.open_threshold = 3.0`（≥3 可开仓、≥4 用标准档严格信号） | 误判策略行为 |
| 「量能：当日量 > 前 5 日均量 × 1.3」 | `SIGNAL.volume_ratio_min`：标准档 1.2 / 宽松档 1.1 | 误判入场条件 |
| （未提及） | 实际有 **3 个扫描器**（MACD 共振 / 超跌反弹 / 趋势突破）+ 大盘双模式 standard/relaxed | 根本不知道系统同时跑了几套策略 |

新 README 的做法：**只讲结构，不复述参数**——参数一律指向 `config.py`（唯一来源），
权威说明指向 `AGENTS.md`。这样下次改参数不会再次让 README 过期。

**顺带发现并归档：`README_LOCAL_RUN.md` 描述的是已废弃架构 — ✅ 已处理**
该文档要求用 Windows 任务计划程序**本机每 5 分钟定时推送**，与铁律 1「部署只在云端」直接冲突，
照做会造成 **云端 + 本机双份推送**；且它「验证」章节引用的诊断行格式（`📡 数据源：… | 校验：…`）
已在提交 `1fdc849`「推送极简版」中被删除。

已 `git mv` 到 `archive/README_LOCAL_RUN_DEPRECATED.md` 并加 ⛔ 废弃头
（保留原文以便追溯设计意图，git 历史保留、可逆）。
`scripts/run_local.ps1` / `run_local.sh` 保留不动，仅限**手动跑一次做链路验证**。

**6.5 GitHub Actions 配额**
节奏已是每 30 分钟。若再加密，需先评估免费配额（提交 `63df125` 的动机）。

**6.6 知识库与策略的耦合**
`knowledge/` 下有大量「熊猫有财」批次数学文档，与选股代码无运行时依赖，
只是作为 Agent 学习资料。后续若要瘦身仓库，这是最大的体积来源。

---

## 7. Codex 接手第一天检查清单

```bash
# 1. 确认本地与远端一致
git fetch origin && git status -sb

# 2. 跑全量测试
python -m pytest tests -q
#    当前基线：92 passed / 0 failed，约 1.6s，全程 0 次真实网络请求。
#    出现任何 failed = 回归；耗时 >10s = 有单测漏了 mock、在打真实行情接口（见 §6.0）。

# 3. 手动触发一次扫描 + 一次盘前，确认推送链路
gh workflow run "V1.0 MACD多周期共振策略云推送" --repo fys2388/dragon-strategy-v4.3 -f test_mode=true
gh workflow run "V1.0 MACD多周期共振策略云推送" --repo fys2388/dragon-strategy-v4.3 -f report_mode=premarket
#    ⚠️ premarket 有 9:45 守卫：若在 9:45 之后执行，会被跳过并打印「已过盘前窗口」。
#    此时改用 morning_noon_push.yml 验证/补发盘前报告（不经守卫）：
gh workflow run "Morning & Noon Report Push" --repo fys2388/dragon-strategy-v4.3
#    观察飞书是否收到「🌅 盘前报告」；运行日志应有 REPORT_MODE / TRIGGER 字段。

# 4. 确认调度器还在跑（否则一切自动推送都会停）
#    最快：gh run list --limit 20 看今天有没有 workflow_dispatch 来源的运行
#    已有自动监控（§6.2）：scheduler_health_check.yml 每天 15:00 BJT 检查最近 3 个交易日，
#    停推会推飞书 🚨 并让该工作流变红。想立刻手动验一次：
gh workflow run "调度器健康检查" --repo fys2388/dragon-strategy-v4.3 -f always_report=true
#    深度排查：Cloudflare 控制台 → Workers → macd-strategy-scheduler → Scheduled events
#    （看是否还在按 */15 触发）；或浏览器访问 Worker URL 看是否返回 {"success":true,"status":204}
#    配了 WORKER_HEALTH_URL 后，浏览器访问 <worker-url>/health 可看 Worker 最近一次
#    dispatch 的时间戳与状态码（§6.2.2）。

# 5. §6.3 的未跟踪文件已处理（2026-08-25），确认 git status 干净即可

# 6. 读 AGENTS.md 全文 + 本文件 §6.0 / §6.2 / §6.4
#    §6.0 测试套件（92/0 全绿）、§6.2 调度器监控（已加，含飞书送达判定与 KV 心跳）、
#    §6.4 README（已重写）都已闭环。
#    仍真正未决：§6.2.2 的 Worker KV 心跳需你在 Cloudflare 控制台手动配两步；
#    §6.5 Actions 配额；§6.6 knowledge 耦合。
```

**验证交接成功的标准**：手动触发 premarket 与 scan 都能收到飞书；
`gh api` 能看到最近的 `workflow_dispatch` 运行记录；`worker.js` 的调度表与实际推送时间一致。

---

## 8. 快速参考：交接方本次会话改了什么

| 提交 | 内容 |
|---|---|
| `656c140` | 盘前报告落款文案「每5分钟」→「每10分钟」 |
| `3ab56fe` | 盘前报告并入云端 9:15 档（`v43_push.py` REPORT_MODE 分支）；`morning_noon_push.yml` 停用定时 |
| `6302bf1` | `strategy_cloud_deploy.yml` 增加 `report_mode` 手动输入（auto/premarket/scan） |
| `d198f77` | 盘前守卫仅对定时档生效（`TRIGGER=schedule`），手动触发可随时验证 |
| `8f240ec` | 交接文档首版（`AGENTS.md` + `docs/HANDOFF.md`） |
| `git log -1` | 交接收尾：盘前守卫改为纯时间判断、未跟踪文件清理、测试基线更正、文档同步（见最新提交） |

云端验证运行：`32803531452`（premarket ✅ HTTP 200）、`32803646853`（scan ✅ HTTP 200，扫描 ~5.5 分钟）。

> 注：以上 4 个提交都已在远端 `main` 历史中（`d198f77` 是当前 HEAD 的祖先），后续并行代理的提交叠加在其上。

---

## 9. Agent 能力提分改造（P0/P1/P2 全量落地）

上一轮交接后，Agent 学习闭环被评为「56/100」，主因不是代码少，而是**声称有的能力实际没接通**。
本节记录本轮改动，全部已跑通 `python -m pytest tests -q`（**118 passed / 0 failed，1.8s**）。

### 9.1 P0 — 阻断级（学习闭环完全无法启动）

| # | 问题 | 修复 |
|---|---|---|
| P0-1 | 完成窗口 20 交易日 + 周度优化 ≥5 条 / 进化 ≥10 条 → 冷启动期样本门永远打不开 | 新增 `strategies/macd_resonance/loop_config.py` 作为**唯一事实源**：`COMPLETION_DAY=3`、`COMPLETION_DAY_FIELD="day3_return_pct"`、`MIN_COMPLETED_SAMPLES=3`、`min_samples_for(kind)`。`tracking` / `weekly_optimizer` / `evolution_engine` 全部改读它 |
| P0-2 | `tracking.update_performance()` 遇到缺 K 线日 `break` 整段中断 → 短窗口收益永远算不出 | 改 `continue` 跳过；同时 `full_window_done` 标记保留，5/10/20 日收益照常计算，只是 `completed` 提前到第 3 个交易日 |
| P0-3 | `adaptive_config.MACD_PARAMS.min_score` 量纲是 40–80，而 `signal_engine` 打分上限只有 4.0 → `min_score` 过滤条件恒不满足 | `min_score` 改为 1.0–4.0 量纲（含详细注释说明量纲来源），`config.py` 同步 |
| P0-4 | `health_monitor` 降级覆盖算出来了但**没人读**，且键名对不上扫描器 | 重写覆盖结构为 `macd` / `oversold` / `breakout` / `general` 四组，键名逐个对齐三个扫描器实际读取的参数；新增 `HealthMonitor.merge_override()`（staticmethod，不改入参）；`scanner` / `oversold_rebound` / `breakout` 都接收 `param_override` 并真正应用 |
| P0-5 | `strategy_cloud_deploy.yml` 回传清单缺 4 个文件 | 清单补为 13 个：新增 `data/optimized_params.json`（**进化引擎的参数回写目标，此前漏了 = 每次进化结果被清掉**）、`data/strategy_weights.json`、`data/ab_test_state.json`、`data/strategy_history.jsonl`、`data/risk_state.json`、`data/position_sizing.json` |

**P0-3 是关键根因**：`min_score` 量纲错位会让 MACD 共振在任何行情下都产出 0 推荐，
这正是 §6.4.1 长期「无推荐」的另一个结构性原因（与 15min 金叉条件叠加）。

### 9.2 P1 — 文档与实现不一致

| # | 问题 | 修复 |
|---|---|---|
| P1-1 | `health_monitor` 降级「只上不下」：`_check_recovery` 用 `datetime.now() - last_recommendation_date` 算天数，跨进程持久化后永远进不了 `days_since == 0` 分支 | `_check_recovery(record_date)` 改为按「本次记录日期 - 上次有推荐日期」相减，去掉墙钟依赖；`_recompute_zero_days` 改为从 `daily_recommendations` 幂等推导连续 0 推荐天数（盘中一天约被调用 10 次，原来会放大计数） |
| P1-2 | 「AI 打分」实际是规则打分，却对外说成上涨概率 | `ai_predictor._rule_based_predict` 主字段改为 `rule_score`（0–100），显式标注 `score_basis="rule_based"` + `probability_is_actual_model=False`，并附 `rule_hits`（命中了哪些规则）；`predict()` 在有 LightGBM 时写 `score_basis="model"`；`AIScorer` 只在实际模型概率时写 `ai_probability`；`add_ai_info_to_message` 按 basis 分别措辞（规则打分不出现「上涨概率」） |
| P1-3 | `AIScorer.add_ai_info_to_message` 从未被调用 → 推送里看不到打分 | `v43_push.py` 新增 `append_ai_score_block()`，三个策略消息都在打分过滤后附加打分块 |
| P1-4 | 训练好的模型只上传 artifact，从不进仓库 → 推送环境永远加载不到 | `weekly_model_training.yml` 新增「提交模型文件到仓库」步骤；`strategy_cloud_deploy.yml` 依赖安装补 `lightgbm`（原清单缺它，即使模型在仓库也会静默降级为规则打分） |
| P1-5 | 15min 共振条件「必须瞬时金叉」→ 4 周期交集必为空 | 改为状态型：`tf15_above_zero`（零轴上方）+ `tf15_golden`（3 日内金叉），符合 §6.4.1 的建议方向 |
| P1-6 | `evolution_engine.get_evolution_report()` 内部偷偷写参数 → 每周参数被写两遍、报告有副作用 | 报告改为纯展示（只消费传入结果，缺省时不写盘）；`run_weekly_evolution()` 改为「先 mutation、再展示」，并显式汇报 A/B 测试状态 |
| P1-7 | `optimize_strategy_weights` 只统计 resonance / oversold，breakout 被排除 → 权重永远算成 0.5/0.5 | 纳入 breakout，三策略均参与评分与归一化 |
| P1-8 | `strategy_history.jsonl` 记录里没有 regime / 降级档位 | `_append_history` 补记 `regime` / `degradation_level` / `recommend_count` / `strategy`，供复盘与看板按环境切片 |

### 9.3 P2 — 闭环缺件

| # | 问题 | 修复 |
|---|---|---|
| P2-1 | `user_feedback.record_feedback()` 全仓库 0 调用方 → 反馈数据恒为 0 | 新增 `scripts/submit_feedback.py` + `.github/workflows/user_feedback.yml`（`workflow_dispatch`，无 `schedule`），反馈落盘后提交回仓库 |
| P2-2 | `scripts/replay_validation.py` 无工作流引用 → 策略有效性从未被周期性验证 | 新增 `.github/workflows/weekly_replay_validation.yml`（周日 UTC 15:00 = BJT 23:00）；`send_feishu` 增加 `PUSH_FEISHU` 开关，手动触发默认不推群 |
| P2-3 | 学习闭环 0 测试 | 新增 `tests/test_agent_loop.py`（**26 项**）：loop_config / tracking 第 3 日完成 + 停牌跳格 / 周度优化冷启动门槛 / 进化引擎门槛与无副作用报告 / 健康度降级阶梯 L0→L3 + 推荐即恢复 + 同日幂等 / 用户反馈写入 / AI 打分诚实标注 |

### 9.4 测试基线更新

| 项 | 改前 | 改后 |
|---|---|---|
| 用例数 | 92 | **123**（+26 学习闭环，+5 共振闸门） |
| 耗时 | ~1.6s | ~2.2s |
| 真实网络请求 | 0 | **0**（新增测试全部 mock `data_source`，写盘重定向到临时目录） |

> `AGENTS.md` 里的「92 passed」基线已同步改成 123（见 §9.6）。

### 9.5 仍未决（需要人工决策，本轮未动）

1. **§6.4.1 的 market_cluster vs market_regime 口径冲突**：报告头部仓位按 `sideways_down` 给、
   选股参数按 `bull_market` 跑。统一两个判定器需要一次口径决策。
2. **样本攒够后回调冷启动阈值**：`loop_config.COLD_START` 目前为 `True`、门槛为 3；
   攒到 5+ 条 completed 样本后应把门槛回调到 `MIN_SAMPLES_FULL=5`
   （`min_samples_for("full")` 已备好），避免长期用小样本过拟合。
3. **A/B 测试框架仍是死代码**：`evolution_engine` 的 `start_ab_test` / `record_ab_result` /
   `conclude_ab_test` 没有扫描链路调用方。本轮让 `run_weekly_evolution()` 显式汇报其状态，
   但接入扫描链路属策略行为变更，未做。
4. **`data/models/lgbm_model.pkl` 是否真的能训练出来**取决于 `weekly_model_training.py`
   的样本量；模型产出后 AI 打分才会从 `rule_based` 切到 `model`。

### 9.6 §6.4.1 收尾：60/30min 闸门改状态型 + 闸门可观测（2026-09-22）

上一轮只修了 15min 的瞬时金叉问题，**60min 与 30min 仍然是「刚发生金叉」口径**。
上线后第一次拿到硬证据（run `35692924401`，14:00 档）：

```
初筛 1200 → 139 只 → 硬过滤 104 只 → 共振信号 0 只 → 推荐 0 只
周期信号统计：日线零轴上方74只 | 60min金叉6只 | 30min金叉3只
```

104 只候选里 60min 瞬时金叉只有 6 只、30min 只有 3 只 —— 三个瞬时事件取交集必然为空。
`min_score` 量纲其实不是本轮瓶颈（标准档信号恒打 3.5 分，远高过 `min_score=1.5`），
**真正的瓶颈是闸门本身**。另外还查出打分公式是死值：
`score = 1 + 1 + (0.5 if dif_d>0) + 0.5*TIMEFRAME_ORDER["60m"]`，
闸门都过了就恒打 3.5，`min_score` 过滤形同虚设。

**改了什么**（`config.py` / `signal_engine.py` / `scanner.py`）：

| 项 | 改前 | 改后 |
|---|---|---|
| 60min 闸门 | `recent_golden_cross(lookback=3)` **且** DIF>0 **且** 红柱逐根放大（3 个瞬时条件） | `tf60_state_or_cross`：DIF 在零轴上方 **或** 近 8 根金叉；红柱只要为正（`require_red_bar_expanding=False`） |
| 30min 闸门 | `recent_golden_cross(lookback=3)` | 同上，lookback 8（宽松档 12） |
| 打分 | 硬编码恒 3.5 | 按各周期实际状态逐项累加：零轴上方 0.5 / 仅近期金叉 0.25；放量 0.5、突破 0.5，未确认各 0.25。区间 1.0–3.5，与 `min_score` 同量纲，`min_score` 重新有区分度 |
| 可观测 | 只有一行「共振信号 0 只」 | `SignalEngine` 加带锁的 `record_gate/get_gate_counts/reset_gate_counts`，C~H 每道闸门都计数（12 线程并发）；日志打「共振闸门拒绝明细」，**0 推荐时飞书消息直接写拒因**（如「无推荐｜硬过滤后104只全部被拒：H未突破60min平台62只、G量能不足×1.2 28只」） |

保留了 `tf60_state_or_cross` / `tf30_state_or_cross` / `require_red_bar_expanding`
三个开关，想回退到旧的「必须刚金叉」口径改配置即可，不用翻代码。

**仍然保留的严格项**：标准档 `require_breakout=True`（收盘价须突破近 20 根 60min 平台）、
量比 ≥1.2。所以下一次推送仍可能 0 推荐 —— 但现在消息里会直接告诉你卡在哪道闸门，
不用再翻 Actions 日志。这是本轮唯一没法靠静态阅读代码确定的事，需要下一次实盘观察。

**测试**：`tests/test_signal_engine.py` 新增 `TestLongEntryStateBased`（5 项），
其中 `test_bullish_state_without_fresh_cross_now_passes` 就是针对本 bug 的回归用例
（DIF 全程高于 DEA，`recent_golden_cross` 在任意 lookback 下都为 False）；
另 4 项覆盖闸门计数与宽松档宽回看。全量 **123 passed / 0 failed，约 2.2s**。
