# -*- coding: utf-8 -*-
"""
每周学习报告生成器 V3.8
每周日20:00运行，生成周度学习报告并双推送
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.strategy_health_monitor import StrategyHealthMonitor
from scripts.feishu_sender import FeishuSender
from scripts.email_sender import EmailSender


class WeeklyLearningGeneratorV38:
    """每周学习报告生成器 V3.8"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = os.path.join(self.base_dir, 'reports', 'output')
        os.makedirs(self.output_dir, exist_ok=True)

        self.health_monitor = StrategyHealthMonitor()
        self.feishu_sender = FeishuSender()
        self.email_sender = EmailSender()

    def get_week_trades(self) -> List[Dict]:
        """获取本周交易"""
        trades = self.health_monitor.load_trades()

        # 筛选本周交易
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        week_trades = []
        for t in trades:
            try:
                trade_date = datetime.fromisoformat(t.get('buy_date', ''))
                if trade_date >= week_start:
                    week_trades.append(t)
            except:
                continue

        return week_trades

    def calculate_week_stats(self, trades: List[Dict]) -> Dict:
        """计算本周统计"""
        if not trades:
            return {
                'trade_count': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0,
                'total_profit': 0,
                'avg_profit': 0,
                'max_profit': 0,
                'max_loss': 0
            }

        profits = [t.get('profit_pct', 0) for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        return {
            'trade_count': len(trades),
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': len(wins) / len(trades) * 100 if trades else 0,
            'total_profit': sum(profits),
            'avg_profit': sum(profits) / len(profits) if profits else 0,
            'max_profit': max(profits) if profits else 0,
            'max_loss': min(profits) if profits else 0
        }

    def generate_learning_report(self) -> str:
        """生成学习报告"""
        today = datetime.now()
        year = today.isocalendar()[0]
        week_num = today.isocalendar()[1]

        # 获取本周数据
        week_trades = self.get_week_trades()
        stats = self.calculate_week_stats(week_trades)

        # 获取总体数据
        all_trades = self.health_monitor.load_trades()
        health_status = self.health_monitor.check_circuit_breaker()

        report = f"""# {year}年第{week_num}周 周度学习报告 V3.8

## 一、本周交易统计

| 指标 | 数值 |
|------|------|
| 本周交易笔数 | {stats['trade_count']}笔 |
| 胜率 | {stats['win_rate']:.1f}% |
| 盈利交易 | {stats['win_count']}笔 |
| 亏损交易 | {stats['loss_count']}笔 |
| 本周总收益 | {stats['total_profit']:.2f}% |
| 平均单笔收益 | {stats['avg_profit']:.2f}% |
| 最大单笔盈利 | {stats['max_profit']:.2f}% |
| 最大单笔亏损 | {stats['max_loss']:.2f}% |

## 二、本周交易记录

| 日期 | 股票 | 买入价 | 卖出价 | 收益率 | 选股路径 | 持仓天数 |
|------|------|--------|--------|--------|----------|----------|
"""

        if not week_trades:
            report += "\n本周无交易记录\n\n"
        else:
            for t in week_trades:
                report += f"| {t.get('buy_date', '-')} | {t.get('name', '-')}（{t.get('code', '-')}） | {t.get('buy_price', 0):.2f} | {t.get('sell_price', 0):.2f} | {t.get('profit_pct', 0):.2f}% | {t.get('selection_path', '-')} | {t.get('holding_days', 0)}天 |\n"

        report += f"""
## 三、盈亏比分析

"""

        if stats['win_count'] > 0 and stats['loss_count'] > 0:
            avg_win = stats['max_profit'] / stats['win_count'] if stats['win_count'] > 0 else 0
            avg_loss = abs(stats['max_loss']) / stats['loss_count'] if stats['loss_count'] > 0 else 0
            profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

            report += f"""- 平均盈利：{avg_win:.2f}%
- 平均亏损：{avg_loss:.2f}%
- 盈亏比：{profit_loss_ratio:.2f}:1
- 评价：{'优秀' if profit_loss_ratio > 2 else '良好' if profit_loss_ratio > 1.5 else '一般' if profit_loss_ratio > 1 else '需改善'}

"""
        else:
            report += "盈亏数据不足，暂无法分析\n\n"

        report += f"""## 四、策略健康度

### 熔断状态

- 胜率熔断：{'🚨 已触发' if health_status.get('circuit_broken') else '✅ 正常'}（{health_status.get('win_rate', 0):.1f}%）
- 仓位熔断：{'⚠️ 已触发' if health_status.get('position_reduced') else '✅ 正常'}

### 最近10笔交易表现

- 胜率：{health_status.get('win_rate', 0):.1f}%
- 平均收益：{health_status.get('avg_profit', 0):.2f}%

"""

        # 优化建议
        report += f"""
## 五、参数优化建议

### 基于本周数据

"""

        if stats['trade_count'] >= 3:
            if stats['win_rate'] < 50:
                report += "1. 胜率偏低，建议加强MACD筛选条件\n"
            if stats['avg_profit'] < 3:
                report += "2. 平均收益偏低，建议优化止盈策略\n"
            if stats['max_loss'] < -5:
                report += "3. 最大亏损较大，建议严格执行止损\n"
        else:
            report += "本周交易较少，暂无法给出有效优化建议\n"

        report += f"""
## 六、下周操作计划

| 日期 | 操作 | 标的 | 条件 |
|------|------|------|------|
| - | - | - | - |

---
*V3.8 实盘版 | {today.strftime('%Y-%m-%d')}*
"""

        return report

    def run(self) -> Tuple[bool, str]:
        """运行周报生成器"""
        try:
            print("=" * 60)
            print("V3.8 每周学习报告生成")
            print("=" * 60)

            # 1. 生成报告
            print("\n1. 生成周报...")
            report = self.generate_learning_report()

            # 2. 保存报告
            print("2. 保存报告...")
            today = datetime.now()
            year = today.isocalendar()[0]
            week_num = today.isocalendar()[1]
            report_file = os.path.join(self.output_dir, f'{year}W{week_num:02d}_周度学习.md')

            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"周报已保存: {report_file}")

            # 3. 发送飞书
            print("3. 发送飞书通知...")
            week_trades = self.get_week_trades()
            stats = self.calculate_week_stats(week_trades)

            feishu_msg = f"📈 【{year}年第{week_num}周 周度学习报告 V3.8】\n\n"
            feishu_msg += f"本周交易：{stats['trade_count']}笔\n"
            feishu_msg += f"胜率：{stats['win_rate']:.1f}%\n"
            feishu_msg += f"总收益：{stats['total_profit']:.2f}%\n\n"
            feishu_msg += f"⚠️ 仅供参考，不构成投资建议"

            feishu_success = self.feishu_sender.send_text(feishu_msg)

            # 4. 发送邮件
            print("4. 发送邮件...")
            subject = f"【V3.8】{year}年第{week_num}周 周度学习报告"
            email_success = self.email_sender.send_email(subject, report, "周度学习", report_file)

            results = []
            results.append(f"周报已生成：{stats['trade_count']}笔交易，胜率{stats['win_rate']:.1f}%")
            results.append(f"飞书推送：{'✅成功' if feishu_success else '❌失败'}")
            results.append(f"邮件推送：{'✅成功' if email_success else '❌失败'}")

            return True, "\n".join(results)

        except Exception as e:
            print(f"生成周报失败: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)


def main():
    generator = WeeklyLearningGeneratorV38()
    success, message = generator.run()
    print("\n" + "=" * 40)
    print(message)
    print("=" * 40)


if __name__ == "__main__":
    main()
