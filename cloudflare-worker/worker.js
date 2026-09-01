// Cloudflare Worker - MACD策略定时推送调度器
// 功能：在交易时段准时调用 GitHub Actions workflow_dispatch，替代不可靠的 GitHub cron
// 部署：Cloudflare Dashboard → Workers & Pages → Create → 粘贴此代码 → 配置环境变量和 Cron Triggers
//
// 环境变量（Worker Settings → Variables）：
//   GITHUB_TOKEN = 你的 GitHub Personal Access Token（需要 repo 权限）
//
// Cron Triggers（Worker Settings → Triggers → Cron Triggers，UTC 时间）：
//   15 1 * * 1-5    → 北京时间 9:15  盘前报告
//   0,30 2-3 * * 1-5 → 北京时间 10:00/10:30/11:00/11:30 上午盘中
//   0,30 5-6 * * 1-5 → 北京时间 13:00/13:30/14:00/14:30 下午盘中
//   50 6 * * 1-5    → 北京时间 14:50 尾盘完整版
//   30 7 * * 1-5    → 北京时间 15:30 收盘复盘

const GITHUB_REPO = "fys2388/dragon-strategy-v4.3";
const WORKFLOW_FILE = "strategy_cloud_deploy.yml";
const REVIEW_WORKFLOW_FILE = "evening_review.yml";

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

  console.log(`[调度触发] 北京时间=${beijingTime.toISOString()} weekday=${weekday}`);

  // 周末不触发（cron 已经限制了 1-5，双保险）
  if (weekday === 0 || weekday === 6) {
    console.log("[跳过] 周末");
    return;
  }

  // 15:30 → 收盘复盘
  if (hour === 15 && minute === 30) {
    await triggerWorkflow(env, REVIEW_WORKFLOW_FILE, "");
    return;
  }

  // 9:15 → 盘前报告
  const reportMode = (hour === 9 && minute === 15) ? "premarket" : "scan";
  await triggerWorkflow(env, WORKFLOW_FILE, reportMode);
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
