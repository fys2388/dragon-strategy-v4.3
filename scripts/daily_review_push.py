# -*- coding: utf-8 -*-
"""收盘复盘推送脚本（重写，适配 MACD 多周期共振策略 V1.0）。

每天 18:00 运行，报告内容：
- 大盘概况（7 分制评分 + 主要指数）
- 今日策略扫描统计（扫描次数 / 共振推荐）
- 推荐表现（今日推荐 vs 最新价）
- 持仓盈亏与离场信号
- 近 7 日策略表现（读 strategy_history.jsonl + 实时行情）

用法：
    python scripts/daily_review_push.py            # 正常推送
    python scripts/daily_review_push.py --no-send  # 仅打印不推送
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 emoji 报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _re = getattr(_stream, "reconfigure", None)
        if _re:
            _re(encoding="utf-8", errors="replace")
    except Exception:
        pass

from strategies.macd_resonance import data_source as ds  # noqa: E402
from strategies.macd_resonance.market_gate import get_market_score  # noqa: E402
from strategies.macd_resonance.portfolio_manager import PortfolioManager  # noqa: E402
from strategies.macd_resonance.trading_calendar import now_bjt  # noqa: E402
from utils.config_loader import load_feishu_config  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "strategy_history.jsonl")


def load_today_records() -> list:
    """读取今日策略扫描记录。"""
    if not os.path.exists(HISTORY_FILE):
        return []
    today = now_bjt().strftime("%Y-%m-%d")
    records = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ts", "").startswith(today):
                records.append(rec)
    return records


def get_webhook() -> str:
    """优先环境变量，其次 feishu_config.json（含 ${} 占位符解析）。"""
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        return webhook
    try:
        cfg = load_feishu_config()
        return cfg["webhook_url"]
    except Exception:
        return ""


def send_to_feishu(message: str) -> bool:
    webhook = get_webhook()
    if not webhook:
        print("❌ 未配置 FEISHU_WEBHOOK_URL，跳过推送")
        return False
    import requests
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": message}}, timeout=10)
        print(f"✅ 复盘推送完成，HTTP {resp.status_code}")
        return True
    except Exception as e:
        print(f"❌ 复盘推送失败: {e}")
        return False


def _load_dashboard_7d() -> str:
    """近7日策略表现摘要（复用 generate_dashboard_data 的统计逻辑）。"""
    try:
        mod_path = os.path.join(BASE_DIR, "scripts", "generate_dashboard_data.py")
        spec = importlib.util.spec_from_file_location("generate_dashboard_data", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        now = now_bjt()
        records = mod.load_history()
        entries = mod.entries_in_window(records, 7, now)
        codes = sorted({str(e["code"]) for e in entries if e.get("code")})
        quotes = ds.get_realtime_quotes(codes) if codes else {}
        d = mod.build_dashboard(7, now, quotes)
        return mod.fmt_summary(d)
    except Exception as e:
        return f"⚠️ 看板统计失败: {e}"


def build_review_report() -> str:
    now = now_bjt()
    lines = [f"📋 MACD多周期共振策略 收盘复盘 {now.strftime('%Y-%m-%d')}"]
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 大盘评分只算一次，全报告复用
    try:
        score, desc, can_open = get_market_score()
        market_score, market_desc, market_can_open = score, desc, can_open
    except Exception as e:
        market_score, market_desc, market_can_open = 0.0, f"⚠️ 大盘评分获取失败: {e}", False

    # 1. 大盘概况
    lines.append("【大盘概况】")
    lines.append(f"大盘评分：{market_score:.1f}/7分 | {'🟢可开仓' if market_can_open else '🔴观望'}")
    if market_desc.startswith("⚠️"):
        lines.append("  " + market_desc)
    else:
        lines.append("  " + " / ".join(l.strip("✓✗ ") for l in market_desc.split("\n")[:4]))

    indices = ds.get_market_indices()
    if indices:
        for code, data in indices.items():
            pct = float(data.get("change_pct", 0) or 0)
            lines.append(f"  {'🟢' if pct > 0 else '🔴'} {data.get('name', code)}: {pct:+.2f}%")
    else:
        lines.append("  ⚠️ 指数行情获取失败")
    lines.append("")

    # 2. 今日策略扫描
    records = load_today_records()
    lines.append("【今日策略扫描】")
    if not records:
        lines.append("  今日暂无扫描记录（可能非交易时段或扫描未运行）")
    else:
        entries_today = []
        seen = set()
        for rec in records:
            for e in rec.get("entries", []):
                code = str(e.get("code", ""))
                if code and code in seen:
                    continue
                if code:
                    seen.add(code)
                entries_today.append(e)
        scans = len(records)
        lines.append(f"  扫描{scans}次 | 今日推荐标的{len(entries_today)}只（信号{sum(len(r.get('entries', [])) for r in records)}次）")
        if entries_today:
            for e in entries_today[:5]:
                lines.append(f"  • {e.get('name')}({e.get('code')}) @ {e.get('price')}元 得分{e.get('score')}")
    lines.append("")

    # 3. 推荐表现（今日推荐 vs 最新价）
    lines.append("【今日推荐表现】")
    records = load_today_records()
    entries = []
    seen = set()
    for rec in records:
        for e in rec.get("entries", []):
            code = str(e.get("code", ""))
            if code and code in seen:
                continue
            if code:
                seen.add(code)
            entries.append(e)
    if not entries:
        lines.append("  今日无推荐标的")
    else:
        codes = sorted({str(e["code"]) for e in entries if e.get("code")})
        quotes = ds.get_realtime_quotes(codes) if codes else {}
        for e in entries[:8]:
            code = str(e.get("code", ""))
            entry_price = float(e.get("price") or 0)
            latest = float(quotes.get(code, {}).get("price") or 0)
            if entry_price > 0 and latest > 0:
                ret = (latest - entry_price) / entry_price * 100
                icon = "🟢" if ret >= 0 else "🔴"
                lines.append(f"  {icon} {e.get('name')}({code}) 推荐{e.get('price')} → 现价{latest:.2f} ({ret:+.1f}%)")
            else:
                lines.append(f"  ⚪ {e.get('name')}({code}) 最新价获取失败")
    lines.append("")

    # 4. 持仓盈亏
    lines.append("【持仓盈亏】")
    try:
        pm = PortfolioManager()
        positions = pm.load_positions()
        if not positions:
            lines.append("  当前无持仓")
        else:
            codes = [str(p.get("code", "")) for p in positions]
            quotes = ds.get_realtime_quotes(codes) if codes else {}
            for pos in positions:
                code = str(pos.get("code", ""))
                entry = float(pos.get("entry_price") or 0)
                latest = float(quotes.get(code, {}).get("price") or 0)
                qty = int(pos.get("quantity") or 0)
                if entry > 0 and latest > 0:
                    ret = (latest - entry) / entry * 100
                    pnl = (latest - entry) * qty
                    icon = "🟢" if ret >= 0 else "🔴"
                    lines.append(f"  {icon} {pos.get('name', code)}({code}) 成本{entry:.2f} 现价{latest:.2f} "
                                 f"盈亏{ret:+.1f}%（{pnl:+.0f}元）")
                else:
                    lines.append(f"  ⚪ {pos.get('name', code)}({code}) 最新价获取失败")
            exits = pm.check_exit_signals(positions, quotes)
            if exits:
                lines.append("  ⚠️ 离场信号：")
                for s in exits:
                    lines.append(f"    - {s.name}({s.code}) {s.signal_type}: {s.reason} → {s.suggestion}")
    except Exception as e:
        lines.append(f"  ⚠️ 持仓读取失败: {e}")
    lines.append("")

    # 5. 近7日策略表现
    lines.append("【近7日策略表现】")
    lines.append(_load_dashboard_7d())
    lines.append("")

    # 6. 操作建议
    lines.append("【操作建议】")
    if market_score >= 4:
        lines.append("  ✅ 大盘评分达标，可按 30% 单票仓位、最多3只参与")
    else:
        lines.append("  ⚠️ 大盘评分不足，明日以观望为主，仅处理持仓离场信号")
    lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⏰ 生成时间：{now.strftime('%H:%M')}")
    lines.append("⚠️ 仅为策略信号复盘，不构成投资建议")
    return "\n".join(lines)


def main():
    no_send = "--no-send" in sys.argv
    report = build_review_report()
    print(report)
    print()
    if not no_send:
        send_to_feishu(report)


if __name__ == "__main__":
    main()
