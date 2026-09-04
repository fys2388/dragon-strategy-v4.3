// Cloudflare Worker - 东方财富API代理
// 解决GitHub Actions IP被东财限制的问题
// 路由：
//   /proxy/sector  - 行业板块列表
//   /proxy/moneyflow?code=600388 - 个股资金流
//   /proxy/fundamental?code=600388 - 个股基本面
//   /proxy/news?code=600388 - 个股公告

const EASTMONEY_BASE = "https://push2.eastmoney.com";
const EASTMONEY_ANNOUNCEMENT = "https://np-anotice-stock.eastmoney.com";

const HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  "Referer": "https://quote.eastmoney.com/",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    try {
      let targetUrl = null;

      if (path === "/proxy/sector") {
        // 行业板块列表
        const params = new URLSearchParams({
          pn: "1", pz: "100", po: "1", np: "1", fltt: "2", invt: "2",
          fid: "f3", fs: "m:90+t:2",
          fields: "f12,f14,f2,f3,f4,f5,f6,f7,f8,f15,f16,f17,f18,f20,f21,f62,f128,f136,f140",
        });
        targetUrl = `${EASTMONEY_BASE}/api/qt/clist/get?${params.toString()}`;
      }
      else if (path === "/proxy/moneyflow") {
        // 个股资金流
        const code = url.searchParams.get("code") || "";
        const days = url.searchParams.get("days") || "10";
        if (!code) return error("缺少code参数");
        const market = code.startsWith("6") ? "1" : "0";
        const params = new URLSearchParams({
          secid: `${market}.${code}`,
          fields1: "f1,f2,f3,f7",
          fields2: "f51,f52,f53,f54,f55,f56,f57",
          klt: "101",
          lmt: days,
        });
        targetUrl = `${EASTMONEY_BASE}/api/qt/stock/fflow/kline/get?${params.toString()}`;
      }
      else if (path === "/proxy/fundamental") {
        // 个股基本面
        const code = url.searchParams.get("code") || "";
        if (!code) return error("缺少code参数");
        const market = code.startsWith("6") ? "1" : "0";
        const params = new URLSearchParams({
          secid: `${market}.${code}`,
          fields: "f55,f57,f58,f116,f117,f162,f167,f173,f187,f188,f190,f191,f192",
        });
        targetUrl = `${EASTMONEY_BASE}/api/qt/stock/get?${params.toString()}`;
      }
      else if (path === "/proxy/news") {
        // 个股公告
        const code = url.searchParams.get("code") || "";
        if (!code) return error("缺少code参数");
        const params = new URLSearchParams({
          sr: "-1", page_size: "20", page_index: "1",
          ann_type: "A", client_source: "web",
          stock_list: code,
        });
        targetUrl = `${EASTMONEY_ANNOUNCEMENT}/api/security/ann?${params.toString()}`;
      }
      else {
        return error("不支持的路径", 404);
      }

      // 转发请求
      const resp = await fetch(targetUrl, {
        method: "GET",
        headers: HEADERS,
        cf: {
          cacheTtl: 30,  // 缓存30秒
          cacheEverything: true,
        },
      });

      const data = await resp.text();

      return new Response(data, {
        status: resp.status,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control": "public, max-age=30",
        },
      });
    } catch (e) {
      return error(`代理请求失败: ${e.message}`);
    }
  },
};

function error(msg, status = 400) {
  return new Response(JSON.stringify({ error: msg }), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
