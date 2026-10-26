# -*- coding: utf-8 -*-
"""
每月迭代报告生成器 V3.8
每月最后1日20:00运行，生成月度迭代报告并双推送
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


class MonthlyIterationGeneratorV38:
    """每月迭代报告生成器 V3.8"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = os.path.join(self.base_dir, 'reports', 'output')
        os.makedirs(self.output_dir, exist_ok=True)

        self.health_monitor = StrategyHealthMonitor()
        self.feishu_sender = FeishuSender()
        self.email_sender = EmailSender()

    def get_month_trades(self) -> List[Dict]:
        """获取本月交易"""
        trades = self.health_monitor.load_trades()

        today = datetime.now()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        month_trades = []
        for t in trades:
            try:
                trade_date = datetime.fromisoformat(t.get('buy_date', ''))
                if trade_date >= month_start:
                    month_trades.append(t)
            except:
                continue

        return month_trades

    def calculate_month_stats(self, trades: List[Dict]) -> Dict:
        """计算本月统计"""
        if not trades:
            return {
                'trade_count': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0,
                'total_profit': 0,
                'avg_profit': 0,
                'max_profit': 0,
                'max_loss': 0,
                'profit_loss_ratio': 0
            }

        profits = [t.get('profit_pct', 0) for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses)) / len(losses) if losses else 0

        return {
            'trade_count': len(trades),
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': len(wins) / len(trades) * 100 if trades else 0,
            'total_profit': sum(profits),
            'avg_profit': sum(profits) / len(profits) if profits else 0,
            'max_profit': max(profits) if profits else 0,
            'max_loss': min(profits) if profits else 0,
            'profit_loss_ratio': avg_win / avg_loss if avg_loss > 0 else 0
        }

    def calculate_monthly_return(self, trades: List[Dict]) -> float:
        """计算月度收益率"""
        if not trades:
            return 0.0

        # 简化计算：累计收益
        total = sum(t.get('profit_pct', 0) for t in trades)
        return total

    def generate_iteration_report(self) -> str:
        """生成迭代报告"""
        today = datetime.now()
        year = today.year
        month = today.month

        # 获取本月数据
        month_trades = self.get_month_trades()
        stats = self.calculate_month_stats(month_trades)
        monthly_return = self.calculate_monthly_return(month_trades)

        # 获取策略健康度
        health_status = self.health_monitor.check_circuit_breaker()
        all_trades = self.health_monitor.load_trades()

        # 版本历史
        current_version = "V3.8"

        report = f"""# {year}年{month:02d}月 月度迭代报告 {current_version}

## 一、本月绩效评估

### 核心指标

| 指标 | 数值 | 评级 |
|------|------|------|
| 月度收益率 | {monthly_return:.2f}% | {'优秀' if monthly_return > 10 else '良好' if monthly_return > 5 else '一般' if monthly_return > 0 else '亏损'} |
| 交易笔数 | {stats['trade_count']}笔 | {'较多' if stats['trade_count'] > 10 else '适中' if stats['trade_count'] > 5 else '较少'} |
| 胜率 | {stats['win_rate']:.1f}% | {'优秀' if stats['win_rate'] > 60 else '良好' if stats['win_rate'] > 50 else '一般' if stats['win_rate'] > 40 else '需改善'} |
| 盈亏比 | {stats['profit_loss_ratio']:.2f}:1 | {'优秀' if stats['profit_loss_ratio'] > 2 else '良好' if stats['profit_loss_ratio'] > 1.5 else '一般'} |

### 收益分析

- 本月总收益：{monthly_return:.2f}%
- 平均单笔收益：{stats['avg_profit']:.2f}%
- 最大单笔盈利：{stats['max_profit']:.2f}%
- 最大单笔亏损：{stats['max_loss']:.2f}%

## 二、交易记录汇总

| 股票 | 买入日期 | 买入价 | 卖出价 | 收益率 | 选股路径 | 持仓天数 |
|------|----------|--------|--------|--------|----------|----------|
"""

        if not month_trades:
            report += "\n本月无交易记录\n\n"
        else:
            for t in month_trades:
                report += f"| {t.get('name', '-')}（{t.get('code', '-')}） | {t.get('buy_date', '-')} | {t.get('buy_price', 0):.2f} | {t.get('sell_price', 0):.2f} | {t.get('profit_pct', 0):.2f}% | {t.get('selection_path', '-')} | {t.get('holding_days', 0)}天 |\n"

        report += f"""
## 三、策略健康度回顾

### 熔断触发记录

- 胜率熔断：{'🚨 已触发' if health_status.get('circuit_broken') else '✅ 未触发'}
- 仓位熔断：{'⚠️ 已触发' if health_status.get('position_reduced') else '✅ 未触发'}

### 本月熔断评估

"""

        if monthly_return < -20:
            report += "⚠️ 本月亏损超过20%，触发月度风控，停止下月操作\n\n"
        elif monthly_return < -10:
            report += "⚠️ 本月亏损超过10%，需警惕下月操作\n\n"
        else:
            report += "✅ 本月未触发月度风控红线\n\n"

        report += f"""### 最近10笔交易表现

- 胜率：{health_status.get('win_rate', 0):.1f}%
- 平均收益：{health_status.get('avg_profit', 0):.2f}%

## 四、规则优化建议

### 本月问题回顾

"""

        # 基于统计数据给出建议
        suggestions = []

        if stats['trade_count'] == 0:
            suggestions.append("1. 本月无交易，需检查选股条件是否过于严格")
        elif stats['win_rate'] < 40:
            suggestions.append("1. 胜率偏低，建议加强MACD 0轴上方金叉的筛选")
        elif stats['win_rate'] < 50:
            suggestions.append("1. 胜率有提升空间，建议优化选股路径A/B的权重")
        else:
            suggestions.append("1. 胜率表现良好，维持现有策略")

        if stats['max_loss'] < -8:
            suggestions.append("2. 最大亏损较大，必须严格执行12%硬性止损")
        elif stats['max_loss'] < -5:
            suggestions.append("2. 止损执行需加强，建议使用平安证券条件单自动执行")

        if stats['profit_loss_ratio'] < 1.5:
            suggestions.append("3. 盈亏比偏低，建议优化阶梯止盈策略")
        else:
            suggestions.append("3. 盈亏比表现良好")

        if monthly_return < 5:
            suggestions.append("4. 整体收益有提升空间，可关注市场环境评分的作用")
        else:
            suggestions.append("4. 本月收益表现优秀")

        for s in suggestions:
            report += s + "\n"

        report += f"""
## 五、版本升级计划

### 当前版本：{current_version}

### 下月优化方向

1. **选股优化**：根据本月数据微调选股参数
2. **止损优化**：确保阶梯止盈止损策略严格执行
3. **风控加强**：加强熔断机制的预警和执行

## 六、下月操作计划

| 目标 | 计划 |
|------|------|
| 月度收益目标 | {'≥10%' if monthly_return < 5 else '≥5%'} |
| 最大亏损控制 | -12% |
| 交易频率 | {'适中' if 5 < stats['trade_count'] < 15 else '控制'} |

---
*{current_version} 实盘版 | {today.strftime('%Y-%m-%d')}*
"""

        return report

    def run(self) -> Tuple[bool, str]:
        """运行月报生成器"""
        try:
            print("=" * 60)
            print("V3.8 每月迭代报告生成")
            print("=" * 60)

            # 1. 生成报告
            print("\n1. 生成月报...")
            report = self.generate_iteration_report()

            # 2. 保存报告
            print("2. 保存报告...")
            today = datetime.now()
            year = today.year
            month = today.month
            report_file = os.path.join(self.output_dir, f'{year}{month:02d}_月度迭代.md')

            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"月报已保存: {report_file}")

            # 3. 发送飞书
            print("3. 发送飞书通知...")
            month_trades = self.get_month_trades()
            stats = self.calculate_month_stats(month_trades)
            monthly_return = self.calculate_monthly_return(month_trades)

            feishu_msg = f"📉 【{year}年{month:02d}月 月度迭代报告 V3.8】\n\n"
            feishu_msg += f"月度收益率：{monthly_return:.2f}%\n"
            feishu_msg += f"交易笔数：{stats['trade_count']}笔\n"
            feishu_msg += f"胜率：{stats['win_rate']:.1f}%\n\n"
            feishu_msg += f"⚠️ 仅供参考，不构成投资建议"

            feishu_success = self.feishu_sender.send_text(feishu_msg)

            # 4. 发送邮件
            print("4. 发送邮件...")
            subject = f"【V3.8】{year}年{month:02d}月 月度迭代报告"
            email_success = self.email_sender.send_email(subject, report, "月度迭代", report_file)

            results = []
            results.append(f"月报已生成：收益率{monthly_return:.2f}%，{stats['trade_count']}笔交易")
            results.append(f"飞书推送：{'✅成功' if feishu_success else '❌失败'}")
            results.append(f"邮件推送：{'✅成功' if email_success else '❌失败'}")

            return True, "\n".join(results)

        except Exception as e:
            print(f"生成月报失败: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)


def main():
    generator = MonthlyIterationGeneratorV38()
    success, message = generator.run()
    print("\n" + "=" * 40)
    print(message)
    print("=" * 40)


if __name__ == "__main__":
    main()
