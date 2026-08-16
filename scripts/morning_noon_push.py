# -*- coding: utf-8 -*-
"""盘前 + 午盘推送脚本（重写，适配 MACD 多周期共振策略 V1.0）。

- 盘前 09:15：大盘评分 + 昨日推荐回顾 + 持仓提醒
- 午盘 11:35：大盘评分 + 今日上午推荐 + 持仓提醒

用法：
    python scripts/morning_noon_push.py            # 按当前时间自动选择
    python scripts/morning_noon_push.py --mode premarket
    python scripts/morning_noon_push.py --mode noon
    python scripts/morning_noon_push.py --no-send
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_resonance import data_source as ds  # noqa: E402
from strategies.macd_resonance.market_gate import get_market_score  # noqa: E402
from strategies.macd_resonance.portfolio_manager import PortfolioManager  # noqa: E402
from utils.config_loader import load_feishu_config  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "strategy_history.jsonl")


def load_history() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    records = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def records_on(date: datetime) -> list:
    day = date.strftime("%Y-%m-%d")
    return [r for r in load_history() if r.get("ts", "").startswith(day)]


def get_webhook() -> str:
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        return webhook
    try:
        return load_feishu_config()["webhook_url"]
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
        print(f"✅ 推送完成，HTTP {resp.status_code}")
        return True
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        return False


def _market_section() -> list:
    lines = ["【大盘概况】"]
    try:
        score, desc, can_open = get_market_score()
        lines.append(f"大盘评分：{score:.1f}/7分 | {'🟢可开仓' if can_open else '🔴观望'}")
        lines.append("  " + " / ".join(l.strip("✓✗ ") for l in desc.split("\n")[:4]))
    except Exception as e:
        lines.append(f"⚠️ 大盘评分获取失败: {e}")
    indices = ds.get_market_indices()
    if indices:
        for code, data in indices.items():
            pct = float(data.get("change_pct", 0) or 0)
            lines.append(f"  {'🟢' if pct > 0 else '🔴'} {data.get('name', code)}: {pct:+.2f}%")
    else:
        lines.append("  ⚠️ 指数行情获取失败")
    return lines


def _portfolio_section() -> list:
    lines = ["【持仓提醒】"]
    try:
        pm = PortfolioManager()
        positions = pm.load_positions()
        if not positions:
            lines.append("  当前无持仓")
            return lines
        codes = [str(p.get("code", "")) for p in positions]
        quotes = ds.get_realtime_quotes(codes) if codes else {}
        for pos in positions:
            code = str(pos.get("code", ""))
            entry = float(pos.get("entry_price") or 0)
            latest = float(quotes.get(code, {}).get("price") or 0)
            if entry > 0 and latest > 0:
                ret = (latest - entry) / entry * 100
                icon = "🟢" if ret >= 0 else "🔴"
                lines.append(f"  {icon} {pos.get('name', code)}({code}) 成本{entry:.2f} 现价{latest:.2f} ({ret:+.1f}%)")
            else:
                lines.append(f"  ⚪ {pos.get('name', code)}({code}) 最新价获取失败")
        exits = pm.check_exit_signals(positions, quotes)
        if exits:
            lines.append("  ⚠️ 触发离场信号：")
            for s in exits:
                lines.append(f"    - {s.name}({s.code}) {s.signal_type}: {s.reason} → {s.suggestion}")
    except Exception as e:
        lines.append(f"  ⚠️ 持仓读取失败: {e}")
    return lines


def _entries_section(records: list, limit: int = 6) -> list:
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
        return ["  暂无推荐标的"]
    lines = []
    codes = sorted({str(e["code"]) for e in entries if e.get("code")})
    quotes = ds.get_realtime_quotes(codes) if codes else {}
    for e in entries[:limit]:
        code = str(e.get("code", ""))
        entry_price = float(e.get("price") or 0)
        latest = float(quotes.get(code, {}).get("price") or 0)
        if entry_price > 0 and latest > 0:
            ret = (latest - entry_price) / entry_price * 100
            icon = "🟢" if ret >= 0 else "🔴"
            lines.append(f"  {icon} {e.get('name')}({code}) 推荐{e.get('price')} → 现价{latest:.2f} ({ret:+.1f}%)")
        else:
            lines.append(f"  ⚪ {e.get('name')}({code}) @ {e.get('price')}元")
    return lines


def build_premarket_report() -> str:
    now = datetime.now()
    lines = [f"🌅 盘前报告 {now.strftime('%Y-%m-%d')} MACD多周期共振V1.0"]
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines += _market_section()
    lines.append("")
    lines.append("【昨日推荐回顾】")
    yesterday_records = records_on(now - timedelta(days=1))
    if not yesterday_records:
        lines.append("  昨日无推荐记录（非交易日或扫描未运行）")
    else:
        lines += _entries_section(yesterday_records)
    lines.append("")
    lines += _portfolio_section()
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⏰ 开盘前参考，9:30 后策略盘中每5分钟自动扫描")
    lines.append("⚠️ 仅为策略信号，不构成投资建议")
    return "\n".join(lines)


def build_noon_report() -> str:
    now = datetime.now()
    lines = [f"☀️ 午间点评 {now.strftime('%Y-%m-%d')} MACD多周期共振V1.0"]
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines += _market_section()
    lines.append("")
    lines.append("【今日上午推荐】")
    today_records = records_on(now)
    if not today_records:
        lines.append("  今日暂无推荐（可能无共振信号或大盘观望）")
    else:
        lines += _entries_section(today_records)
    lines.append("")
    lines += _portfolio_section()
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⏰ 尾盘 14:50 自动推送完整版，敬请关注")
    lines.append("⚠️ 仅为策略信号，不构成投资建议")
    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if a.startswith("--")]
    no_send = "--no-send" in args
    mode_arg = None
    if "--mode" in args:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode_arg = sys.argv[idx + 1]

    if mode_arg:
        mode = mode_arg
    else:
        hour = datetime.now().hour
        mode = "premarket" if hour < 11 else "noon"

    report = build_premarket_report() if mode == "premarket" else build_noon_report()
    print(report)
    print()
    if not no_send:
        send_to_feishu(report)


if __name__ == "__main__":
    main()
