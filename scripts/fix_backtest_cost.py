# -*- coding: utf-8 -*-
"""修复backtest_engine.py剩余部分：类定义、成本计算方法、绩效统计。"""
file_path = r"E:\AI\策略\dragon-strategy-v4.3\strategies\macd_resonance\backtest_engine.py"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改类定义和__init__
old = '''class BacktestEngine:
    """轻量级回测引擎。"""

    def __init__(self):
        self.trades = []'''

new = '''class BacktestEngine:
    """轻量级回测引擎。"""

    # A股交易成本配置
    COMMISSION_RATE = 0.00025    # 佣金万2.5
    COMMISSION_MIN = 5.0         # 最低佣金5元
    STAMP_TAX_RATE = 0.001       # 印花税千1（卖出）
    SLIPPAGE_RATE = 0.001        # 滑点0.1%

    def __init__(self, enable_cost: bool = True):
        self.trades = []
        self.enable_cost = enable_cost

    def _calc_buy_cost(self, price: float, shares: int) -> Dict:
        """计算买入成本。"""
        if not self.enable_cost:
            return {"actual_price": price, "commission": 0, "total_cost": price * shares}
        actual_price = price * (1 + self.SLIPPAGE_RATE)
        commission = max(actual_price * shares * self.COMMISSION_RATE, self.COMMISSION_MIN)
        total_cost = actual_price * shares + commission
        return {"actual_price": round(actual_price, 3), "commission": round(commission, 2), "total_cost": round(total_cost, 2)}

    def _calc_sell_cost(self, price: float, shares: int) -> Dict:
        """计算卖出成本。"""
        if not self.enable_cost:
            return {"actual_price": price, "commission": 0, "stamp_tax": 0, "total_revenue": price * shares}
        actual_price = price * (1 - self.SLIPPAGE_RATE)
        commission = max(actual_price * shares * self.COMMISSION_RATE, self.COMMISSION_MIN)
        stamp_tax = actual_price * shares * self.STAMP_TAX_RATE
        total_revenue = actual_price * shares - commission - stamp_tax
        return {"actual_price": round(actual_price, 3), "commission": round(commission, 2),
                "stamp_tax": round(stamp_tax, 2), "total_revenue": round(total_revenue, 2)}'''

if old in content:
    content = content.replace(old, new, 1)
    print("✅ 类定义和成本方法添加成功")
else:
    print("❌ 未找到类定义")

# 2. 修复绩效统计返回（先找到实际格式）
import re
# 找到return { ... } 块，包含total_trades和win_rate
pattern = r'        return \{\n            "status": "ok",\n            "stock_code": stock_code,'
match = re.search(pattern, content)
if match:
    print(f"✅ 找到绩效统计返回，位置{match.start()}")
    # 找到这个return块的结束
    start = match.start()
    # 找到对应的闭合}
    brace_count = 0
    end = start
    for i in range(start, len(content)):
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                break

    old_block = content[start:end]
    # 在trades之前添加交易成本统计
    if '"total_commission"' not in old_block:
        new_block = old_block.replace(
            '            "trades": trades,',
            '''            "total_commission": round(sum(t.get("buy_commission", 0) + t.get("sell_commission", 0) for t in trades), 2),
            "total_stamp_tax": round(sum(t.get("stamp_tax", 0) for t in trades), 2),
            "total_trading_cost": round(sum(t.get("buy_commission", 0) + t.get("sell_commission", 0) + t.get("stamp_tax", 0) for t in trades), 2),
            "cost_enabled": self.enable_cost,
            "trades": trades,'''
        )
        content = content[:start] + new_block + content[end:]
        print("✅ 绩效统计交易成本添加成功")
    else:
        print("ℹ️ 绩效统计已有交易成本")
else:
    print("❌ 未找到绩效统计返回")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ 修复完成")
