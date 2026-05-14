# -*- coding: utf-8 -*-
"""
每日复盘报告生成器 V3.8
每日18:00运行，生成复盘报告并双推送
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.eastmoney_source import EastMoneyDataSource
from models.strategy_health_monitor import StrategyHealthMonitor
from scripts.feishu_sender import FeishuSender
from scripts.email_sender import EmailSender


class DailyReviewGeneratorV38:
    """每日复盘报告生成器 V3.8"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = os.path.join(self.base_dir, 'reports', 'output')
        os.makedirs(self.output_dir, exist_ok=True)

        self.eastmoney = EastMoneyDataSource()
        self.health_monitor = StrategyHealthMonitor()
        self.feishu_sender = FeishuSender()
        self.email_sender = EmailSender()

    def get_today_limit_up_data(self) -> Dict:
        """获取今日涨停数据"""
        try:
            limit_up = self.eastmoney.get_limit_up_stocks()
            return limit_up
        except Exception as e:
            print(f"获取涨停数据失败: {e}")
            return {}

    def get_lhb_data(self) -> List[Dict]:
        """获取龙虎榜数据"""
        try:
            # 从东方财富获取今日龙虎榜
            lhb = self.eastmoney.get_longhubang_data()
            return lhb
        except Exception as e:
            print(f"获取龙虎榜失败: {e}")
            return []

    def get_today_market_index(self) -> Dict:
        """获取今日市场指数"""
        try:
            indices = self.eastmoney.get_market_index()
            return indices
        except Exception as e:
            print(f"获取指数失败: {e}")
            return {}

    def calculate_first_board_premium(self) -> float:
        """计算今日首板溢价率"""
        try:
            premium = self.eastmoney.get_yesterday_premium_rate()
            return premium
        except Exception as e:
            print(f"获取溢价率失败: {e}")
            return 0.0

    def generate_review_content(self) -> str:
        """生成复盘报告内容"""
        today = datetime.now()
        today_str = today.strftime('%Y年%m月%d日')

        # 获取数据
        market_index = self.get_today_market_index()
        limit_up_data = self.get_today_limit_up_data()
        lhb_data = self.get_lhb_data()
        premium = self.calculate_first_board_premium()

        # 市场概况
        shangzheng = market_index.get('上证指数', {})
        shangzheng_change = shangzheng.get('change_pct', 0)

        # 涨停统计
        mainboard_count = limit_up_data.get('mainboard_count', 0)
        first_board = limit_up_data.get('first_board_count', 0)
        continue_board = limit_up_data.get('continue_board_count', 0)
        break_board_rate = limit_up_data.get('break_board_rate', 0)

        # 策略健康度
        health_report = self.health_monitor.get_health_report()
        trades = self.health_monitor.load_trades()
        recent_trade = trades[-1] if trades else None

        # 生成报告
        report = f"""# {today_str} 每日复盘 V3.8

## 一、今日市场概况

| 指标 | 数值 |
|------|------|
| 上证指数涨跌幅 | {shangzheng_change:+.2f}% |
| 主板涨停家数 | {mainboard_count}只 |
| 首板涨停 | {first_board}只 |
| 连板涨停 | {continue_board}只 |
| 炸板率 | {break_board_rate:.1f}% |

## 二、今日涨停复盘

### 涨停股分析

- 主板涨停{mainboard_count}只，其中首板{first_board}只，连板{continue_board}只
- 市场情绪：{'强势' if shangzheng_change > 0.5 else '偏弱' if shangzheng_change < -0.5 else '中性'}

### 首板溢价率

- 今日首板平均溢价率：{premium:.2f}%
- 溢价率解读：{'市场追涨情绪强' if premium > 5 else '追涨情绪一般' if premium > 2 else '市场谨慎'}

## 三、龙虎榜复盘验证

### 持仓个股龙虎榜（如有）

"""

        # 龙虎榜数据
        if lhb_data:
            for item in lhb_data[:5]:
                report += f"""**{item.get('name', '-')}（{item.get('code', '-')}）**

- 买入席位：{item.get('buy_seats', '-')}
- 卖出席位：{item.get('sell_seats', '-')}
- 机构动向：{item.get('institution_action', '-')}
- 解读：{item.get('interpretation', '-')}

"""
        else:
            report += "今日无持仓个股龙虎榜数据\n\n"

        report += f"""### 龙虎榜操作建议

- 买入前五有机构：持仓信心+1，可继续持有
- 卖出前五有机构：提高警惕，严格执行止损
- 无龙虎榜数据：正常执行原计划

## 四、次日市场环境预判

"""

        # 次日预判
        tomorrow_change = shangzheng_change  # 简化处理
        if tomorrow_change > 1:
            report += "- 市场强势，次日环境预期较好\n"
        elif tomorrow_change > 0:
            report += "- 市场震荡，次日环境预期一般\n"
        else:
            report += "- 市场偏弱，次日需谨慎操作\n"

        report += f"""
## 五、策略健康度

### 最近交易记录

"""

        if recent_trade:
            report += f"""- 股票：{recent_trade.get('name', '-')}（{recent_trade.get('code', '-')}）
- 买入日期：{recent_trade.get('buy_date', '-')}
- 买入价格：{recent_trade.get('buy_price', 0):.2f}元
- 当前收益率：{recent_trade.get('profit_pct', 0):.2f}%
- 持仓天数：{recent_trade.get('holding_days', 0)}天

"""
        else:
            report += "近期无交易记录\n\n"

        report += f"""### 熔断检查

{health_report}

## 六、操作计划

| 操作类型 | 标的 | 条件 | 价格区间 |
|----------|------|------|----------|
| - | - | - | - |

---
*V3.8 实盘版 | {today.strftime('%Y-%m-%d %H:%M')} 生成*
"""

        return report

    def run(self) -> Tuple[bool, str]:
        """运行复盘生成器"""
        try:
            print("=" * 60)
            print("V3.8 每日复盘报告生成")
            print("=" * 60)

            # 1. 生成复盘内容
            print("\n1. 生成复盘内容...")
            report = self.generate_review_content()

            # 2. 保存报告
            print("2. 保存报告...")
            today = datetime.now().strftime('%Y%m%d')
            report_file = os.path.join(self.output_dir, f'{today}_每日复盘.md')

            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"复盘报告已保存: {report_file}")

            # 3. 发送飞书
            print("3. 发送飞书通知...")
            feishu_msg = f"📋 【{today} 每日复盘 V3.8】\n\n已生成复盘报告，包含：\n• 今日市场概况\n• 涨停复盘\n• 龙虎榜验证\n• 策略健康度\n• 次日预判\n\n详情请查看报告"
            feishu_success = self.feishu_sender.send_text(feishu_msg)

            # 4. 发送邮件
            print("4. 发送邮件...")
            subject = f"【V3.8】{today} 每日复盘"
            email_success = self.email_sender.send_email(subject, report, "每日复盘", report_file)

            results = []
            results.append("复盘报告已生成")
            results.append(f"飞书推送：{'✅成功' if feishu_success else '❌失败'}")
            results.append(f"邮件推送：{'✅成功' if email_success else '❌失败'}")

            return True, "\n".join(results)

        except Exception as e:
            print(f"生成复盘失败: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)


def main():
    generator = DailyReviewGeneratorV38()
    success, message = generator.run()
    print("\n" + "=" * 40)
    print(message)
    print("=" * 40)


if __name__ == "__main__":
    main()
