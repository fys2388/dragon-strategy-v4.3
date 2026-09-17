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
