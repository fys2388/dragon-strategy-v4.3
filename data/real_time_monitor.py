# -*- coding: utf-8 -*-
"""
盘中实时监控模块 V3.8
每5分钟扫描一次，仅监控当日预选池标的
触发预警条件时发送飞书红色紧急提醒
"""

import json
import os
import sys
import time
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.eastmoney_source import EastMoneyDataSource
from data.macd_calculator import MACDCalculator


class RealTimeMonitor:
    """盘中实时监控器 V3.8"""

    def __init__(self, pool_file: str = None):
        self.eastmoney = EastMoneyDataSource()
        self.macd = MACDCalculator(fast=6, slow=13, signal=5)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 今日预选池文件
        if pool_file is None:
            today = datetime.now().strftime('%Y%m%d')
            self.pool_file = os.path.join(
                self.base_dir, 'reports', 'output', f'{today}_预选池.json'
            )
        else:
            self.pool_file = pool_file

        # 已提醒标的缓存（当日去重）
        self.notified_today: Set[str] = set()

        # 加载配置
        config_path = os.path.join(self.base_dir, 'config', 'selection_rules_v38.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.trigger_conditions = self.config['盘中监控']

    def load_today_pool(self) -> List[Dict]:
        """加载今日预选池"""
        try:
            if os.path.exists(self.pool_file):
                with open(self.pool_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('stocks', [])
            else:
                print(f"预选池文件不存在: {self.pool_file}")
                return []
        except Exception as e:
            print(f"加载预选池失败: {e}")
            return []

    def is_trading_time(self) -> bool:
        """判断是否在交易时间段"""
        now = datetime.now()
        current_time = now.time()

        # 9:30-11:30 上午
        morning_start = dt_time(9, 30)
        morning_end = dt_time(11, 30)

        # 13:00-14:30 下午
        afternoon_start = dt_time(13, 0)
        afternoon_end = dt_time(14, 30)

        is_weekday = now.weekday() < 5  # 周一=0，周五=4

        if not is_weekday:
            return False

        if morning_start <= current_time <= morning_end:
            return True
        if afternoon_start <= current_time <= afternoon_end:
            return True

        return False

    def check_limit_up_trigger(self, stock: Dict, realtime_data: Dict) -> Optional[Dict]:
        """检查涨停触发条件

        触发条件（必须同时满足）：
        1. 10:30前成功封死首板涨停
        2. 封板时间持续≥15分钟未开板
        3. 涨停时成交量≥前一日总成交量的1.5倍
        4. 所属板块实时涨停数≥3只，且至少2只封板≥15分钟
        5. 板块内有≥1只涨幅>5%的跟风股
        6. 日线MACD(6,13,5)为0轴上方金叉
        7. 满足全部基础选股条件
        """
        code = stock['code']
        name = stock['name']

        # 跳过一字板（开盘即封死）
        open_price = realtime_data.get('open', 0)
        current_price = realtime_data.get('price', 0)
        high_price = realtime_data.get('high', 0)
        limit_up_price = realtime_data.get('limit_up_price', 0)

        # 一字板判断：开盘价=最高价=涨停价
        if open_price == high_price == limit_up_price and high_price > 0:
            print(f"  {code} {name}为一字板，跳过")
            return None

        # 条件1: 检查是否在10:30前涨停
        seal_time = realtime_data.get('seal_time', '')
        if seal_time:
            try:
                seal_dt = datetime.strptime(seal_time, '%H:%M:%S')
                if seal_dt.time() > dt_time(10, 30):
                    print(f"  {code} {name}封板时间{seal_time}在10:30后，不触发")
                    return None
            except:
                pass

        # 条件2: 检查封板是否持续≥15分钟
        seal_duration = realtime_data.get('seal_duration', 0)  # 分钟
        if seal_duration < 15:
            print(f"  {code} {name}封板持续时间{seal_duration}分钟<15分钟，不触发")
            return None

        # 条件3: 检查成交量是否≥1.5倍
        volume_today = realtime_data.get('volume', 0)
        volume_yesterday = stock.get('volume_yesterday', 0)
        if volume_yesterday > 0:
            volume_ratio = volume_today / volume_yesterday
            if volume_ratio < 1.5:
                print(f"  {code} {name}成交量倍数{volume_ratio:.2f}<1.5，不触发")
                return None

        # 条件4: 检查板块涨停数
        sector_stocks = realtime_data.get('sector_limit_up_count', 0)
        sector_sealed_15min = realtime_data.get('sector_sealed_15min', 0)
        if sector_stocks < 3 or sector_sealed_15min < 2:
            print(f"  {code} {name}板块涨停{sector_stocks}只，15分钟封板{sector_sealed_15min}只，不满足")
            return None

        # 条件5: 检查跟风股
        follow_up_count = realtime_data.get('follow_up_stocks', 0)
        if follow_up_count < 1:
            print(f"  {code} {name}板块无跟风股，不触发")
            return None

        # 条件6: MACD检查
        macd_result = self.macd.analyze_macd(code)
        if macd_result.get('macd_status') != 'PASS':
            print(f"  {code} {name}MACD未通过，不触发")
            return None

        # 条件7: 基础选股条件已在预选池中确保

        # 所有条件满足，返回触发信息
        return {
            'code': code,
            'name': name,
            'price': current_price,
            'seal_time': seal_time,
            'theme': stock.get('theme', '热门题材'),
            'sector_limit_up_count': sector_stocks,
            'buy_min': stock.get('buy_min', round(current_price * 1.01, 2)),
            'buy_max': stock.get('buy_max', round(current_price * 1.04, 2)),
            'stop_loss': stock.get('stop_loss', round(current_price * 0.93, 2)),
            'macd_signal': macd_result.get('signal_type', '未知'),
            'atr': stock.get('atr', 0),
            'trigger_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    def scan_pool(self) -> List[Dict]:
        """扫描预选池"""
        pool = self.load_today_pool()

        if not pool:
            print("预选池为空，跳过扫描")
            return []

        print(f"\n开始盘中扫描，预选池共{len(pool)}只标的...")

        triggered_stocks = []

        for stock in pool:
            code = stock['code']
            name = stock['name']

            # 跳过已提醒的标的
            if code in self.notified_today:
                continue

            print(f"\n检查 {code} {name}...")

            try:
                # 获取实时行情
                realtime = self.eastmoney.get_realtime_quote([code])

                if not realtime:
                    print(f"  获取实时数据失败")
                    continue

                realtime_data = realtime[0] if isinstance(realtime, list) else realtime

                # 检查是否涨停
                current_price = realtime_data.get('price', 0)
                limit_up_price = realtime_data.get('limit_up_price', 0)

                if limit_up_price > 0 and abs(current_price - limit_up_price) < 0.01:
                    # 涨停了，检查触发条件
                    trigger = self.check_limit_up_trigger(stock, realtime_data)
                    if trigger:
                        triggered_stocks.append(trigger)
                        self.notified_today.add(code)
                else:
                    print(f"  当前未涨停，价格:{current_price}")

            except Exception as e:
                print(f"  检查出错: {e}")
                continue

        return triggered_stocks

    def format_alert_message(self, stock: Dict) -> str:
        """格式化预警消息"""
        message = f"🚨 【涨停预警】\n\n"
        message += f"🔥 {stock['name']}（{stock['code']}）\n"
        message += f"💰 现价：{stock['price']}元\n"
        message += f"⏰ 封板时间：{stock['seal_time']}\n"
        message += f"🏷️ 题材：{stock['theme']}\n"
        message += f"📊 板块涨停数：{stock['sector_limit_up_count']}只\n"
        message += f"📊 MACD信号：{stock['macd_signal']}\n\n"
        message += f"📋 次日建议买入区间：{stock['buy_min']}-{stock['buy_max']}元\n"
        message += f"🛡️ ATR止损价：{stock['stop_loss']}元\n\n"
        message += f"━━━━━━━━━━━━━━━\n"
        message += f"⚠️ V3.8盘中监控预警"

        return message

    def monitor_once(self) -> List[Dict]:
        """执行一次监控扫描"""
        if not self.is_trading_time():
            print(f"当前非交易时间，跳过监控")
            return []

        triggered = self.scan_pool()
        return triggered

    def monitor_loop(self, interval_seconds: int = 300):
        """持续监控循环"""
        print("=" * 60)
        print("V3.8 盘中实时监控启动")
        print(f"监控频率: 每{interval_seconds // 60}分钟")
        print(f"预选池: {self.pool_file}")
        print("=" * 60)

        while True:
            if self.is_trading_time():
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 执行监控...")
                triggered = self.monitor_once()

                for stock in triggered:
                    message = self.format_alert_message(stock)
                    # 这里会调用飞书发送，但monitor_loop通常由调度器触发
                    print("\n" + "=" * 40)
                    print("🚨 触发预警!")
                    print(message)
                    print("=" * 40)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 非交易时间...")

            print(f"\n等待{interval_seconds // 60}分钟后下次扫描...")
            time.sleep(interval_seconds)


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--loop':
        monitor = RealTimeMonitor()
        monitor.monitor_loop()
    else:
        monitor = RealTimeMonitor()
        triggered = monitor.monitor_once()
        print(f"\n扫描完成，触发预警{len(triggered)}只")


if __name__ == "__main__":
    main()
