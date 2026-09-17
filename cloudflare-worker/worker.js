// Cloudflare Worker - MACD策略定时推送调度器
// 功能：在交易时段准时调用 GitHub Actions workflow_dispatch
// 调度逻辑内置：每15分钟触发一次，Worker内部判断是否执行
// 彻底解决Cron触发器配置丢失问题
//
// 环境变量（Worker Settings → Variables）：
//   GITHUB_TOKEN = 你的 GitHub Personal Access Token（需要 repo 权限）
//
// KV 绑定（Worker Settings → Storage → KV namespaces，可选但强烈建议）：
//   HEARTBEAT = 心跳 namespace，用于让 GitHub Actions 侧的调度器健康检查能区分
//   「Worker 没跑」和「Worker 跑了但 GitHub 没接单」两种都表现为 runs==0 的故障。
//   未配置时 Worker 照常推送，只是 /health 返回的空心跳无法参与比对。
//
// Cron Triggers（只需配置一个，UTC 时间）：
//   */15 * * * MON,TUE,WED,THU,FRI  → 每15分钟触发，Worker内部判断交易时段
//
// 诊断端点（浏览器或 Actions 健康检查访问）：
//   GET https://<worker-url>/health  → 最近一次成功/失败的 dispatch 记录

const GITHUB_REPO = "fys2388/dragon-strategy-v4.3";
const WORKFLOW_FILE = "strategy_cloud_deploy.yml";
const REVIEW_WORKFLOW_FILE = "evening_review.yml";

// 交易时段调度表（北京时间）
const SCHEDULE = [
  { hour: 9, minute: 15, mode: "premarket", label: "盘前报告" },
  { hour: 10, minute: 0, mode: "scan", label: "上午盘中" },
  { hour: 10, minute: 30, mode: "scan", label: "上午盘中" },
  { hour: 11, minute: 0, mode: "scan", label: "上午盘中" },
  { hour: 11, minute: 30, mode: "scan", label: "上午盘中" },
  { hour: 13, minute: 0, mode: "scan", label: "下午盘中" },
  { hour: 13, minute: 30, mode: "scan", label: "下午盘中" },
  { hour: 14, minute: 0, mode: "scan", label: "下午盘中" },
  { hour: 14, minute: 30, mode: "scan", label: "下午盘中" },
  { hour: 14, minute: 45, mode: "scan", label: "尾盘扫描" },
  { hour: 15, minute: 30, mode: "review", label: "收盘复盘" },
];

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleTrigger(event, env));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // 东财API代理路由（解决GitHub Actions IP被限制问题）
    if (path.startsWith("/proxy/")) {
      return await proxyEastmoney(url);
    }

    // 心跳端点：GitHub Actions 的 scheduler_health_check 每天比对这里，
    // 用它区分 Worker 停摆 / GitHub 未接单 / dispatch 调用失败三种故障。
    if (path === "/health") {
      return await healthEndpoint(env);
    }

    // 手动测试入口：浏览器访问 Worker URL 即可触发一次 scan
    const mode = url.searchParams.get("mode") || "scan";
    const result = await triggerWorkflow(env, WORKFLOW_FILE, mode);
    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" },
    });
  },
};

// 东财API代理
async function proxyEastmoney(url) {
  const path = url.pathname;
  const EASTMONEY_BASE = "https://push2.eastmoney.com";
  const EASTMONEY_ANNOUNCEMENT = "https://np-anotice-stock.eastmoney.com";
  const HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
  };

  try {
    let targetUrl = null;

    if (path === "/proxy/sector") {
      const params = new URLSearchParams({
        pn: "1", pz: "100", po: "1", np: "1", fltt: "2", invt: "2",
        fid: "f3", fs: "m:90+t:2",
        fields: "f12,f14,f2,f3,f4,f5,f6,f7,f8,f15,f16,f17,f18,f20,f21,f62,f128,f136,f140",
      });
      targetUrl = `${EASTMONEY_BASE}/api/qt/clist/get?${params.toString()}`;
    }
    else if (path === "/proxy/moneyflow") {
      const code = url.searchParams.get("code") || "";
      const days = url.searchParams.get("days") || "10";
      if (!code) return new Response(JSON.stringify({error: "缺少code"}), {status: 400});
      const market = code.startsWith("6") ? "1" : "0";
      const params = new URLSearchParams({
        secid: `${market}.${code}`,
        fields1: "f1,f2,f3,f7", fields2: "f51,f52,f53,f54,f55,f56,f57",
        klt: "101", lmt: days,
      });
      targetUrl = `${EASTMONEY_BASE}/api/qt/stock/fflow/kline/get?${params.toString()}`;
    }
    else if (path === "/proxy/fundamental") {
      const code = url.searchParams.get("code") || "";
      if (!code) return new Response(JSON.stringify({error: "缺少code"}), {status: 400});
      const market = code.startsWith("6") ? "1" : "0";
      const params = new URLSearchParams({
        secid: `${market}.${code}`,
        fields: "f55,f57,f58,f116,f117,f162,f167,f173,f187,f188,f190,f191,f192",
      });
      targetUrl = `${EASTMONEY_BASE}/api/qt/stock/get?${params.toString()}`;
    }
    else if (path === "/proxy/news") {
      const code = url.searchParams.get("code") || "";
      if (!code) return new Response(JSON.stringify({error: "缺少code"}), {status: 400});
      const params = new URLSearchParams({
        sr: "-1", page_size: "20", page_index: "1",
        ann_type: "A", client_source: "web", stock_list: code,
      });
      targetUrl = `${EASTMONEY_ANNOUNCEMENT}/api/security/ann?${params.toString()}`;
    }
    else {
      return new Response(JSON.stringify({error: "不支持的路径"}), {status: 404});
    }

    const resp = await fetch(targetUrl, {
      method: "GET",
      headers: HEADERS,
      cf: { cacheTtl: 30, cacheEverything: true },
    });
    const data = await resp.text();
    return new Response(data, {
      status: resp.status,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=30" },
    });
  } catch (e) {
    return new Response(JSON.stringify({error: `代理失败: ${e.message}`}), {status: 500});
  }
}

async function handleTrigger(event, env) {
  // event.scheduledTime 可能是 Date 对象或数字时间戳，统一转成毫秒
  const scheduledMs = event.scheduledTime instanceof Date
    ? event.scheduledTime.getTime()
    : Number(event.scheduledTime);
  const beijingTime = new Date(scheduledMs + 8 * 60 * 60 * 1000);
  const hour = beijingTime.getHours();
  const minute = beijingTime.getMinutes();
  const weekday = beijingTime.getDay(); // 0=周日, 6=周六

  console.log(`[调度触发] 北京时间=${beijingTime.toISOString().slice(0, 19)} weekday=${weekday}`);

  // 周末不触发
  if (weekday === 0 || weekday === 6) {
    console.log("[跳过] 周末");
    return;
  }

  // 查找匹配的调度项（允许±2分钟误差，因为Cron每15分钟触发）
  const matched = SCHEDULE.find(s => {
    const diff = Math.abs((s.hour * 60 + s.minute) - (hour * 60 + minute));
    return diff <= 2;
  });

  if (!matched) {
    console.log(`[跳过] 非调度时间 ${hour}:${String(minute).padStart(2, '0')}`);
    return;
  }

  console.log(`[执行] ${matched.label} (${matched.hour}:${String(matched.minute).padStart(2, '0')}) mode=${matched.mode}`);

  if (matched.mode === "review") {
    await triggerWorkflow(env, REVIEW_WORKFLOW_FILE, "");
  } else {
    await triggerWorkflow(env, WORKFLOW_FILE, matched.mode);
  }
}

async function triggerWorkflow(env, workflowFile, reportMode) {
  const url = `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${workflowFile}/dispatches`;

  const body = { ref: "main" };
  if (reportMode) {
    body.inputs = { report_mode: reportMode };
  }

  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `token ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "macd-strategy-scheduler",
      },
      body: JSON.stringify(body),
    });

    if (resp.status === 204) {
      console.log(`[成功] 已触发 ${workflowFile} (report_mode=${reportMode || "N/A"})`);
      await recordHeartbeat(env, "last_dispatch", {
        ts_ms: Date.now(),
        workflow: workflowFile,
        report_mode: reportMode || null,
        ok: true,
      });
      return { success: true, status: 204 };
    } else {
      const text = await resp.text();
      console.error(`[失败] HTTP ${resp.status}: ${text}`);
      await recordHeartbeat(env, "last_failure", {
        ts_ms: Date.now(),
        workflow: workflowFile,
        report_mode: reportMode || null,
        ok: false,
        status: resp.status,
        error: text.slice(0, 200),
      });
      return { success: false, status: resp.status, error: text };
    }
  } catch (e) {
    console.error(`[异常] ${e.message}`);
    await recordHeartbeat(env, "last_failure", {
      ts_ms: Date.now(),
      workflow: workflowFile,
      report_mode: reportMode || null,
      ok: false,
      status: null,
      error: String(e.message).slice(0, 200),
    });
    return { success: false, error: e.message };
  }
}

// 写心跳到 KV。只观测、不参与主流程：写失败仅记日志，
// 绝不让「KV 写不进」导致当天交易推送丢失。
async function recordHeartbeat(env, key, value) {
  const heartbeat = env.HEARTBEAT;
  if (!heartbeat) {
    // 静默跳过：每个档位都会调到这里，不打日志避免刷屏。
    // 「KV 未配置」这个状态由 GET /health 的 kvConfigured=false 暴露。
    return;
  }
  try {
    await heartbeat.put(key, JSON.stringify(value));
  } catch (e) {
    console.warn(`[心跳] 写入失败（忽略）: ${e.message}`);
  }
}

// GET /health —— 返回心跳，供 scheduler_health_check.py 比对。
// KV 未配置时返回 kvConfigured=false + 空记录，端点本身仍正常响应，
// 这样「还没升级 KV」和「Worker 挂了」能被区分开。
async function healthEndpoint(env) {
  const heartbeat = env.HEARTBEAT;
  const readKey = async (key) => {
    if (!heartbeat) return null;
    try {
      const raw = await heartbeat.get(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      console.warn(`[心跳] 读取 ${key} 失败: ${e.message}`);
      return null;
    }
  };
  const [lastDispatch, lastFailure] = await Promise.all([
    readKey("last_dispatch"),
    readKey("last_failure"),
  ]);
  const body = {
    ok: true,
    repo: GITHUB_REPO,
    checkedAtUtc: new Date().toISOString(),
    kvConfigured: Boolean(heartbeat),
    last_dispatch: lastDispatch,
    last_failure: lastFailure,
  };
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
