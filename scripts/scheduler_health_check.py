# -*- coding: utf-8 -*-
"""调度器健康检查：检测 Cloudflare Worker / GITHUB_TOKEN 静默失效。

背景（docs/HANDOFF.md §6.2）：
    所有交易时段推送都由 Cloudflare Worker 调 workflow_dispatch 触发。
    Worker 挂掉、或其 Secrets.GITHUB_TOKEN 过期 = 完全停推，
    而仓库里原本没有任何东西会告警。

为什么触发源必须是 GitHub schedule（而不是放进 evening_review.yml）：
    evening_review.yml 本身也是 Worker 在 15:30 触发的 —— Worker 一挂它也跑不了，
    把检查放进去就是「用停摆的系统监控停摆的系统」。
    GitHub schedule 是本仓库唯一不依赖 Worker 的自动触发源。

cron 延迟容忍（实测）：
    本仓库 schedule 实测延迟 4h23m~4h32m（daily_position_monitor.yml）。
    因此 cron 定在 15:00 BJT，实际执行约 19:30 BJT，当日全部档位（9:15~15:30）
    都已结束，不会误报；且脚本只评估「已完整结束」的交易日，
    即使延迟更久（甚至跨到次日）结论依然成立。

判定口径：数 workflow_dispatch 运行次数，外加 Worker 心跳比对。
    - 数运行次数对节假日免疫：Worker 不检查 A 股休市日历，节假日照样触发。
    - 数运行次数对检查自身延迟免疫：只看历史日。

Worker 心跳比对（需配置 WORKER_HEALTH_URL，可选）：
    worker.js 在每次 dispatch 成功/失败后往 Cloudflare KV 写一条时间戳，
    /health 端点返回。这让下面三种「都表现为 runs==0」的情况第一次能被区分开：
        heartbeat_stale    Worker 没跑（暂停/删除/Cron 触发器丢失）
        dispatch_no_run    Worker 说成功了，但 GitHub 没接单（配额耗尽/服务异常）
        dispatch_failed    dispatch 调用本身失败（401/403 = GITHUB_TOKEN 失效，404 = 工作流改名）
    未配置 WORKER_HEALTH_URL 时跳过这一段，不影响原有的运行次数判定。

飞书送达判定（已封堵的盲区）：
    本脚本自身和 scripts/v43_push.py 都校验飞书正文的 StatusCode/code，
    不再只看 HTTP 200；推送未被飞书接受时 v43_push.py 以非零退出码结束，
    工作流变红 → 会被下面的 failed_run 分支抓到。

用法：
    python scripts/scheduler_health_check.py                  # 正常：仅异常时推送
    python scripts/scheduler_health_check.py --always-report   # 每次都推送（验证飞书链路）
    python scripts/scheduler_health_check.py --dry-run         # 只打印，不推送
    python scripts/scheduler_health_check.py --selftest        # 打印一次模拟告警文案

环境变量：
    GH_REPO             仓库 full_name，默认 fys2388/dragon-strategy-v4.3
    GITHUB_TOKEN        具备 actions: read 的 token（Actions 内置）
    FEISHU_WEBHOOK_URL  告警通道
    WORKER_HEALTH_URL   Cloudflare Worker 的 /health 端点完整 URL（可选，启用心跳比对）
    MAX_HEARTBEAT_AGE_H 心跳陈旧阈值（小时），默认 6.0
    ALWAYS_REPORT       "true" 时正常情况也推送
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 emoji 报错
# （与 scripts/daily_review_push.py、morning_noon_push.py 保持一致）
for _stream in (sys.stdout, sys.stderr):
    try:
        _re = getattr(_stream, "reconfigure", None)
        if _re:
            _re(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = os.environ.get("GH_REPO", "fys2388/dragon-strategy-v4.3")
PUSH_WORKFLOW = "strategy_cloud_deploy.yml"   # 盘中/盘前推送
REVIEW_WORKFLOW = "evening_review.yml"        # 收盘复盘

# 期望值与 cloudflare-worker/worker.js 的 SCHEDULE 一一对应，改节奏时同步改这里。
EXPECTED_PUSH_PER_DAY = 10    # 9:15 盘前 1 次 + 盘中 9 档（10:00~14:30 各30分钟 + 14:45 尾盘）
EXPECTED_REVIEW_PER_DAY = 1   # 15:30 复盘

CHECK_DAYS = 3                # 回看最近 N 个完整交易日
API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "macd-scheduler-health-check"

# 心跳陈旧阈值。本工作流 cron 定 15:00 BJT，实测延迟 ~4.5h → 约 19:30 BJT 执行，
# 当日最后一个档位是 15:30 复盘。6.0h 意味着「最后成功 dispatch 在 13:30 BJT 之后」
# 就算新鲜；Worker 在 13:30 之前挂掉会被判为陈旧。想更严格就调小这个值。
MAX_HEARTBEAT_AGE_H = float(os.environ.get("MAX_HEARTBEAT_AGE_H", "6.0"))

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class ApiError(Exception):
    """GitHub API 多次重试后仍不可用（无法判定健康状态）。"""


# ------------------------------------------------------------
# 时间
# ------------------------------------------------------------
def now_bjt() -> datetime:
    """当前北京时间（显式 +8，不依赖 runner 的 TZ 设置）。"""
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


def day_label(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}({_WEEKDAY_CN[d.weekday()]})"


def completed_weekdays(n: int, ref: Optional[date] = None) -> List[date]:
    """最近 n 个「已完整结束」的工作日（不含 ref 当天），旧 → 新。

    只排除周六日，不处理 A 股节假日：Worker 也不检查节假日，节假日照样触发，
    所以按运行次数判定不会误报。
    """
    ref = ref or now_bjt().date()
    days: List[date] = []
    d = ref - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days


# ------------------------------------------------------------
# GitHub API
# ------------------------------------------------------------
def _api_get(token: str, path: str, retries: int = 3) -> dict:
    """GET api.github.com/repos/{REPO}{path}。404 原样返回 {"_404": True}，重试耗尽抛 ApiError。"""
    import requests

    url = f"{API_BASE}/repos/{REPO}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT,
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return {"_404": True}
            print(f"  ⚠️ API HTTP {resp.status_code}: {resp.text[:160]}")
        except Exception as e:
            print(f"  ⚠️ API 异常 attempt{attempt + 1}: {type(e).__name__} {e}")
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise ApiError(f"{path} 重试 {retries} 次仍失败")


def fetch_dispatch_runs(token: str, workflow_file: str, day: date) -> Dict:
    """取某个工作日（北京时间）该工作流的 workflow_dispatch 运行。

    北京时间交易日 9:15~15:30 对应 UTC 同日 01:15~07:30，故直接按 UTC 自然日过滤。

    返回 {"missing": bool, "runs": [...]}
        missing=True  → 工作流文件不存在（被删除/改名），Worker 的 dispatch 必然 404。
        runs=[]       → 文件存在，但当天没有任何 workflow_dispatch 运行。
    """
    created = f"{day}T00:00:00Z..{day}T23:59:59Z"
    data = _api_get(token,
                    f"/actions/workflows/{workflow_file}/runs"
                    f"?created={created}&per_page=100")
    if data.get("_404"):
        return {"missing": True, "runs": []}
    runs = [r for r in data.get("workflow_runs", [])
            if r.get("event") == "workflow_dispatch"]
    return {"missing": False, "runs": runs}


# ------------------------------------------------------------
# 判定
# ------------------------------------------------------------
def evaluate(token: str, days: List[date]) -> Tuple[List[Dict], List[Tuple[str, str]], List[str]]:
    """统计每个交易日的运行次数。

    返回 (per_day, problems, api_errors)
        problems 元素为 (级别标记, 分类, 说明)：
            级别 "🚨"（停推级）/ "⚠️"（提示级）
            分类 silent / missing_workflow / partial / failed_run / api_error
    """
    per_day: List[Dict] = []
    problems: List[Tuple[str, str]] = []
    api_errors: List[str] = []

    for day in days:
        label = day_label(day)
        row: Dict = {"label": label}
        for key, wf, expect, what in (
            ("push", PUSH_WORKFLOW, EXPECTED_PUSH_PER_DAY, "盘中/盘前推送"),
            ("review", REVIEW_WORKFLOW, EXPECTED_REVIEW_PER_DAY, "收盘复盘"),
        ):
            errored = False
            try:
                res = fetch_dispatch_runs(token, wf, day)
            except ApiError as e:
                errored = True
                api_errors.append(f"{label} {wf}: {e}")
                res = {"missing": False, "runs": []}
            row[f"{key}_error"] = errored
            row[f"{key}_missing"] = res["missing"]
            row[key] = len(res["runs"])
            row[f"{key}_failed"] = [r["id"] for r in res["runs"]
                                    if r.get("conclusion") not in ("success", None)]
            # API 失败时不做判定：「查不到」≠「没推送」，
            # 否则会把「检查器自己坏了」误报成「Cloudflare Worker 停摆」。
            if errored:
                continue
            if res["missing"]:
                problems.append(("🚨", "missing_workflow",
                                 f"{label} 工作流文件 `{wf}` 不存在（已删除或改名），"
                                 f"Worker 的 dispatch 调用必然 404 → {what}全停"))
            elif row[key] == 0:
                problems.append(("🚨", "silent",
                                 f"{label} 全天 0 次 {what}调度 → "
                                 f"Cloudflare Worker 未运行，或其 Secrets.GITHUB_TOKEN 已失效"))
            elif row[key] < expect:
                problems.append(("⚠️", "partial",
                                 f"{label} {what}只触发 {row[key]}/{expect} 次 → "
                                 f"Worker 部分档位漏触发（检查 SCHEDULE 与交易时段判断）"))
            if row[f"{key}_failed"]:
                ids = ",".join(str(i) for i in row[f"{key}_failed"][:3])
                problems.append(("⚠️", "failed_run",
                                 f"{label} {what}有 {len(row[f'{key}_failed'])} 次运行未成功"
                                 f"（run id: {ids}）→ 检查 v43_push.py 推送链路"))
        per_day.append(row)

    if api_errors:
        problems.append(("⚠️", "api_error",
                         f"本次检查有 {len(api_errors)} 项 GitHub API 调用失败，"
                         f"受影响日期的数字不可信（是「查不到」，不是「停推」）"))

    return per_day, problems, api_errors


# ------------------------------------------------------------
# Worker 心跳（可选，需 WORKER_HEALTH_URL）
# ------------------------------------------------------------
def fetch_worker_heartbeat(url: str, retries: int = 2) -> Optional[Dict]:
    """GET Cloudflare Worker 的 /health 端点。

    返回 None 表示端点不可达（网络/域名/Worker 下线），由调用方判为异常；
    返回 dict 即 worker.js 的 /health 响应体。
    """
    import requests
    base = url.rstrip("/")
    if not base.endswith("/health"):
        base += "/health"
    last_err = ""
    for attempt in range(retries):
        try:
            resp = requests.get(base, timeout=15, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                return resp.json()
            last_err = f"HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            last_err = f"{type(e).__name__} {e}"
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    print(f"  ⚠️ Worker 心跳端点不可达: {base} -> {last_err}")
    return None


def heartbeat_problems(hb: Dict, per_day: List[Dict]) -> List[Tuple[str, str, str]]:
    """比对 Worker 心跳与 GitHub 运行记录，产出可区分的告警。

    hb 为 /health 响应体。时间戳统一按 UTC 毫秒比较（Date.now() 就是 UTC 毫秒）。
    """
    problems: List[Tuple[str, str, str]] = []
    last_dispatch = hb.get("last_dispatch") or {}
    last_failure = hb.get("last_failure") or {}
    now_ms = time.time() * 1000

    def age_hours(item: Dict) -> Optional[float]:
        ts = item.get("ts_ms")
        if not ts:
            return None
        try:
            return (now_ms - float(ts)) / 3.6e6
        except (TypeError, ValueError):
            return None

    def beijing_time(item: Dict) -> str:
        ts = item.get("ts_ms")
        if not ts:
            return "未知时间"
        try:
            return datetime.fromtimestamp(float(ts) / 1000,
                                          timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            return "未知时间"

    # 1) dispatch 调用本身失败 —— 心跳里带了 HTTP 状态码，能直接定位原因
    fail_age = age_hours(last_failure)
    if fail_age is not None and fail_age <= MAX_HEARTBEAT_AGE_H:
        status = last_failure.get("status") or "网络异常"
        hint = ("401/403 → Cloudflare Secrets.GITHUB_TOKEN 失效或不含 repo 权限；"
                "404 → 工作流文件被改名/删除" if str(status).isdigit() else "")
        problems.append(("🚨", "dispatch_failed",
                         f"Worker 最近一次 dispatch 失败（{beijing_time(last_failure)}，"
                         f"HTTP {status}，{fail_age:.1f} 小时前）{hint}"))

    # 2) 没有任何近期成功记录 → Worker 本身没在跑
    dispatch_age = age_hours(last_dispatch)
    if dispatch_age is None:
        # KV 里还没有任何成功记录：通常是刚部署完、或今天还没到第一个档位（9:15）。
        # 不能报停推 —— 那会把「刚上线」误报成「停摆」，半夜白查一轮控制台。
        # 「Worker 从来没 dispatch 过」这种情况由上面的 silent 分支（按运行次数判定）兜住。
        print("   ⚠️ Worker 心跳里还没有成功的 dispatch 记录"
              "（可能刚部署，或今天还没到 9:15 档），跳过陈旧判定")
    elif dispatch_age > MAX_HEARTBEAT_AGE_H:
        problems.append(("🚨", "heartbeat_stale",
                         f"Worker 最近 {MAX_HEARTBEAT_AGE_H:.1f} 小时内没有成功的 dispatch 记录"
                         f"（最后成功：{beijing_time(last_dispatch)}）→ "
                         f"Worker 未运行/被暂停/被删除，或 Cron 触发器丢失"))
    else:
        # 3) 心跳新鲜但 GitHub 侧一次都没跑 → 问题在 GitHub，不在 Worker。
        # 只在「确实查到了可信的 GitHub 运行记录」时才判，否则会把
        # 「检查器自己查不到」误报成「GitHub 未接单」。
        reliable = [r for r in per_day if not r.get("push_error")]
        if reliable and sum(r.get("push", 0) for r in reliable) == 0:
            problems.append(("🚨", "dispatch_no_run",
                             f"Worker 在 {beijing_time(last_dispatch)} 成功 dispatch，"
                             f"但最近 {len(reliable)} 个交易日 GitHub 侧 0 次运行记录 → "
                             f"GitHub 未接单（Actions 配额耗尽或服务异常），Worker 本身是好的"))

    return problems


# ------------------------------------------------------------
# 文案
# ------------------------------------------------------------
def build_report(now: datetime, per_day: List[Dict],
                 problems: List[Tuple[str, str, str]], api_errors: List[str]) -> Tuple[bool, str]:
    """返回 (healthy, 飞书文本)。healthy=False 时才应推送。

    标题分三档：正常 ✅ / 停推级 🚨 / 检查自身异常 ⚠️。
    第三档很重要 —— 它把「Worker 停了」和「检查器查不到」明确区分开，
    避免半夜收到一条错误的 🚨 然后去翻 Cloudflare 控制台。
    """
    has_critical = any(p[0] == "🚨" for p in problems)
    healthy = not problems
    if healthy:
        head = "✅ 调度器健康检查：正常"
    elif has_critical:
        head = "🚨 调度器健康检查：检测到停推风险"
    else:
        head = "⚠️ 调度器健康检查：本次未能完整判定（检查自身问题，非停推）"
    lines: List[str] = []
    lines.append(head)
    lines.append(f"🕒 检查时间：{now:%Y-%m-%d %H:%M}（北京时间）")
    lines.append(f"📊 最近 {len(per_day)} 个完整交易日的 workflow_dispatch 运行数")
    lines.append(f"   期望：{PUSH_WORKFLOW} {EXPECTED_PUSH_PER_DAY} 次 + "
                 f"{REVIEW_WORKFLOW} {EXPECTED_REVIEW_PER_DAY} 次 / 天")

    for row in per_day:
        bits = [f"   {row['label']:<12}"]
        for key, what in (("push", "盘中"), ("review", "复盘")):
            expect = EXPECTED_PUSH_PER_DAY if key == "push" else EXPECTED_REVIEW_PER_DAY
            if row[f"{key}_error"]:
                icon = "❓API失败"
            elif row[f"{key}_missing"]:
                icon = "❌缺工作流"
            elif row[key] >= expect:
                icon = "✅"
            elif row[key] == 0:
                icon = "❌"
            else:
                icon = "⚠️"
            bits.append(f"{what} {row[key]}次 {icon}")
        bits.append(f"失败 {len(row['push_failed']) + len(row['review_failed'])} 次")
        lines.append("   ".join(bits))

    if problems:
        lines.append("")
        lines.append("异常明细：")
        lines += [f"   {level} {text}" for level, _kind, text in problems]

    if api_errors:
        lines.append("")
        lines.append("API 调用失败明细（这些日期不判定，故上表显示 ❓）：")
        lines += [f"   - {e}" for e in api_errors[:5]]

    if not healthy:
        lines.append("")
        lines.append("🔧 排查路径：")
        kinds = {p[1] for p in problems}
        # 每条诊断一组提示行；先收集再统一编号，避免多分支各自从 1 开始重复编号。
        groups: List[Tuple[str, List[str]]] = []
        if "heartbeat_unreachable" in kinds:
            groups.append(("Worker 心跳端点不可达", [
                "确认 Worker 没被删除，且 GitHub Secret WORKER_HEALTH_URL 填的是 Worker 根 URL。"]))
        if "dispatch_failed" in kinds:
            groups.append(("Cloudflare 控制台 → Workers → macd-strategy-scheduler →", [
                "Settings → Secrets and variables，检查 GITHUB_TOKEN 是否失效或权限不足。",
                "HTTP 404 则是工作流文件被改名/删除，对照 worker.js 的 WORKFLOW_FILE 常量。"]))
        if "dispatch_no_run" in kinds:
            groups.append(("问题在 GitHub 侧，不是 Worker：", [
                "检查本月 Actions 分钟数配额是否耗尽（Settings → Actions → Usage），",
                "或 GitHub 状态页是否有故障。Worker 不需要动。"]))
        if "heartbeat_stale" in kinds:
            groups.append(("Cloudflare 控制台 → Workers → macd-strategy-scheduler，", [
                "确认 Worker 没被暂停/删除，且 Scheduled events 里 */15 的 cron 还在。"]))
        if "silent" in kinds or "missing_workflow" in kinds:
            groups.append(("Cloudflare 控制台 → Workers → macd-strategy-scheduler → Scheduled events，", [
                "看最近是否还在按 */15 触发（Worker 停摆 = 这里没有事件）；",
                "同一页面 Settings → Secrets and variables，确认 GITHUB_TOKEN 有效且含 repo 权限 ——",
                "token 失效时 Worker 调 dispatch 返回 401/403，GitHub 端不产生任何运行记录。"]))
            groups.append(("确认链路正常后要补发当日推送：", [
                f"gh workflow run \"V1.0 MACD多周期共振策略云推送\" --repo {REPO} -f report_mode=scan"]))
        if "partial" in kinds:
            groups.append(("对照 cloudflare-worker/worker.js 的 SCHEDULE 数组与实际触发时间；", [
                "常见原因是 GitHub Actions 配额耗尽导致部分档位触发失败。"]))
        if "failed_run" in kinds:
            groups.append(("打开上面 run id 的日志，看 scripts/v43_push.py 的推送步骤是否报错。", [
                "v43_push.py 已改为推送未被飞书接受时非零退出，所以红点基本等价于推送失败。"]))
        if "api_error" in kinds:
            groups.append(("本工作流已配 permissions: actions: read；持续失败请检查", [
                "GitHub API 限流或 Actions 内置 token 状态。"]))
        for idx, (top, rest) in enumerate(groups, start=1):
            lines.append(f"   {idx}. {top}")
            lines.extend(f"      {s}" for s in rest)

    return healthy, "\n".join(lines)


# ------------------------------------------------------------
# 推送
# ------------------------------------------------------------
def _feishu_result(resp) -> Tuple[bool, str]:
    """校验飞书响应是否真的成功，返回 (是否成功, 失败原因)。

    飞书自定义机器人成功返回 HTTP 200 + 正文 {"StatusCode": 0}（v2）或 {"code": 0}（v1）。
    webhook 被删除/停用时 HTTP 往往仍是 200，只有正文状态码非 0 —— 只看 HTTP 状态码
    会把「告警没送达」误判成「已送达」，于是本脚本以为发出去了、直接 exit 0。
    本脚本是监控本身，这条链断了就等于静默失效，所以必须校验。
    （与 scripts/v43_push.py 的同名函数逻辑一致；此处刻意复制，
    避免本脚本依赖 strategies/ 的重型依赖。）
    """
    if getattr(resp, "status_code", 0) != 200:
        return False, f"HTTP {resp.status_code}: {(getattr(resp, 'text', '') or '')[:120]}"
    try:
        data = resp.json()
    except Exception:
        return True, ""
    if not isinstance(data, dict):
        return True, ""
    code = data.get("StatusCode", data.get("code"))
    if code in (None, 0):
        return True, ""
    return False, f"飞书拒绝 StatusCode={code} msg={data.get('msg', '')}"


def push_feishu(text: str) -> bool:
    """推送纯文本。返回是否真的被飞书接受。未配置 webhook 时打印并返回 False。"""
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        print("⚠️ 未配置 FEISHU_WEBHOOK_URL，告警无法送达（仅打印）")
        return False
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
    except Exception as e:
        print(f"❌ 飞书推送失败: {type(e).__name__} {e}")
        return False
    ok, reason = _feishu_result(resp)
    if ok:
        print(f"✅ 飞书推送 HTTP {resp.status_code}，已确认飞书接受")
    else:
        print(f"❌ 飞书未接受推送: {reason}")
    return ok


def selftest_report() -> str:
    """打印一次模拟告警文案，用于离线核对格式（不发网络请求）。"""
    y = now_bjt().date() - timedelta(days=1)
    d1 = y - timedelta(days=3) if y.weekday() == 0 else y - timedelta(days=2)
    d2 = y - timedelta(days=1) if y.weekday() >= 1 else y - timedelta(days=4)
    per_day = [
        _synth_row(d1, EXPECTED_PUSH_PER_DAY, EXPECTED_REVIEW_PER_DAY),
        _synth_row(d2, 7, EXPECTED_REVIEW_PER_DAY),
        _synth_row(y, 0, 0),
    ]
    problems = [
        ("⚠️", "partial", f"{day_label(d2)} 盘中/盘前推送只触发 7/{EXPECTED_PUSH_PER_DAY} 次 → "
                          f"Worker 部分档位漏触发（检查 SCHEDULE 与交易时段判断）"),
        ("🚨", "silent", f"{day_label(y)} 全天 0 次 盘中/盘前推送调度 → "
                         f"Cloudflare Worker 未运行，或其 Secrets.GITHUB_TOKEN 已失效"),
        ("🚨", "silent", f"{day_label(y)} 全天 0 次 收盘复盘调度 → "
                         f"Cloudflare Worker 未运行，或其 Secrets.GITHUB_TOKEN 已失效"),
    ]
    # 心跳分支：用合成的「陈旧心跳 + 1 小时前的 401 失败」走一遍真实判定逻辑，
    # 这样核对格式时检查的是真实代码路径，而不是手写字符串。
    now_ts = now_bjt().timestamp()
    stale_hb = {
        "kvConfigured": True,
        "last_dispatch": {"ts_ms": (now_ts - 20 * 3600) * 1000,
                          "workflow": PUSH_WORKFLOW, "report_mode": "scan"},
        "last_failure": {"ts_ms": (now_ts - 1 * 3600) * 1000,
                         "workflow": PUSH_WORKFLOW, "status": 401},
    }
    problems.extend(heartbeat_problems(stale_hb, per_day))
    _, text = build_report(now_bjt(), per_day, problems, [])
    return text


def _synth_row(day: date, push: int, review: int) -> Dict:
    """构造一行合成的判定结果（--selftest 专用，结构须与 evaluate() 输出一致）。"""
    return {"label": day_label(day), "push": push, "review": review,
            "push_missing": False, "review_missing": False,
            "push_error": False, "review_error": False,
            "push_failed": [], "review_failed": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="调度器健康检查（检测 Worker / GITHUB_TOKEN 静默失效）")
    parser.add_argument("--days", type=int, default=CHECK_DAYS, help=f"回看交易日数（默认 {CHECK_DAYS}）")
    parser.add_argument("--always-report", action="store_true", help="正常时也推送报告（验证飞书链路）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不推送飞书")
    parser.add_argument("--selftest", action="store_true", help="打印模拟告警文案后退出（不发网络请求）")
    args = parser.parse_args()

    if args.selftest:
        print(selftest_report())
        return 0

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("❌ 缺少 GITHUB_TOKEN（需 actions: read 权限）")
        return 1

    always_report = args.always_report or os.environ.get("ALWAYS_REPORT", "").lower() == "true"
    now = now_bjt()
    print("=" * 56)
    print(f"🛰 调度器健康检查  {now:%Y-%m-%d %H:%M} 北京时间")
    print(f"   仓库 {REPO}，回看 {args.days} 个完整交易日")
    print("=" * 56)

    days = completed_weekdays(args.days, now.date())
    print("   检查日：" + "、".join(day_label(d) for d in days))

    per_day, problems, api_errors = evaluate(token, days)

    # Worker 心跳比对（可选升级项）：未配置 WORKER_HEALTH_URL 时跳过，
    # 不影响上面已经能用的「数运行次数」判定。
    hb_url = os.environ.get("WORKER_HEALTH_URL", "").strip()
    if hb_url:
        hb = fetch_worker_heartbeat(hb_url)
        if hb is None:
            problems.append(("🚨", "heartbeat_unreachable",
                             f"Worker 心跳端点 {hb_url.rstrip('/')}/health 不可达 → "
                             f"Worker 已下线/被删除，或 WORKER_HEALTH_URL 配置错误"))
        else:
            kv = "已配置" if hb.get("kvConfigured") else "未配置 KV 绑定"
            print(f"   心跳：Worker 在线（KV {kv}），最后成功 dispatch="
                  f"{(hb.get('last_dispatch') or {}).get('ts_ms') or '无'}")
            problems.extend(heartbeat_problems(hb, per_day))
    else:
        print("   ⚠️ 未配置 WORKER_HEALTH_URL，跳过 Worker 心跳比对"
              "（仍按 workflow_dispatch 次数判定，无法区分 Worker 停摆与 GitHub 未接单）")

    healthy, text = build_report(now, per_day, problems, api_errors)
    print(text)

    should_send = (not healthy) or always_report
    if not should_send:
        print("\n✅ 无异常，按约定保持静默（不推送飞书）")
        return 0

    if args.dry_run:
        print("\n🔧 --dry-run：不实际推送")
        return 0 if healthy else 1

    ok = push_feishu(text)
    if not ok:
        print("❌ 告警未送达飞书（webhook 失效或网络失败）")
    # 返回非零让 GitHub Actions 也变红 —— 双通道兜底：
    # 1) 检测到异常 → 红点提醒去翻飞书告警；
    # 2) 飞书本身挂了 → 红点提醒去修 webhook。否则监控会静默失效。
    return 0 if (healthy and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
