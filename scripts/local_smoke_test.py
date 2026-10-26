# -*- coding: utf-8 -*-
"""本地冒烟测试：不触发网络，只验证 import + 基础类型检查。

用法：
    python scripts/local_smoke_test.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))


def main():
    # 1. 验证关键 import（云端 traceback 的根因检查）
    from strategies.macd_resonance.trading_calendar import (
        BJT, now_bjt, is_holiday, is_trading_day, is_trading_time,
        is_premarket, is_aftermarket, is_scan_window, get_current_session,
    )
    print("[1/4] trading_calendar imports OK")

    from strategies.macd_resonance.scanner import Scanner, build_message
    print("[2/4] scanner imports OK")

    from strategies.macd_resonance.breakout import BreakoutScanner
    print("[3/4] breakout imports OK")

    # 2. 验证 is_holiday 基础行为
    from datetime import date, datetime
    assert is_holiday(date(2026, 9, 26)) is True, "周六应为休市日"
    assert is_holiday(date(2026, 9, 28)) is False, "周一应为交易日"
    assert is_holiday(date(2026, 10, 1)) is True, "国庆应为休市日"
    assert is_holiday(date(2026, 10, 8)) is False, "10/8 应为交易日"
    print("[4/4] is_holiday basic checks OK")

    # 3. 验证 scanner.build_message 可调用（用空 result）
    msg = build_message({
        "market_score": 0.0,
        "can_open": False,
        "entries": [],
        "exit_signals": [],
        "market_desc": "test",
        "diagnosis": "test",
        "passed_count": 0,
    })
    assert "MACD共振" in msg, "build_message 应包含 MACD共振"
    print("[5/5] build_message OK")

    print()
    print("=== 全部冒烟测试通过 ✅ ===")
    print("云端 ImportError 根因（is_holiday 缺失）已修复。")
    print("可安全推送。")


if __name__ == "__main__":
    main()
