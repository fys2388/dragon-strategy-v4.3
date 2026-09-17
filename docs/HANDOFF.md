# HANDOFF.md — 交接给 Codex 的背景说明（一次性阅读）

> 日常开发请读根目录 `AGENTS.md`（协作手册 + 已知坑）。
> 本文件只讲「交接这个时点发生了什么、有什么坑、接手第一天该做什么」。**处理完未决事项后可归档到 `archive/`。**

---

## 1. 交接时点

| 项 | 值 |
|---|---|
| 远端主分支 | `main`（直接推 main，无 PR 流程） |
| 本地与远端 | 已同步，无未提交改动 |
| 测试 | **71 passed / 11 failed**（测试落后于代码，明细见 §6.0） |
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

**6.0 测试套件是红的：71 passed / 11 failed**
当前 `main` 的 11 项失败全部是「代码改了、测试没跟」，**不是代码回归**。
接手前必须知悉：这套测试目前**不能**作为改动是否安全的判据。

| 失败用例 | 根因 | 建议修复 |
|---|---|---|
| `test_market_gate.py::TestLimitUpDown`（3 项） | **mock 目标漂移**：`get_limit_up_down_count()` 新增了第 1 步 `_get_em_limit_pool_count()`（东财官方涨跌停池 push2ex），该函数直接调 `requests.get`，**绕过了** `_request_get`。测试只 mock 了 `ds._request_get`，于是第 1 步打到真实东财、返回真实数据（如 47/0）并提前 return，后续断言全部落空 | 改 mock 目标为 `mock.patch("strategies.macd_resonance.data_source.requests.get", ...)`；或给 `_get_em_limit_pool_count` 抽出可注入的请求函数。修完这三项将完全离线，不再依赖真实行情 |
| `test_market_gate.py::TestScannerDiagnosticLine::test_build_message_has_trigger_line` | **断言过期**：`build_message()` 输出已简化为 `📊 MACD共振：大盘5/7 🟢可开仓\n  无推荐`，不再包含 `⏱ 触发时间：北京时间`、`扫描耗时`、`涨停45家/跌停2家` | 先确认精简格式是否符合推送需求；若需保留触发时间，改 `scanner.py build_message()`，**不要**为了过测试而改断言 |
| `test_data_validator.py::TestRegime`（4 项）+ `TestScannerIntegration`（2 项）+ `TestBuildMessageDataSourceLine`（1 项） | 市场环境分级阈值、数据源行文案变化，断言未同步 | 逐个对照 `data_validator.py` / `scanner.py` 当前实现修正断言 |

**优先级判断**：不阻断线上推送，但会让后续所有改动失去回归保护。建议把「修这 11 项」作为接手后的第一个任务。

**6.1 盘前守卫空转 — ✅ 已修**
守卫已从 `TRIGGER == "schedule" and hm >= 945` 改为纯时间判断 `mode == "premarket" and hm >= 945 → skip`，
不再依赖 `TRIGGER`（schedule 已禁用、Worker 走 `workflow_dispatch`，旧条件永不成立 = 空转）。
「两个报告」撞车风险已消除。

副作用：9:45 之后手动触发 `strategy_cloud_deploy.yml -f report_mode=premarket` 会被跳过；
窗口外补发盘前报告请走 `morning_noon_push.yml`（`workflow_dispatch`，不经守卫）。
可选加固：在 Worker 侧 `handleTrigger` 里也判断一次时间（修复 B），双保险。

**6.2 调度器无监控（单点静默失败）**
Cloudflare Worker 挂掉、或其 `GITHUB_TOKEN` 过期 → **完全停推，且没有任何告警**。
建议在 `evening_review.yml` 或周度工作流里加一个「今日是否收到盘中推送」的检查，缺失则发飞书告警。

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

**6.4 `README.md` 已过期**
README 仍写「`strategy-push.yml` / `strategy_cloud_deploy.yml` 自动运行」「每 5 分钟」「unittest 16 项」。
实际是：外部调度器触发、每 30 分钟、pytest 82 项。建议把 README 的「部署」章节改为指向 `AGENTS.md`。

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
#    当前基线：71 passed / 11 failed。11 项是已知失败（§6.0），不要当成回归误判。
#    若出现「新增」失败 → 才是你改坏了东西。

# 3. 手动触发一次扫描 + 一次盘前，确认推送链路
gh workflow run "V1.0 MACD多周期共振策略云推送" --repo fys2388/dragon-strategy-v4.3 -f test_mode=true
gh workflow run "V1.0 MACD多周期共振策略云推送" --repo fys2388/dragon-strategy-v4.3 -f report_mode=premarket
#    ⚠️ premarket 有 9:45 守卫：若在 9:45 之后执行，会被跳过并打印「已过盘前窗口」。
#    此时改用 morning_noon_push.yml 验证/补发盘前报告（不经守卫）：
gh workflow run "Morning & Noon Report Push" --repo fys2388/dragon-strategy-v4.3
#    观察飞书是否收到「🌅 盘前报告」；运行日志应有 REPORT_MODE / TRIGGER 字段。

# 4. 确认调度器还在跑（否则一切自动推送都会停）
#    - Cloudflare 控制台 → Workers → macd-strategy-scheduler → Scheduled events 日志
#    - 或浏览器访问 Worker URL 看是否返回 {"success":true,"status":204}
#    - 或检查 GitHub Actions 里近几小时是否有 workflow_dispatch 来源的运行

# 5. §6.3 的未跟踪文件已处理（2026-08-25），确认 git status 干净即可

# 6. 读 AGENTS.md 全文 + 本文件 §6.0 / §6.2：
#    「测试套件是红的」与「调度器是单点」是接手后最该先处理的两件事
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
