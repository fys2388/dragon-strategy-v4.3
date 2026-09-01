// Cloudflare Worker - MACD策略定时推送调度器
// 功能：在交易时段准时调用 GitHub Actions workflow_dispatch
// 调度逻辑内置：每15分钟触发一次，Worker内部判断是否执行
// 彻底解决Cron触发器配置丢失问题
//
// 环境变量（Worker Settings → Variables）：
//   GITHUB_TOKEN = 你的 GitHub Personal Access Token（需要 repo 权限）
//
// Cron Triggers（只需配置一个，UTC 时间）：
//   */15 * * * MON,TUE,WED,THU,FRI  → 每15分钟触发，Worker内部判断交易时段

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
    // 手动测试入口：浏览器访问 Worker URL 即可触发一次 scan
    const url = new URL(request.url);
    const mode = url.searchParams.get("mode") || "scan";
    const result = await triggerWorkflow(env, WORKFLOW_FILE, mode);
    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" },
    });
  },
};

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
      return { success: true, status: 204 };
    } else {
      const text = await resp.text();
      console.error(`[失败] HTTP ${resp.status}: ${text}`);
      return { success: false, status: resp.status, error: text };
    }
  } catch (e) {
    console.error(`[异常] ${e.message}`);
    return { success: false, error: e.message };
  }
}
