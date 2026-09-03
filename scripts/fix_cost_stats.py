# -*- coding: utf-8 -*-
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\backtest_engine.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''            "final_capital": round(final_capital, 2),
            "trades": trades,'''

new = '''            "final_capital": round(final_capital, 2),
            "total_commission": round(sum(t.get("buy_commission", 0) + t.get("sell_commission", 0) for t in trades), 2),
            "total_stamp_tax": round(sum(t.get("stamp_tax", 0) for t in trades), 2),
            "total_trading_cost": round(sum(t.get("buy_commission", 0) + t.get("sell_commission", 0) + t.get("stamp_tax", 0) for t in trades), 2),
            "cost_enabled": self.enable_cost,
            "trades": trades,'''

if old in content:
    content = content.replace(old, new, 1)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ 绩效统计交易成本添加成功")
else:
    print("❌ 未匹配")
