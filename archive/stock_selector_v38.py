# -*- coding: utf-8 -*-
"""
V3.8 选股模型
基于市场环境评分的双路径选股系统
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.eastmoney_source import EastMoneyDataSource
from data.macd_calculator import MACDCalculator


class StockSelectorV38:
    """V3.8 选股模型"""

    def __init__(self):
        self.eastmoney = EastMoneyDataSource()
        self.macd = MACDCalculator(fast=6, slow=13, signal=5)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 加载配置
        config_path = os.path.join(self.base_dir, 'config', 'selection_rules_v38.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.selection_rules = self.config['选股规则']
        self.basic_rules = self.selection_rules['基础条件']
        self.path_a = self.selection_rules['路径A_超跌反弹型']
        self.path_b = self.selection_rules['路径B_强势龙头型']

    def is_mainboard(self, code: str) -> bool:
        """判断是否沪深主板"""
        if code.startswith(('600', '601', '603', '605')):
            return True
        if code.startswith(('000', '001')):
            return True
        return False

    def check_basic_conditions(self, stock: Dict) -> Tuple[bool, str]:
        """检查基础选股条件"""
        code = stock.get('code', '')
        price = stock.get('price', 0)
        market_cap = stock.get('float_market_cap', 0)  # 流通市值（亿）
        avg_volume = stock.get('avg_volume_20d', 0)  # 20日均成交额（万）

        # 1. 股票范围
        if not self.is_mainboard(code):
            return False, f"{code}非沪深主板"

        # 2. 股价范围
        if price < 3 or price > 10:
            return False, f"{code}股价{price}不在3-10元范围"

        # 3. 流通市值
        if market_cap < 40 or market_cap > 150:
            return False, f"{code}流通市值{market_cap}亿不在40-150亿范围"

        # 4. 近20日成交额
        if avg_volume < 8000:  # 万
            return False, f"{code}20日均成交额{avg_volume/10000:.2f}亿<8000万"

        # 5. 负面筛选
        name = stock.get('name', '')
        if any(x in name for x in ['ST', '*ST', '退市']):
            return False, f"{code}{name}为ST/*ST/退市"

        # 6. 股东户数变化（需要数据源支持）
        # shareholder_change = stock.get('shareholder_change_3m', 0)
        # if shareholder_change > -8:  # 减少≥8%为负值
        #     return False, f"{code}股东户数减少不足8%"

        return True, "基础条件满足"

    def check_path_a(self, stock: Dict) -> Tuple[bool, str]:
        """检查路径A：超跌反弹型"""
        # 近12个月跌幅
        price_change_12m = stock.get('price_change_12m', 0)
        if price_change_12m > -30:  # 跌幅需要≥30%（负值）
            return False, f"{stock['code']}近12月跌幅{price_change_12m}%<30%"

        # 近2个月横盘振幅
        amplitude_2m = stock.get('amplitude_2m', 100)
        if amplitude_2m > 20:
            return False, f"{stock['code']}近2月振幅{amplitude_2m}%>20%"

        # MACD信号
        code = stock['code']
        macd_result = self.macd.analyze_macd(code)

        # 通过条件：0轴上方金叉 或 底背离后金叉确认
        signal = macd_result.get('signal_type', '')
        position = macd_result.get('position', 'below')  # above/below zero

        if position == 'above' and '金叉' in signal:
            return True, f"{code}路径A通过:0轴上方金叉"

        if macd_result.get('bottom_divergence') and '金叉' in signal:
            return True, f"{code}路径A通过:底背离后金叉"

        return False, f"{code}路径AMACD条件未满足"

    def check_path_b(self, stock: Dict) -> Tuple[bool, str]:
        """检查路径B：强势龙头型"""
        # 近3个月跌幅
        price_change_3m = stock.get('price_change_3m', 0)
        if price_change_3m > -10 or price_change_3m < -25:
            return False, f"{stock['code']}近3月跌幅{price_change_3m}%不在10-25%范围"

        # 60日均线
        ma60 = stock.get('ma60', 0)
        price = stock.get('price', 0)
        if price <= ma60:
            return False, f"{stock['code']}收盘价未站上60日均线"

        # 突破放量
        volume_ratio = stock.get('volume_ratio', 0)
        if volume_ratio < 1.5:
            return False, f"{stock['code']}突破放量倍数{volume_ratio}<1.5"

        # 首板涨停（突破后8个交易日内）
        days_since_breakthrough = stock.get('days_since_breakthrough', 999)
        if days_since_breakthrough > 8:
            return False, f"{stock['code']}突破后{days_since_breakthrough}天未出现首板"

        # MACD信号：0轴上方金叉，红柱持续放大
        code = stock['code']
        macd_result = self.macd.analyze_macd(code)

        if macd_result.get('macd_status') != 'PASS':
            return False, f"{code}路径BMACD未通过"

        if macd_result.get('position') != 'above':
            return False, f"{code}MACD未在0轴上方"

        return True, f"{code}路径B通过"

    def select_stocks(self, market_score: int, limit: int = 10) -> List[Dict]:
        """执行选股

        Args:
            market_score: 市场环境评分
            limit: 最多返回标的数
        """
        print("=" * 60)
        print("V3.8 选股系统启动")
        print(f"市场环境评分: {market_score}分")
        print("=" * 60)

        # 获取候选股票（从东方财富涨停数据）
        print("\n1. 获取候选股票...")
        candidates = self.eastmoney.get_dragon_candidates(min_score=60)

        if not candidates:
            print("无候选股票")
            return []

        print(f"候选股票: {len(candidates)}只")

        # 逐个检查
        print("\n2. 筛选股票...")
        selected = []
        path_a_selected = []
        path_b_selected = []
        failed_details = []

        for stock in candidates:
            code = stock['code']
            name = stock['name']

            # 基础条件检查
            basic_pass, basic_msg = self.check_basic_conditions(stock)
            if not basic_pass:
                failed_details.append((code, name, basic_msg))
                continue

            # 路径A检查
            path_a_pass, path_a_msg = self.check_path_a(stock)
            if path_a_pass:
                stock['selection_path'] = 'A'
                stock['selection_reason'] = path_a_msg
                stock['priority'] = 1 if market_score >= 6 else 2
                path_a_selected.append(stock)
                print(f"  ✅ {code} {name} - 路径A通过")
                continue

            # 路径B检查
            path_b_pass, path_b_msg = self.check_path_b(stock)
            if path_b_pass:
                stock['selection_path'] = 'B'
                stock['selection_reason'] = path_b_msg
                stock['priority'] = 1
                path_b_selected.append(stock)
                print(f"  ✅ {code} {name} - 路径B通过")
                continue

            failed_details.append((code, name, f"路径A/B均未通过"))

        # 合并结果，路径A优先
        selected = path_a_selected + path_b_selected

        # 按优先级和市场环境评分排序
        def sort_key(s):
            return (s['priority'], s.get('score', 0), s.get('volume_ratio', 0))

        selected.sort(key=sort_key, reverse=True)

        # 限制数量
        selected = selected[:limit]

        print(f"\n3. 选股结果:")
        print(f"   路径A（超跌反弹）: {len(path_a_selected)}只")
        print(f"   路径B（强势龙头）: {len(path_b_selected)}只")
        print(f"   最终入选: {len(selected)}只")

        return selected

    def format_pool_message(self, stocks: List[Dict], market_score: int) -> str:
        """格式化预选池消息"""
        today = datetime.now().strftime('%Y年%m月%d日')

        message = f"📊 【{today} 主板预选池 V3.8】\n"
        message += f"🏆 市场环境评分: {market_score}/8分\n"
        message += f"📈 预选标的（最多10只）:\n\n"

        if not stocks:
            message += "暂无符合条件标的\n\n"
        else:
            message += "┌─────────────────────────────────────────────────────┐\n"
            message += "│ 代码    名称     股价   题材        路径  MACD信号    │\n"
            message += "├─────────────────────────────────────────────────────┤\n"

            for s in stocks:
                code = s.get('code', '-')
                name = s.get('name', '-')[:4]
                price = s.get('price', 0)
                theme = s.get('theme', '热门题材')[:6]
                path = s.get('selection_path', '-')
                macd = s.get('macd_signal', s.get('selection_reason', '-'))[:8]

                message += f"│ {code}  {name:4s}  {price:5.2f}  {theme:6s}   {path}    {macd:8s} │\n"

            message += "└─────────────────────────────────────────────────────┘\n\n"

            message += "📋 买入条件：\n"
            message += "  • 次日开盘涨幅1%-6%\n"
            message += "  • 9:30-10:00回踩5日均线买入\n"
            message += "  • 首次建仓60%，确认加仓至80%\n\n"

        message += "━━━━━━━━━━━━━━━\n"
        message += "⚠️ 仅供参考，不构成投资建议\n"
        message += "⚠️ V3.8 实盘版"

        return message


def main():
    selector = StockSelectorV38()
    stocks = selector.select_stocks(market_score=6, limit=10)
    message = selector.format_pool_message(stocks, 6)
    print("\n" + message)
    return stocks


if __name__ == "__main__":
    main()
