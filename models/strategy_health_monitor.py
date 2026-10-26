# -*- coding: utf-8 -*-
"""
策略健康度监控模块 V3.8
监控交易绩效，触发熔断机制
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class StrategyHealthMonitor:
    """策略健康度监控器 V3.8"""

    def __init__(self, trades_file: str = None):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 交易记录文件
        if trades_file is None:
            self.trades_file = os.path.join(self.base_dir, 'reports', 'output', '交易记录.json')
        else:
            self.trades_file = trades_file

        # 熔断配置
        config_path = os.path.join(self.base_dir, 'config', 'selection_rules_v38.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.circuit_breaker = self.config['熔断机制']['触发条件']

        # 最近N笔交易
        self.recent_trades = deque(maxlen=10)

        # 熔断状态
        self.circuit_broken = False
        self.position_reduced = False

    def load_trades(self) -> List[Dict]:
        """加载交易记录"""
        try:
            if os.path.exists(self.trades_file):
                with open(self.trades_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('trades', [])
            return []
        except Exception as e:
            print(f"加载交易记录失败: {e}")
            return []

    def save_trades(self, trades: List[Dict]):
        """保存交易记录"""
        try:
            with open(self.trades_file, 'w', encoding='utf-8') as f:
                json.dump({'trades': trades, 'updated': datetime.now().isoformat()}, f,
                         ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存交易记录失败: {e}")

    def add_trade(self, trade: Dict):
        """添加交易记录"""
        trades = self.load_trades()
        trades.append({
            **trade,
            'added_at': datetime.now().isoformat()
        })
        self.save_trades(trades)
        self.recent_trades.append(trade)

    def calculate_win_rate(self, trades: List[Dict]) -> float:
        """计算胜率"""
        if not trades:
            return 0.0

        wins = sum(1 for t in trades if t.get('profit_pct', 0) > 0)
        return wins / len(trades) * 100

    def calculate_avg_profit(self, trades: List[Dict]) -> float:
        """计算平均收益率"""
        if not trades:
            return 0.0

        total = sum(t.get('profit_pct', 0) for t in trades)
        return total / len(trades)

    def check_circuit_breaker(self) -> Dict:
        """检查熔断机制

        触发条件：
        1. 最近10笔胜率<40% → 停止操作，全面复盘
        2. 最近10笔平均收益<5% → 降低仓位至50%试水
        3. 连续3个月跑输沪指 → 暂停策略
        """
        trades = self.load_trades()
        recent_10 = trades[-10:] if len(trades) >= 10 else trades

        if len(recent_10) < 5:  # 至少5笔交易才判断
            return {
                'circuit_broken': False,
                'position_reduced': False,
                'reason': '交易笔数不足5笔'
            }

        win_rate = self.calculate_win_rate(recent_10)
        avg_profit = self.calculate_avg_profit(recent_10)

        result = {
            'checked_at': datetime.now().isoformat(),
            'recent_trades_count': len(recent_10),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'circuit_broken': False,
            'position_reduced': False,
            'actions': []
        }

        # 检查条件1: 胜率熔断
        win_rate_threshold = 40
        if win_rate < win_rate_threshold:
            result['circuit_broken'] = True
            result['actions'].append({
                'condition': f'胜率{win_rate:.1f}%<{win_rate_threshold}%',
                'action': '停止操作，全面复盘'
            })

        # 检查条件2: 收益熔断
        profit_threshold = 5
        if avg_profit < profit_threshold:
            result['position_reduced'] = True
            result['actions'].append({
                'condition': f'平均收益{avg_profit:.2f}%<{profit_threshold}%',
                'action': '降低仓位至50%试水'
            })

        self.circuit_broken = result['circuit_broken']
        self.position_reduced = result['position_reduced']

        return result

    def get_health_report(self) -> str:
        """生成健康度报告"""
        trades = self.load_trades()
        recent_10 = trades[-10:] if len(trades) >= 10 else trades

        win_rate = self.calculate_win_rate(recent_10)
        avg_profit = self.calculate_avg_profit(recent_10)
        circuit_status = self.check_circuit_breaker()

        # 总交易统计
        total_trades = len(trades)
        total_wins = sum(1 for t in trades if t.get('profit_pct', 0) > 0)
        total_loss = total_trades - total_wins
        total_profit = sum(t.get('profit_pct', 0) for t in trades)

        message = f"📊 【策略健康度报告 V3.8】\n"
        message += f"⏰ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        message += f"📈 总体绩效：\n"
        message += f"  总交易笔数：{total_trades}笔\n"
        message += f"  胜率：{total_wins}胜/{total_loss}负\n"
        message += f"  累计收益率：{total_profit:.2f}%\n\n"

        message += f"📋 最近10笔交易：\n"
        message += f"  胜率：{win_rate:.1f}%\n"
        message += f"  平均收益：{avg_profit:.2f}%\n\n"

        message += f"🔒 熔断状态：\n"
        if circuit_status['circuit_broken']:
            message += f"  🚨 已触发熔断 - 停止操作\n"
            for action in circuit_status['actions']:
                message += f"     {action['condition']}\n"
                message += f"     措施：{action['action']}\n"
        elif circuit_status['position_reduced']:
            message += f"  ⚠️ 仓位降至50%试水\n"
            for action in circuit_status['actions']:
                message += f"     {action['condition']}\n"
                message += f"     措施：{action['action']}\n"
        else:
            message += f"  ✅ 策略运行正常\n"

        message += f"\n━━━━━━━━━━━━━━━\n"
        message += f"⚠️ V3.8 策略健康监控"

        return message


def main():
    monitor = StrategyHealthMonitor()
    report = monitor.get_health_report()
    print(report)


if __name__ == "__main__":
    main()
