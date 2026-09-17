# HANDOFF.md — 交接给 Codex 的背景说明（一次性阅读）

> 日常开发请读根目录 `AGENTS.md`（协作手册 + 已知坑）。
> 本文件只讲「交接这个时点发生了什么、有什么坑、接手第一天该做什么」。**处理完未决事项后可归档到 `archive/`。**

---

## 1. 交接时点

| 项 | 值 |
|---|---|
| 远端主分支 | `main`（直接推 main，无 PR 流程） |
| 本地与远端 | 已同步，无未提交改动 |
| 测试 | 82 项全过（`python -m pytest tests -q`） |
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
| Cloudflare `account_id` | `cloudflare-worker/wrangler.toml`（**未入库**） | 重部署 Worker 前必须有此文件 |
| GitHub token（Worker 用） | Cloudflare Worker Secrets `GITHUB_TOKEN`，需 `repo` 权限 | 失效则静默停推 |
| gh CLI 登录态 | 本机 `gh auth`（scope 含 `repo`） | 换机器需重新 `gh auth login` |
| 本地代理 | `127.0.0.1:7897`（系统代理，ProxyServer） | git 直连 GitHub 会 21s 超时 |

**注意 `wrangler.toml` 未入库**：任何代理 clone 全新仓库后都无法直接重部署 Worker。
建议要么把它加入 `.gitignore` 并写明获取方式，要么脱敏后入库（见 §6 未决项 1）。

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

**6.1 盘前守卫空转**
`v43_push.py` 的守卫是 `TRIGGER == "schedule" and hm >= 945`，
但 schedule 已禁用、Worker 走 `workflow_dispatch`，条件**永远不成立**。
若某次盘前触发被延迟（历史上 GitHub 延迟过 76 分钟），盘前报告会撞上盘中报告 —— 也就是最初被投诉的「两个报告」问题会复现。

- 修复 A（简单）：守卫改成只看时间 —— `mode == "premarket" and hm >= 945 → skip`。
- 修复 B（更彻底）：在 Worker 侧判断，若当前时间已过 9:45 就不触发 premarket。

**6.2 调度器无监控（单点静默失败）**
Cloudflare Worker 挂掉、或其 `GITHUB_TOKEN` 过期 → **完全停推，且没有任何告警**。
建议在 `evening_review.yml` 或周度工作流里加一个「今日是否收到盘中推送」的检查，缺失则发飞书告警。

**6.3 未跟踪文件（21 项）需要处置决定**

| 类型 | 文件 | 建议 |
|---|---|---|
| 调度器配置 | `cloudflare-worker/wrangler.toml`（0.2KB，含 `account_id`） | **入库（脱敏后）** 或加入 `.gitignore` 并在 `AGENTS.md` 写明来源。不处理会让任何新 clone 无法重部署 Worker |
| Agent 学习数据 | `data/{optimization_state,weekly_optimization_report,data_quality_fixes,backtest_1_8_result}.json`（~12KB） | **入库**。提交 `51809dd` 的目的就是持久化学习数据；丢弃等于 Agent 失忆 |
| 一次性补丁脚本 | `scripts/_patch_*.py`（5 个）、`scripts/patch_*.py`（9 个）、`scripts/_check_learning.py`（~50KB） | **移到 `archive/patch_scripts/`**。功能已应用到主代码，留着只会误导后续代理 |
| 上传的二进制 | `user_upload.bin`、`user_upload2.bin`、`user_upload_xiongmao.bin`（~33KB，仓库根目录） | **加 `.gitignore` 或移出仓库**。根目录放二进制属于误投放 |

> 以上都是**删除/移动**类操作，请用户确认后再做；交接方未擅自处理。

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
python -m pytest tests -q            # 期望 82 passed

# 3. 手动触发一次盘前 + 一次扫描，确认推送链路
gh workflow run "V1.0 MACD多周期共振策略云推送" --repo fys2388/dragon-strategy-v4.3 -f report_mode=premarket
# 观察飞书是否收到「🌅 盘前报告」；运行日志应有 REPORT_MODE: premarket / TRIGGER: workflow_dispatch

# 4. 确认调度器还在跑（否则一切自动推送都会停）
#    - Cloudflare 控制台 → Workers → macd-strategy-scheduler → Scheduled events 日志
#    - 或浏览器访问 Worker URL 看是否返回 {"success":true,"status":204}
#    - 或检查 GitHub Actions 里近几小时是否有 schedule=workflow_dispatch 的运行

# 5. 检查 .workbuddy/ 与 §6.3 的未跟踪文件，决定是否清理

# 6. 读 AGENTS.md 全文 + 本文件 §6 未决事项，确认已了解「盘前守卫空转」与「调度器单点」
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

云端验证运行：`32803531452`（premarket ✅ HTTP 200）、`32803646853`（scan ✅ HTTP 200，扫描 ~5.5 分钟）。

> 注：以上 4 个提交都已在远端 `main` 历史中（`d198f77` 是当前 HEAD 的祖先），后续并行代理的提交叠加在其上。
