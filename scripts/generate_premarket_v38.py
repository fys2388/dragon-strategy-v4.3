# -*- coding: utf-8 -*-
"""
V3.8 每日预选池生成器
每日9:15前运行，生成预选池并双推送（飞书+邮件）
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.market_scanner import MarketScanner
from models.stock_selector_v38 import StockSelectorV38
from scripts.feishu_sender import FeishuSender
from scripts.email_sender import EmailSender


class PremarketGeneratorV38:
    """每日预选池生成器 V3.8"""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = os.path.join(self.base_dir, 'reports', 'output')
        os.makedirs(self.output_dir, exist_ok=True)

        self.market_scanner = MarketScanner()
        self.stock_selector = StockSelectorV38()
        self.feishu_sender = FeishuSender()
        self.email_sender = EmailSender()

    def generate_pool(self) -> Dict:
        """生成预选池"""
        print("=" * 60)
        print("V3.8 每日预选池生成")
        print("=" * 60)

        # 1. 市场环境扫描
        print("\n1. 市场环境扫描...")
        market_result = self.market_scanner.scan()
        market_score = market_result['total_score']

        # 2. 选股
        print("\n2. 执行选股...")
        if market_score >= self.market_scanner.open_threshold:
            stocks = self.stock_selector.select_stocks(market_score, limit=10)
        else:
            print(f"市场评分{market_score}<{self.market_scanner.open_threshold}，不符合开仓条件")
            stocks = []

        # 3. 保存预选池
        print("\n3. 保存预选池...")
        today = datetime.now().strftime('%Y%m%d')
        pool_file = os.path.join(self.output_dir, f'{today}_预选池.json')

        pool_data = {
            'date': today,
            'generated_at': datetime.now().isoformat(),
            'market_score': market_score,
            'can_open': market_score >= self.market_scanner.open_threshold,
            'market_details': market_result,
            'stocks': stocks
        }

        with open(pool_file, 'w', encoding='utf-8') as f:
            json.dump(pool_data, f, ensure_ascii=False, indent=2)

        print(f"预选池已保存: {pool_file}")

        return pool_data

    def format_pool_report(self, pool_data: Dict) -> str:
        """格式化预选池报告"""
        today = datetime.now().strftime('%Y年%m月%d日')
        market_score = pool_data['market_score']
        stocks = pool_data['stocks']
        can_open = pool_data['can_open']

        report = f"""# {today} 主板预选池 V3.8

## 市场环境评分：{market_score}/8分

| 评分项 | 得分 | 详情 |
|--------|------|------|
| 沪指vs20日均线 | {pool_data['market_details']['details']['沪指vs20日均线']['score']}/2 | {pool_data['market_details']['details']['沪指vs20日均线']['detail']} |
| 前一日涨停家数 | {pool_data['market_details']['details']['前一日涨停家数']['score']}/2 | {pool_data['market_details']['details']['前一日涨停家数']['detail']} |
| 首板平均溢价率 | {pool_data['market_details']['details']['首板平均溢价率']['score']}/2 | {pool_data['market_details']['details']['首板平均溢价率']['detail']} |
| 炸板率 | {pool_data['market_details']['details']['炸板率']['score']}/1 | {pool_data['market_details']['details']['炸板率']['detail']} |
| 跌停家数 | {pool_data['market_details']['details']['跌停家数']['score']}/1 | {pool_data['market_details']['details']['跌停家数']['detail']} |

**开仓结论：{'✅ 可以开仓' if can_open else '❌ 建议空仓'}**

## 预选标的（最多10只）

| 优先级 | 代码 | 名称 | 现价 | 题材 | 选股路径 | MACD信号 |
|--------|------|------|------|------|----------|----------|
"""

        if not stocks:
            report += "\n暂无符合条件标的\n\n"
        else:
            for i, s in enumerate(stocks, 1):
                report += f"| {i} | {s.get('code', '-')} | {s.get('name', '-')} | {s.get('price', 0):.2f} | {s.get('theme', '热门题材')} | {s.get('selection_path', '-')} | {s.get('macd_signal', '-')} |\n"

        report += f"""
## 买入条件

- 次日开盘涨幅1%-6%
- 买入时间：9:30-10:00，回踩5日均线或分时均价线时买入
- 仓位：首次建仓60%，确认不破均价线加仓至80%，保留20%现金

## 放弃条件

- 开盘涨幅>6%
- 一字板涨停
- 板块内出现2只以上涨停股同时炸板
- 市场环境评分<5分

---
*V3.8 实盘版 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

        return report

    def run(self) -> Tuple[bool, str]:
        """运行生成器"""
        try:
            # 1. 生成预选池
            pool_data = self.generate_pool()

            # 2. 生成报告
            report = self.format_pool_report(pool_data)

            # 3. 保存报告
            today = datetime.now().strftime('%Y%m%d')
            report_file = os.path.join(self.output_dir, f'{today}_预选池.md')
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)

            # 4. 发送飞书
            print("\n4. 发送飞书通知...")
            feishu_msg = self.stock_selector.format_pool_message(
                pool_data['stocks'],
                pool_data['market_score']
            )
            feishu_success = self.feishu_sender.send_text(feishu_msg)

            # 5. 发送邮件
            print("5. 发送邮件...")
            subject = f"【V3.8】{today} 主板预选池"
            email_success = self.email_sender.send_email(subject, report, "预选池", report_file)

            results = []
            results.append(f"预选池已生成：{len(pool_data['stocks'])}只")
            results.append(f"市场评分：{pool_data['market_score']}/8分 ({'可开仓' if pool_data['can_open'] else '空仓'})")
            results.append(f"飞书推送：{'✅成功' if feishu_success else '❌失败'}")
            results.append(f"邮件推送：{'✅成功' if email_success else '❌失败'}")

            return True, "\n".join(results)

        except Exception as e:
            print(f"生成预选池失败: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)


def main():
    generator = PremarketGeneratorV38()
    success, message = generator.run()
    print("\n" + "=" * 40)
    print(message)
    print("=" * 40)


if __name__ == "__main__":
    main()
