# -*- coding: utf-8 -*-
"""
市场环境评分模块 V3.8
每日9:15前运行，评估市场环境是否适合开仓
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.eastmoney_source import EastMoneyDataSource


class MarketScanner:
    """市场环境评分器 V3.8"""

    def __init__(self):
        self.eastmoney = EastMoneyDataSource()
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 加载配置
        config_path = os.path.join(self.base_dir, 'config', 'selection_rules_v38.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.scoring_rules = self.config['市场环境评分']
        self.open_threshold = self.scoring_rules['开仓阈值']
        self.max_score = self.scoring_rules['满分']

    def get_market_index_data(self) -> Dict:
        """获取市场指数数据"""
        try:
            indices = self.eastmoney.get_market_index()
            return indices
        except Exception as e:
            print(f"获取市场指数失败: {e}")
            return {}

    def get_limit_up_stats(self) -> Dict:
        """获取涨停统计数据"""
        try:
            limit_up = self.eastmoney.get_limit_up_stocks()
            return {
                'mainboard_count': limit_up.get('mainboard_count', 0),
                'first_board_count': limit_up.get('first_board_count', 0),
                'continue_board_count': limit_up.get('continue_board_count', 0),
                'break_board_rate': limit_up.get('break_board_rate', 50),  # 炸板率
                'limit_down_count': limit_up.get('limit_down_count', 0)
            }
        except Exception as e:
            print(f"获取涨停数据失败: {e}")
            return {
                'mainboard_count': 0,
                'first_board_count': 0,
                'continue_board_count': 0,
                'break_board_rate': 50,
                'limit_down_count': 0
            }

    def get_first_board_premium(self) -> float:
        """获取前一日首板平均溢价率"""
        try:
            # 从东方财富获取昨日首板溢价率数据
            # 这里需要调用东方财富API获取昨日涨停股今日表现
            premium = self.eastmoney.get_yesterday_premium_rate()
            return premium
        except Exception as e:
            print(f"获取首板溢价率失败: {e}")
            return 0.0

    def calculate_ma_status(self, indices: Dict) -> Tuple[int, str]:
        """评估沪指与20日均线关系"""
        score = 0
        detail = ""

        shangzheng = indices.get('上证指数', {})
        price = shangzheng.get('price', 0)
        ma20 = shangzheng.get('ma20', price)  # 如果没有MA20数据，用价格代替

        if price > ma20:
            score += 1
            detail = f"沪指{price}站在20日均线{ma20}上方"
        else:
            detail = f"沪指{price}在20日均线{ma20}下方"

        # 注意：均线的方向需要历史数据判断，这里简化处理
        # 实际应该根据MA20的斜率判断

        return min(score, 2), detail

    def calculate_limit_up_score(self, stats: Dict) -> Tuple[int, str]:
        """计算涨停家数得分"""
        score = 0
        count = stats.get('mainboard_count', 0)

        if count >= 50:
            score = 2
            detail = f"主板涨停{count}家（≥50家，得2分）"
        elif count >= 30:
            score = 1
            detail = f"主板涨停{count}家（≥30家，得1分）"
        else:
            score = 0
            detail = f"主板涨停{count}家（<30家，得0分）"

        return min(score, 2), detail

    def calculate_premium_score(self, premium: float) -> Tuple[int, str]:
        """计算首板溢价率得分"""
        score = 0

        if premium >= 5:
            score = 2
            detail = f"首板溢价率{premium:.2f}%（≥5%，得2分）"
        elif premium >= 2:
            score = 1
            detail = f"首板溢价率{premium:.2f}%（≥2%，得1分）"
        else:
            detail = f"首板溢价率{premium:.2f}%（<2%，得0分）"

        return min(score, 2), detail

    def calculate_break_board_score(self, stats: Dict) -> Tuple[int, str]:
        """计算炸板率得分"""
        rate = stats.get('break_board_rate', 50)

        if rate < 30:
            score = 1
            detail = f"炸板率{rate:.1f}%（<30%，得1分）"
        else:
            score = 0
            detail = f"炸板率{rate:.1f}%（≥30%，得0分）"

        return min(score, 1), detail

    def calculate_limit_down_score(self, stats: Dict) -> Tuple[int, str]:
        """计算跌停家数得分"""
        count = stats.get('limit_down_count', 0)

        if count < 10:
            score = 1
            detail = f"跌停{count}家（<10家，得1分）"
        else:
            score = 0
            detail = f"跌停{count}家（≥10家，得0分）"

        return min(score, 1), detail

    def scan(self) -> Dict:
        """执行完整市场环境扫描"""
        print("=" * 60)
        print("V3.8 市场环境扫描")
        print("=" * 60)

        # 1. 获取市场指数
        print("\n1. 获取市场指数数据...")
        indices = self.get_market_index_data()

        # 2. 获取涨停统计
        print("2. 获取涨停统计数据...")
        stats = self.get_limit_up_stats()

        # 3. 获取首板溢价率
        print("3. 获取首板溢价率...")
        premium = self.get_first_board_premium()

        # 4. 逐项评分
        print("4. 计算各项得分...")

        ma_score, ma_detail = self.calculate_ma_status(indices)
        limit_up_score, limit_up_detail = self.calculate_limit_up_score(stats)
        premium_score, premium_detail = self.calculate_premium_score(premium)
        break_board_score, break_board_detail = self.calculate_break_board_score(stats)
        limit_down_score, limit_down_detail = self.calculate_limit_down_score(stats)

        total_score = ma_score + limit_up_score + premium_score + break_board_score + limit_down_score

        # 5. 判断是否可以开仓
        can_open = total_score >= self.open_threshold

        # 汇总结果
        result = {
            'total_score': total_score,
            'max_score': self.max_score,
            'can_open': can_open,
            'open_threshold': self.open_threshold,
            'details': {
                '沪指vs20日均线': {'score': ma_score, 'max': 2, 'detail': ma_detail},
                '前一日涨停家数': {'score': limit_up_score, 'max': 2, 'detail': limit_up_detail},
                '首板平均溢价率': {'score': premium_score, 'max': 2, 'detail': premium_detail},
                '炸板率': {'score': break_board_score, 'max': 1, 'detail': break_board_detail},
                '跌停家数': {'score': limit_down_score, 'max': 1, 'detail': limit_down_detail}
            },
            'market_data': {
                '上证指数': indices.get('上证指数', {}),
                '深证成指': indices.get('深证成指', {}),
                '涨停统计': stats,
                '首板溢价率': premium
            }
        }

        # 打印结果
        print(f"\n{'='*40}")
        print(f"市场环境评分结果：{total_score}/{self.max_score}分")
        print(f"{'='*40}")
        print(f"✓ 沪指vs20日均线: {ma_score}/2 - {ma_detail}")
        print(f"✓ 前一日涨停家数: {limit_up_score}/2 - {limit_up_detail}")
        print(f"✓ 首板平均溢价率: {premium_score}/2 - {premium_detail}")
        print(f"✓ 炸板率: {break_board_score}/1 - {break_board_detail}")
        print(f"✓ 跌停家数: {limit_down_score}/1 - {limit_down_detail}")
        print(f"{'='*40}")
        print(f"开仓阈值: {self.open_threshold}分")
        print(f"当前得分: {total_score}分")
        print(f"结论: {'✅ 可以开仓' if can_open else '❌ 建议空仓'}")
        print(f"{'='*40}")

        return result

    def get_market_outlook(self, result: Dict) -> str:
        """根据评分生成市场展望"""
        score = result['total_score']

        if score >= 7:
            return "强势上涨，适合重仓参与"
        elif score >= 5:
            return "震荡偏强，可适度参与"
        elif score >= 4:
            return "震荡偏弱，谨慎轻仓"
        else:
            return "弱势行情，建议空仓等待"


def main():
    scanner = MarketScanner()
    result = scanner.scan()
    return result


if __name__ == "__main__":
    main()
