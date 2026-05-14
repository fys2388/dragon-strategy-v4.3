#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书群机器人通知模块 v3.8
用于推送预选池、复盘报告等到飞书群
含盘中实时预警功能
"""

import json
import requests
import sys
import os
from datetime import datetime
from typing import Dict

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FeishuSender:
    """飞书群机器人消息发送器"""
    
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'config', 'feishu_config.json'
            )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.webhook = self.config['飞书配置']['webhook']
        self.enabled = self.config['飞书配置'].get('enabled', True)
    
    def send_text(self, message):
        """发送纯文本消息"""
        if not self.enabled:
            print("⚠️ 飞书通知已禁用")
            return False
        
        try:
            payload = {
                "msg_type": "text",
                "content": {
                    "text": message
                }
            }
            
            response = requests.post(
                self.webhook,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            result = response.json()
            
            if result.get('code') == 0 or result.get('StatusCode') == 0:
                print(f"✅ 飞书消息发送成功")
                return True
            else:
                print(f"❌ 飞书消息发送失败: {result}")
                return False
                
        except Exception as e:
            print(f"❌ 飞书消息发送异常: {e}")
            return False
    
    def send_markdown(self, title, content):
        """发送 Markdown 格式消息（支持更丰富的格式）"""
        if not self.enabled:
            print("⚠️ 飞书通知已禁用")
            return False
        
        try:
            # 飞书支持富文本消息
            payload = {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "title": title,
                            "content": [
                                [{
                                    "tag": "text",
                                    "text": content
                                }]
                            ]
                        }
                    }
                }
            }
            
            response = requests.post(
                self.webhook,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            result = response.json()
            
            if result.get('code') == 0 or result.get('StatusCode') == 0:
                print(f"✅ 飞书Markdown消息发送成功")
                return True
            else:
                print(f"❌ 飞书Markdown消息发送失败: {result}")
                return False
                
        except Exception as e:
            print(f"❌ 飞书Markdown消息发送异常: {e}")
            return False
    
    def send_dragon_pool(self, date, stocks, market_info=None):
        """发送龙头股池（V3.4版含MACD信号）"""
        today = datetime.now().strftime('%Y年%m月%d日')
        
        message = f"📊 【{today} 主板龙头股池 V3.4】\n"
        message += f"🏆 MACD(6,13,5)过滤后的精选标的\n\n"
        
        if market_info:
            message += f"📈 市场概况：主板涨停 {market_info.get('mainboard_count', 0)} 只\n"
            message += f"   首板 {market_info.get('first_board_count', 0)} | 连板 {market_info.get('continue_board_count', 0)}\n\n"
        
        message += f"✅ 通过MACD筛选的龙头候选（最多2只）：\n\n"
        
        if not stocks:
            message += "暂无符合MACD筛选条件的标的\n\n"
        else:
            for i, stock in enumerate(stocks[:2], 1):  # 最多2只
                name = stock.get('name', 'N/A')
                code = stock.get('code', 'N/A')
                price = stock.get('price', 0)
                theme = stock.get('theme', '热门题材')
                macd_status = stock.get('macd_status', '未知')
                macd_signal = stock.get('macd_signal', '未知')
                buy_min = stock.get('buy_min', 0)
                buy_max = stock.get('buy_max', 0)
                stop_loss = stock.get('stop_loss', 0)
                
                message += f"{i}. {name}（{code}）\n"
                message += f"   💰 现价：{price}元\n"
                message += f"   🏷️ 题材：{theme}\n"
                message += f"   📊 MACD：{macd_signal}\n"
                message += f"   🎯 买入区间：{buy_min}-{buy_max}元\n"
                message += f"   🛡️ 止损位：{stop_loss}元\n"
                message += f"   ⏰ 预期持有：{stock.get('expected_days', 21)}天\n\n"
        
        message += "━━━━━━━━━━━━━━━\n"
        message += "⚠️ 仅供参考，不构成投资建议\n"
        message += "⚠️ 投资有风险，决策需谨慎\n"
        message += "⚠️ MACD(6,13,5) V3.4"
        
        return self.send_text(message)
    
    def send_daily_review(self, date, review_content):
        """发送每日复盘"""
        today = datetime.now().strftime('%Y年%m月%d日')
        
        message = f"📋 【{today} 每日复盘】\n\n"
        message += review_content
        
        return self.send_text(message)
    
    def send_weekly_report(self, year, week, content):
        """发送周度报告"""
        message = f"📈 【{year}年第{week}周 周度报告】\n\n"
        message += content
        
        return self.send_text(message)
    
    def send_monthly_report(self, year, month, content):
        """发送月度报告"""
        message = f"📉 【{year}年{month}月 月度报告】\n\n"
        message += content
        
        return self.send_text(message)
    
    def send_urgent_alert(self, stock: Dict):
        """发送盘中紧急涨停预警（红色紧急提醒）

        Args:
            stock: 股票信息字典
        """
        if not self.enabled:
            print("⚠️ 飞书通知已禁用")
            return False

        message = f"🚨 【涨停预警 - 紧急】\n\n"
        message += f"🔥 {stock.get('name', '-')}（{stock.get('code', '-')}）\n"
        message += f"💰 现价：{stock.get('price', 0)}元\n"
        message += f"⏰ 封板时间：{stock.get('seal_time', '-')}\n"
        message += f"🏷️ 题材：{stock.get('theme', '热门题材')}\n"
        message += f"📊 板块涨停数：{stock.get('sector_limit_up_count', 0)}只\n"
        message += f"📊 MACD信号：{stock.get('macd_signal', '-')}\n\n"
        message += f"📋 次日建议买入区间：{stock.get('buy_min', 0)}-{stock.get('buy_max', 0)}元\n"
        message += f"🛡️ ATR止损价：{stock.get('stop_loss', 0)}元\n\n"
        message += "━━━━━━━━━━━━━━━\n"
        message += "⚠️ V3.8 盘中实时监控预警\n"

        return self.send_text(message)

    def test_connection(self):
        """测试飞书连接"""
        print("🧪 测试飞书连接...")

        message = f"🧪 【21天龙头策略 V3.8 实盘版】\n"
        message += f"✅ 飞书通知模块测试成功！\n"
        message += f"⏰ 测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        message += "📊 V3.8 功能清单：\n"
        message += "  • 每日9:15前预选池推送\n"
        message += "  • 盘中9:30-14:30实时预警\n"
        message += "  • 每日18:00复盘报告\n"
        message += "  • 每周日20:00周度学习\n"
        message += "  • 每月28日20:00月度迭代\n"
        message += "  • 策略健康度监控\n"
        message += "  • 熔断机制保护\n\n"
        message += "━━━━━━━━━━━━━━━\n"
        message += "⚠️ 以上内容仅供参考，不构成投资建议"

        return self.send_text(message)


def main():
    """主函数 - 测试发送"""
    print("=" * 50)
    print("飞书群机器人通知模块 v3.8")
    print("=" * 50)

    sender = FeishuSender()

    # 测试发送
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        sender.test_connection()
        return

    # 如果直接运行，则测试发送
    sender.test_connection()


if __name__ == '__main__':
    main()
