# -*- coding: utf-8 -*-
"""修改v43_push.py，集成趋势突破策略（三策略并行）。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\scripts\v43_push.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加导入
old = 'from strategies.macd_resonance.llm_analyzer import StockAnalyzer, build_analysis_message  # noqa: E402'
new = '''from strategies.macd_resonance.llm_analyzer import StockAnalyzer, build_analysis_message  # noqa: E402
from strategies.macd_resonance.breakout import BreakoutScanner, build_breakout_message  # noqa: E402'''
if old in content:
    content = content.replace(old, new)
    print("✅ 导入添加成功")
else:
    print("❌ 未找到导入位置")

# 2. 在超跌反弹之后添加趋势突破策略
old = '''    except Exception as e:
        print(f"❌ 超跌反弹扫描异常: {e}")
        try:
            send_feishu_alert(f"超跌反弹模式异常: {e}", "策略异常")
        except Exception:
            pass

    # 更新所有跟踪股票的表现'''

new = '''    except Exception as e:
        print(f"❌ 超跌反弹扫描异常: {e}")
        try:
            send_feishu_alert(f"超跌反弹模式异常: {e}", "策略异常")
        except Exception:
            pass

    # ===== 趋势突破模式（第三策略，震荡市补充）=====
    try:
        print("\\n" + "=" * 50)
        print("🚀 开始趋势突破模式扫描...")
        breakout_scanner = BreakoutScanner()
        breakout_box: dict = {}

        def _breakout_scan():
            breakout_box["r"] = breakout_scanner.run(need_push=True, max_stocks=SCAN_MAX_STOCKS)

        t3 = threading.Thread(target=_breakout_scan, daemon=True)
        t3.start()
        t3.join(timeout=SCAN_TIMEOUT_S)
        if t3.is_alive():
            print(f"⏰ 趋势突破扫描超过 {SCAN_TIMEOUT_S}s 超时")
            breakout_result = {"summary": "趋势突破扫描超时", "diagnosis": "", "scan_elapsed": 0, "entries": []}
        else:
            breakout_result = breakout_box.get("r", {"summary": "趋势突破扫描无结果"})

        breakout_msg = build_breakout_message(breakout_result)
        # 智能分析
        breakout_entries = breakout_result.get("entries", [])
        if breakout_entries:
            try:
                analyzer = StockAnalyzer()
                analyzed = analyzer.analyze_batch(breakout_entries)
                analysis_msg = build_analysis_message(analyzed)
                if analysis_msg:
                    breakout_msg = breakout_msg + analysis_msg
            except Exception as e:
                print(f"⚠️ 趋势突破智能分析失败: {e}")
        print(breakout_msg)
        print("\\n[BREAKOUT SUMMARY]", breakout_result.get("summary", ""))
        _send_text(breakout_msg)

        # 记录趋势突破推荐股
        if breakout_entries:
            breakout_time = breakout_result.get("scan_time", now_bjt().strftime("%Y-%m-%d %H:%M:%S"))
            breakout_regime = breakout_result.get("regime", "unknown")
            record_recommendations(breakout_entries, "breakout", breakout_time, breakout_regime)
    except Exception as e:
        print(f"❌ 趋势突破扫描异常: {e}")
        try:
            send_feishu_alert(f"趋势突破模式异常: {e}", "策略异常")
        except Exception:
            pass

    # 更新所有跟踪股票的表现'''

if old in content:
    content = content.replace(old, new)
    print("✅ 趋势突破策略集成成功")
else:
    print("❌ 未找到集成位置")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ v43_push.py 修改完成")
