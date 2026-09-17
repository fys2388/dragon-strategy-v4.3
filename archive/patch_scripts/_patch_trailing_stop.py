# -*- coding: utf-8 -*-
"""为持仓监控添加移动止盈(Trailing Stop)功能。"""

with open('strategies/macd_resonance/position_monitor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在止损止盈检查部分添加移动止盈逻辑
old_check = """            # 止损止盈检查
            stop_loss_price = entry_price * (1 - pos.get("stop_loss_pct", 0.05)) if entry_price > 0 else 0
            take_profit_price = entry_price * (1 + pos.get("take_profit_pct", 0.08)) if entry_price > 0 else 0

            # 买卖一致性检查（黄阳原则）
            buy_reason_check = self._check_buy_reason(pos, current_price)"""

new_check = """            # 止损止盈检查（含移动止盈Trailing Stop）
            base_stop_loss = entry_price * (1 - pos.get("stop_loss_pct", 0.05)) if entry_price > 0 else 0
            take_profit_price = entry_price * (1 + pos.get("take_profit_pct", 0.08)) if entry_price > 0 else 0

            # 移动止盈：获取持仓期间最高价，动态调整止损线
            trailing_stop_price = base_stop_loss
            highest_since_entry = current_price
            try:
                from . import data_source as _ds
                _df = _ds.get_kline_daily(code, count=60)
                if not _df.empty and len(_df) > 5:
                    _closes = _df["close"].astype(float).tolist()
                    # 取最近30天最高价作为持仓期间最高价参考
                    highest_since_entry = max(_closes[-30:]) if len(_closes) >= 30 else max(_closes)
                    pnl_at_high = (highest_since_entry - entry_price) / entry_price * 100 if entry_price > 0 else 0
                    if pnl_at_high >= 8:
                        # 盈利超过8%后，从最高价回撤3%卖出（让利润奔跑）
                        trailing_stop_price = highest_since_entry * 0.97
                    elif pnl_at_high >= 5:
                        # 盈利超过5%后，止损线上移到成本价（保本）
                        trailing_stop_price = entry_price
            except Exception:
                pass

            # 实际止损价取基础止损和移动止损的较高者
            stop_loss_price = max(base_stop_loss, trailing_stop_price) if entry_price > 0 else 0

            # 买卖一致性检查（黄阳原则）
            buy_reason_check = self._check_buy_reason(pos, current_price)"""

if old_check in content:
    content = content.replace(old_check, new_check, 1)
    print('1. 移动止盈逻辑添加成功')
else:
    print('1. 未找到止损止盈检查匹配')

# 在持仓明细中增加移动止盈信息
old_detail = """            if pos.get("stop_loss_price", 0) > 0:
                lines.append(f"    止损{pos['stop_loss_price']:.2f}元 | 止盈{pos['take_profit_price']:.2f}元 | {pos['status']}")
            # 买卖一致性检查（黄阳原则）"""

new_detail = """            if pos.get("stop_loss_price", 0) > 0:
                trailing_note = ""
                if pos.get("trailing_active"):
                    trailing_note = " [移动止盈中]"
                lines.append(f"    止损{pos['stop_loss_price']:.2f}元 | 止盈{pos['take_profit_price']:.2f}元 | {pos['status']}{trailing_note}")
            # 买卖一致性检查（黄阳原则）"""

if old_detail in content:
    content = content.replace(old_detail, new_detail, 1)
    print('2. 持仓明细移动止盈标记添加成功')
else:
    print('2. 未找到持仓明细匹配')

# 在position_details中增加trailing_active字段
old_pos_detail = """                "buy_reason_valid": buy_reason_check["valid"],
                "buy_reason_detail": buy_reason_check["reason"],
            })"""

new_pos_detail = """                "buy_reason_valid": buy_reason_check["valid"],
                "buy_reason_detail": buy_reason_check["reason"],
                "trailing_active": trailing_stop_price > base_stop_loss if entry_price > 0 else False,
                "highest_since_entry": round(highest_since_entry, 2),
            })"""

if old_pos_detail in content:
    content = content.replace(old_pos_detail, new_pos_detail, 1)
    print('3. position_details增加trailing字段成功')
else:
    print('3. 未找到position_details匹配')

with open('strategies/macd_resonance/position_monitor.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('修改完成')
