# -*- coding: utf-8 -*-
"""在 breakout.py 中插入大盘门控。"""

filepath = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\breakout.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

old = '''            "scan_elapsed": 0.0,
        }

        # 1. 获取股票池'''

new = '''            "scan_elapsed": 0.0,
        }

        # 0. 大盘门控（修复：趋势突破也受大盘评分限制，避免弱势市场推太多）
        from .market_gate import evaluate_market_gate
        score, gate_desc, can_open = evaluate_market_gate()
        result["market_score"] = score
        result["can_open"] = can_open

        # 大盘<3分：不推荐
        if score < 3.0:
            result["summary"] = f"大盘{score:.1f}/7分<3分，趋势突破暂停推荐"
            result["diagnosis"] = f"大盘评分不足，仅观察不推荐"
            result["scan_elapsed"] = round(time.time() - t0, 1)
            return result

        # 大盘3-4分（宽松档）：最多2只，最低得分提高到60
        max_recommend = 2 if score < 4.0 else 5
        min_score_override = 60 if score < 4.0 else 0

        # 1. 获取股票池'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print("插入成功")
else:
    print("未找到插入点")
    idx = content.find("scan_elapsed")
    if idx >= 0:
        print(repr(content[idx:idx+300]))
