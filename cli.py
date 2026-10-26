"""
alpha-pick 命令行入口

用法：
  python cli.py scan          # 盘前选股 + 推送
  python cli.py alert         # 盘中预警
  python cli.py review        # 盘后复盘
  python cli.py backtest      # 回测信号
  python cli.py positions     # 查看持仓
  python cli.py add <code>    # 添加持仓
  python cli.py remove <code> # 移除持仓
  python cli.py clear-cache   # 清空缓存
  python cli.py status        # 系统状态
"""

import sys
import json
import logging
import argparse
from datetime import datetime

# Windows 下强制 UTF-8 输出，避免 GBK 编码错误
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 确保项目根目录在 path 中
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import (
    DATA_DIR, CACHE_DIR, REPORT_DIR, USER_PROFILE, FEISHU, TEST_MODE
)
from src.pool.universe import universe
from src.signals.entry import signal_detector
from src.risk.market_gate import market_gate
from src.risk.position import position_manager
from src.risk.performance_tracker import get_tracker
from src.backtest.engine import backtest_engine
from src.monitor.scanner import scanner
from src.notify.feishu import feishu
from src.data.cache import cache as data_cache

# ─── 日志配置 ──────────────────────────────────────
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / f"alpha_pick_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("cli")


# ─── 命令实现 ──────────────────────────────────────

def cmd_scan(args):
    """盘前选股"""
    push = not args.no_push
    result = scanner.run_premarket(push=push)

    # 打印摘要
    print("\n" + "=" * 60)
    print(f"📊 {result['date']} 选股结果")
    print("=" * 60)

    if result.get("market_gate"):
        print(f"\n🏛️ 大盘环境：{result['market_gate']['summary']}")

    signals = result.get("signals", [])
    if not signals:
        print(f"\n{result.get('summary', '无推荐')}")
    else:
        print(f"\n推荐 {len(signals)} 只：")
        print("-" * 60)
        for i, sig in enumerate(signals):
            strength = sig.get("signal_strength", "strong")
            strength_label = {"strong": "✅ 强信号", "weak": "⚡ 弱信号", "watch": "👀 观察"}.get(strength, "")
            print(f"\n{'='*40}")
            print(f" {i+1}. {sig['name']} ({sig['code']}) {strength_label}")
            print(f"    买点：{sig['signal_desc']}")
            print(f"    入场：{sig['entry_price']:.2f}元")
            print(f"    止损：{sig.get('stop_loss', 0):.2f}元 ({sig.get('stop_loss_pct', -7):.1f}%)")
            print(f"    目标1：{sig.get('target_1', 0):.2f}元 (+{sig.get('target_1_pct', 15):.0f}%)")
            print(f"    目标2：{sig.get('target_2', 0):.2f}元 (+{sig.get('target_2_pct', 25):.0f}%)")
            print(f"    评分：{sig.get('score', 0):.0f}")
            print(f"    理由：{sig['reason']}")
            # 仓位建议
            pos = sig.get("position_plan", {})
            if pos:
                print(f"    仓位：{pos['buy_shares']}股 ≈ {pos['total_amount']:,.0f}元 ({pos['position_pct']:.1f}%)")
                print(f"    分批：试探{pos['batch_plan']['batch_1']['shares']}股 → 加仓{pos['batch_plan']['batch_2']['shares']}股 → 机动{pos['batch_plan']['batch_3']['shares']}股")

    if push and signals:
        print(f"\n✅ 已推送飞书")
    elif not push:
        print(f"\nℹ️ 未推送（--no-push）")

    return result


def cmd_alert(args):
    """盘中预警"""
    push = not args.no_push
    alerts = scanner.run_intraday_alerts(push=push)

    if not alerts:
        print("✅ 无异动预警")
    else:
        print(f"\n🚨 {len(alerts)} 条预警：")
        for a in alerts:
            print(f"  🔔 {a['name']} ({a['code']}): {a['alert_type']}")
            print(f"     {a['detail']}")
            if a.get('pnl_pct'):
                print(f"     持仓盈亏：{a['pnl_pct']:+.2f}%")

    return alerts


def cmd_review(args):
    """盘后复盘"""
    push = not args.no_push
    result = scanner.run_review(push=push)

    print("\n" + "=" * 60)
    print(f"📋 {result['date']} 盘后复盘")
    print("=" * 60)

    portfolio = result.get("portfolio", {})
    print(f"\n💼 持仓：{portfolio.get('total_positions', 0)} 只")
    print(f"💰 总成本：{portfolio.get('total_cost', 0):,.0f}元")
    print(f"📈 总市值：{portfolio.get('total_value', 0):,.0f}元")
    print(f"📊 总盈亏：{portfolio.get('total_pnl', 0):+,.0f}元 ({portfolio.get('total_pnl_pct', 0):+.2f}%)")

    gate = result.get("market_gate", {})
    if gate:
        print(f"\n🏛️ 大盘：{gate.get('summary', 'N/A')}")

    watchlist = result.get("tomorrow_watchlist", [])
    if watchlist:
        print(f"\n👀 明日关注 {len(watchlist)} 只：")
        for s in watchlist[:10]:
            print(f"  • {s['name']} ({s['code']}): {s.get('reason', '')}")

    if push:
        print(f"\n✅ 已推送飞书")
    return result


def cmd_backtest(args):
    """回测"""
    print("🔄 回测中...")
    print("  1. 获取候选池...")
    candidates = universe.run_pipeline()
    if candidates.empty:
        print("  无候选标的，跳过回测")
        return {}

    print(f"  2. 信号检测 ({len(candidates)} 只)...")
    signals = signal_detector.detect_all(candidates)
    if not signals:
        print("  无信号，跳过回测")
        return {}

    print(f"  3. 回测 {len(signals)} 个信号...")
    result = backtest_engine.run(signals, trading_days=args.days)

    print("\n" + "=" * 60)
    print("📊 回测结果")
    print("=" * 60)

    if "error" in result:
        print(f"  ❌ {result['error']}")
        return result

    print(f"  总交易：{result['total_trades']} 笔")
    print(f"  胜/负：{result['wins']} / {result['losses']}")
    print(f"  胜率：{result['win_rate_pct']:.1f}%")
    print(f"  平均盈利：{result['avg_win_pct']:+.2f}%")
    print(f"  平均亏损：{result['avg_loss_pct']:+.2f}%")
    print(f"  盈亏比：{result['profit_loss_ratio']:.2f}")
    print(f"  总收益：{result['total_return_pct']:+.2f}%")
    print(f"  最大回撤：{result['max_drawdown_pct']:.2f}%")
    print(f"  夏普比率：{result['sharpe_ratio']:.2f}")
    print(f"  平均持仓：{result['avg_holding_days']:.1f}天")

    print(f"\n  出场分布：")
    for reason, count in result.get("exit_reasons", {}).items():
        print(f"    {reason}: {count} 笔")

    print(f"\n  按信号类型：")
    for stype, data in result.get("by_signal_type", {}).items():
        print(f"    {stype}: {data['count']}笔, 胜率{data['win_rate']:.0f}%, 均盈亏{data['avg_pnl']:+.1f}%")

    return result


def cmd_positions(args):
    """查看持仓"""
    summary = position_manager.get_positions_summary()

    if not summary["positions"]:
        print("📭 当前无持仓")
        return summary

    print(f"\n💼 持仓概览")
    print(f"  持仓数：{summary['total_positions']} 只")
    print(f"  总成本：{summary['total_cost']:,.0f}元")
    print(f"  总市值：{summary['total_value']:,.0f}元")
    print(f"  总盈亏：{summary['total_pnl']:+,.0f}元 ({summary['total_pnl_pct']:+.2f}%)")
    print()

    for pos in summary["positions"]:
        print(f"  📌 {pos['name']} ({pos['code']})")
        print(f"     成本：{pos.get('cost_price', 0):.2f} | 股数：{pos.get('shares', 0)}")
        print(f"     止损：{pos.get('stop_loss', 0):.2f} | 目标1：{pos.get('target_1', 0):.2f}")
        print()

    return summary


def cmd_add(args):
    """添加持仓"""
    # 获取股票信息
    spot = data_cache.get("spot_all", ttl=3600)
    if spot is None:
        from src.data.source import data_source
        spot = data_source.get_spot_all()
        data_cache.set("spot_all", spot)

    row = spot[spot["code"] == args.code]
    if row.empty:
        print(f"❌ 未找到股票 {args.code}")
        return

    stock_name = row.iloc[0]["name"]
    current_price = row.iloc[0]["price"]

    print(f"📌 添加持仓：{stock_name} ({args.code})")
    print(f"   当前价：{current_price:.2f}元")

    # 计算仓位
    stop_loss = current_price * 0.93  # 默认 -7%
    position_info = position_manager.calculate_position_size({
        "code": args.code,
        "name": stock_name,
        "entry_price": current_price,
        "stop_loss": stop_loss,
        "target_1": current_price * 1.15,
        "target_2": current_price * 1.25,
    })

    # 确认
    print(f"   建议仓位：{position_info['buy_shares']}股 ≈ {position_info['total_amount']:,.0f}元")
    print(f"   止损：{stop_loss:.2f} | 目标1：{current_price*1.15:.2f} | 目标2：{current_price*1.25:.2f}")

    # 保存（实际使用时需要用户确认）
    position_manager.add_position({
        "code": args.code,
        "name": stock_name,
        "entry_price": current_price,
        "cost_price": current_price,
        "shares": position_info["buy_shares"],
        "stop_loss": stop_loss,
        "target_1": current_price * 1.15,
        "target_2": current_price * 1.25,
        "entry_date": datetime.now().strftime("%Y-%m-%d"),
    })

    print(f"✅ 已添加持仓")
    return position_info


def cmd_remove(args):
    """移除持仓"""
    position_manager.remove_position(args.code)
    print(f"✅ 已移除持仓 {args.code}")


def cmd_clear_cache(args):
    """清空缓存"""
    data_cache.clear()
    print("✅ 缓存已清空")


def cmd_status(args):
    """系统状态"""
    print("=" * 60)
    print("📊 alpha-pick 系统状态")
    print("=" * 60)

    print(f"\n📁 数据目录：{DATA_DIR}")
    print(f"📁 缓存目录：{CACHE_DIR}")
    print(f"📁 报告目录：{REPORT_DIR}")

    print(f"\n💰 用户配置：")
    print(f"   资金：{USER_PROFILE['capital']:,.0f}元")
    print(f"   风格：{USER_PROFILE['style']}")
    print(f"   单只上限：{USER_PROFILE['single_stock_max_pct']*100:.0f}%")
    print(f"   最大持仓：{USER_PROFILE['max_holdings']}只")

    print(f"\n🔔 推送配置：")
    print(f"   飞书：{'✅ 已启用' if FEISHU['enabled'] else '❌ 未配置'}")
    print(f"   Webhook：{'已设置' if FEISHU['webhook_url'] else '未设置'}")

    print(f"\n📊 持仓：{len(position_manager.positions)} 只")
    print(f"🧪 测试模式：{'是' if TEST_MODE else '否'}")

    # 检查依赖
    print(f"\n🔧 依赖检查：")
    for mod_name in ["akshare", "pandas", "numpy", "requests"]:
        try:
            mod = __import__(mod_name)
            print(f"   ✅ {mod_name} {getattr(mod, '__version__', 'ok')}")
        except:
            print(f"   ❌ {mod_name} 未安装")


def cmd_performance(args):
    """绩效追踪"""
    tracker = get_tracker()
    summary = tracker.get_summary()
    m = summary.get("metrics", {})

    if not m:
        print("📊 暂无绩效数据")
        print("   请先运行 python cli.py scan 开始记录")
        return summary

    print("=" * 60)
    print("📊 绩效追踪报告")
    print("=" * 60)

    print(f"\n💰 资金表现")
    print(f"   初始资金:  {m.get('initial_equity', 0):>12,.2f} 元")
    print(f"   当前资金:  {m.get('current_equity', 0):>12,.2f} 元")
    print(f"   总收益率:  {m.get('total_return_pct', 0):>+12.2f} %")
    print(f"   年化收益:  {m.get('annualized_return_pct', 0):>+12.2f} %")
    print(f"   记录天数:  {m.get('trading_days', 0):>10} 天")

    print(f"\n📈 绩效指标")
    print(f"   夏普比率:   {m.get('sharpe_ratio', 0):>10.2f}")
    print(f"   索提诺比率: {m.get('sortino_ratio', 0):>10.2f}")
    print(f"   卡玛比率:   {m.get('calmar_ratio', 0):>10.2f}")
    print(f"   最大回撤:   {m.get('max_drawdown_pct', 0):>10.2f} %")
    print(f"   当前回撤:   {m.get('current_drawdown_pct', 0):>10.2f} %")

    print(f"\n📋 交易统计")
    print(f"   总交易:  {m.get('total_trades', 0):>10}")
    print(f"   盈利/亏损: {m.get('wins', 0):>5} / {m.get('losses', 0)}")
    print(f"   胜率:    {m.get('win_rate_pct', 0):>10.2f} %")
    print(f"   平均盈利: {m.get('avg_win_pct', 0):>+10.2f} %")
    print(f"   平均亏损: {m.get('avg_loss_pct', 0):>+10.2f} %")
    print(f"   盈亏比:  {m.get('profit_loss_ratio', 0):>10.2f}")

    # 最近交易
    trades = summary.get("recent_daily", [])
    if trades:
        print(f"\n📅 最近{len(trades)}天表现:")
        for d in trades[-5:]:
            print(f"   {d['date']}: 权益{d['total_equity']:>10,.2f} | 持仓{d['total_positions']}只 | 盈亏{d['total_pnl_pct']:>+6.2f}%")

    # 衰减警告
    decay = summary.get("decay_warnings", [])
    if decay:
        print(f"\n⚠️ 策略衰减警告:")
        for d in decay[-3:]:
            print(f"   [{d['severity']}] {d['date']}: {d['reason']}")

    return summary


def cmd_health(args):
    """系统健康检查"""
    print("=" * 60)
    print("🏥 alpha-pick 系统健康检查")
    print("=" * 60)

    issues = []
    warnings = []
    ok_count = 0

    # 1. 依赖检查
    print("\n🔧 依赖检查")
    deps = {
        "akshare": "1.19.0",
        "pandas": "2.0.0",
        "numpy": "1.24.0",
        "requests": "2.28.0",
    }
    for mod_name, min_ver in deps.items():
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, '__version__', 'unknown')
            print(f"   ✅ {mod_name} {ver}")
            ok_count += 1
        except ImportError:
            print(f"   ❌ {mod_name} 未安装")
            issues.append(f"缺少依赖: {mod_name}")

    # 2. 数据源检查
    print("\n📡 数据源检查")
    try:
        from src.data.source import data_source
        spot = data_source.get_spot_all()
        print(f"   ✅ 行情数据: {len(spot)} 只股票")
        ok_count += 1
    except Exception as e:
        print(f"   ❌ 行情数据获取失败: {e}")
        issues.append(f"行情数据获取失败: {e}")

    try:
        kline = data_source.get_kline("600519", days=30)
        print(f"   ✅ K线数据: {len(kline)} 条 (贵州茅台)")
        ok_count += 1
    except Exception as e:
        print(f"   ❌ K线数据获取失败: {e}")
        issues.append(f"K线数据获取失败: {e}")

    # 3. 缓存检查
    print("\n💾 缓存检查")
    from pathlib import Path
    cache_dir = Path(DATA_DIR) / "cache"
    cache_files = list(cache_dir.glob("*")) if cache_dir.exists() else []
    print(f"   ✅ 缓存文件: {len(cache_files)} 个")
    ok_count += 1

    # 4. 持仓检查
    print("\n💼 持仓检查")
    positions = position_manager.positions
    print(f"   ✅ 当前持仓: {len(positions)} 只")
    if positions:
        for pos in positions:
            print(f"      {pos.get('name', pos.get('code'))}: 成本{pos.get('cost_price', 0):.2f}, 止损{pos.get('stop_loss', 0):.2f}")
    ok_count += 1

    # 5. 绩效检查
    print("\n📊 绩效检查")
    tracker = get_tracker()
    summary = tracker.get_summary()
    m = summary.get("metrics", {})
    if m:
        print(f"   ✅ 绩效记录: {m.get('trading_days', 0)} 天, {m.get('total_trades', 0)} 笔交易")
        ok_count += 1
    else:
        print(f"   ⚠️ 暂无绩效数据")
        warnings.append("暂无绩效数据，请先运行 scan")

    # 6. 飞书检查
    print("\n🔔 推送检查")
    if FEISHU['enabled'] and FEISHU['webhook_url']:
        print(f"   ✅ 飞书已配置")
        ok_count += 1
    else:
        print(f"   ⚠️ 飞书未配置或Webhook为空")
        warnings.append("飞书未配置")

    # 7. 磁盘空间
    print("\n💾 磁盘空间")
    import shutil
    total, used, free = shutil.disk_usage(DATA_DIR.parent.parent)
    free_gb = free / (1024 ** 3)
    print(f"   可用空间: {free_gb:.1f} GB")
    if free_gb < 5:
        warnings.append(f"磁盘空间不足: {free_gb:.1f} GB")

    # 总结
    print(f"\n{'='*60}")
    print(f"📊 健康检查总结: {ok_count} 项通过")
    if issues:
        print(f"\n❌ 问题 ({len(issues)}):")
        for i in issues:
            print(f"   • {i}")
    if warnings:
        print(f"\n⚠️ 警告 ({len(warnings)}):")
        for w in warnings:
            print(f"   • {w}")
    if not issues and not warnings:
        print("\n✅ 系统状态良好，一切正常")
    elif not issues:
        print("\n⚡ 系统基本正常，注意上述警告")
    else:
        print("\n🔴 系统存在问题，请修复后再使用")

    return {"ok": ok_count, "issues": issues, "warnings": warnings}


# ─── CLI 解析 ──────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="alpha-pick: A股中线波段选股系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python cli.py scan           # 盘前选股 + 推送飞书
  python cli.py scan --no-push # 盘前选股，不推送
  python cli.py alert          # 盘中预警
  python cli.py review         # 盘后复盘
  python cli.py backtest       # 回测
  python cli.py positions      # 查看持仓
  python cli.py add 600519     # 添加持仓（贵州茅台）
  python cli.py remove 600519  # 移除持仓
  python cli.py status         # 系统状态
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # scan
    p_scan = subparsers.add_parser("scan", help="盘前选股")
    p_scan.add_argument("--no-push", action="store_true", help="不推送飞书")

    # alert
    p_alert = subparsers.add_parser("alert", help="盘中预警")
    p_alert.add_argument("--no-push", action="store_true", help="不推送飞书")

    # review
    p_review = subparsers.add_parser("review", help="盘后复盘")
    p_review.add_argument("--no-push", action="store_true", help="不推送飞书")

    # backtest
    p_bt = subparsers.add_parser("backtest", help="回测")
    p_bt.add_argument("--days", type=int, default=20, help="持仓天数")

    # positions
    subparsers.add_parser("positions", help="查看持仓")

    # add
    p_add = subparsers.add_parser("add", help="添加持仓")
    p_add.add_argument("code", type=str, help="股票代码")

    # remove
    p_remove = subparsers.add_parser("remove", help="移除持仓")
    p_remove.add_argument("code", type=str, help="股票代码")

    # clear-cache
    subparsers.add_parser("clear-cache", help="清空缓存")

    # status
    subparsers.add_parser("status", help="系统状态")

    # performance
    subparsers.add_parser("performance", help="绩效追踪")

    # health
    subparsers.add_parser("health", help="系统健康检查")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "scan": cmd_scan,
        "alert": cmd_alert,
        "review": cmd_review,
        "backtest": cmd_backtest,
        "positions": cmd_positions,
        "add": cmd_add,
        "remove": cmd_remove,
        "clear-cache": cmd_clear_cache,
        "status": cmd_status,
        "performance": cmd_performance,
        "health": cmd_health,
    }

    cmd = commands.get(args.command)
    if cmd:
        result = cmd(args)
        return result
    else:
        print(f"未知命令: {args.command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
