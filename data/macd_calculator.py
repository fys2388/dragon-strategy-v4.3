#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
21天龙头策略V3.4 - MACD指标计算模块
MACD参数: 6, 13, 5 日线级别
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class MACDCalculator:
    """MACD指标计算器"""
    
    def __init__(self, fast=6, slow=13, signal=5):
        """
        初始化MACD计算器
        
        Args:
            fast: 快线EMA周期，默认6
            slow: 慢线EMA周期，默认13
            signal: 信号线周期，默认5
        """
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/'
        }
    
    def _code_to_market(self, code: str) -> str:
        """股票代码转市场代码"""
        if code.startswith('6'):
            return f"1.{code}"
        elif code.startswith('0') or code.startswith('3'):
            return f"0.{code}"
        return f"0.{code}"
    
    def get_historical_data(self, code: str, days: int = 60) -> List[Dict]:
        """获取历史K线数据
        
        Args:
            code: 股票代码
            days: 获取天数
        
        Returns:
            K线数据列表
        """
        secid = self._code_to_market(code)
        
        # 东方财富K线接口
        url = f"http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': 101,  # 日K线
            'fqt': 1,    # 前复权
            'beg': (datetime.now() - timedelta(days=days+30)).strftime('%Y%m%d'),
            'end': '20500101',
            'lmt': days + 30
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()
            
            if data.get('data') and data['data'].get('klines'):
                klines = data['data']['klines']
                result = []
                for line in klines[-days:]:
                    parts = line.split(',')
                    result.append({
                        'date': parts[0],
                        'open': float(parts[1]),
                        'close': float(parts[2]),
                        'high': float(parts[3]),
                        'low': float(parts[4]),
                        'volume': float(parts[5]),
                    })
                return result
        except Exception as e:
            print(f"获取K线数据失败 {code}: {e}")
        
        return []
    
    def calculate_ema(self, prices: List[float], period: int) -> List[float]:
        """计算EMA"""
        if not prices:
            return []
        
        ema = []
        multiplier = 2 / (period + 1)
        
        # 初始EMA为SMA
        sma = sum(prices[:period]) / period
        ema = [sma] * period
        
        for i in range(period, len(prices)):
            ema.append((prices[i] - ema[-1]) * multiplier + ema[-1])
        
        return ema
    
    def calculate_macd(self, prices: List[float]) -> Tuple[List[float], List[float], List[float]]:
        """
        计算MACD
        
        Args:
            prices: 收盘价列表
        
        Returns:
            (dif, dea, macd) 三元组
        """
        if len(prices) < self.slow + self.signal:
            return [], [], []
        
        # 计算快线和慢线的EMA
        fast_ema = self.calculate_ema(prices, self.fast)
        slow_ema = self.calculate_ema(prices, self.slow)
        
        # DIF = 快线EMA - 慢线EMA
        dif = [fast_ema[i] - slow_ema[i] for i in range(len(fast_ema))]
        
        # DEA = DIF的EMA
        dea = self.calculate_ema(dif, self.signal)
        
        # MACD柱 = (DIF - DEA) * 2
        macd = [(dif[i] - dea[i]) * 2 if i < len(dea) else 0 for i in range(len(dif))]
        
        return dif, dea, macd
    
    def analyze_macd(self, code: str) -> Dict:
        """
        分析MACD信号
        
        Returns:
            {
                'code': str,
                'name': str,
                'macd_status': str,  # PASS/FAIL
                'signal_type': str,   # 0轴上方金叉/底背离金叉/弱势金叉/顶背离/持续绿柱/多头走弱
                'dif': float,
                'dea': float,
                'macd_histogram': float,
                'histogram_list': list,  # 最近N根MACD柱
                'crossover_date': str,   # 金叉日期
                'bottom_divergence': bool,  # 是否底背离
                'top_divergence': bool,     # 是否顶背离
                'description': str,  # 信号描述
                'recommendation': str  # 建议
            }
        """
        # 获取历史数据
        klines = self.get_historical_data(code, days=60)
        
        if len(klines) < 30:
            return {
                'code': code,
                'name': '',
                'macd_status': 'FAIL',
                'signal_type': '数据不足',
                'description': 'K线数据不足30天',
                'recommendation': '无法分析'
            }
        
        # 提取收盘价
        prices = [k['close'] for k in klines]
        
        # 计算MACD
        dif, dea, macd = self.calculate_macd(prices)
        
        if not dif:
            return {
                'code': code,
                'name': klines[0].get('name', ''),
                'macd_status': 'FAIL',
                'signal_type': '计算失败',
                'description': 'MACD计算失败',
                'recommendation': '无法分析'
            }
        
        # 获取最新值
        latest_dif = dif[-1]
        latest_dea = dea[-1]
        latest_macd = macd[-1]
        
        # 最近5根MACD柱
        recent_histograms = macd[-6:-1] if len(macd) >= 6 else macd[:-1]
        current_histogram = macd[-1]
        
        # 判断MACD状态
        macd_status = 'FAIL'
        signal_type = ''
        description = ''
        recommendation = ''
        bottom_divergence = False
        top_divergence = False
        crossover_date = ''
        
        # 1. 检查是否在0轴上方
        above_zero = latest_dif > 0 and latest_dea > 0
        
        # 2. 检查金叉（ DIF 从下方穿越 DEA ）
        golden_cross = False
        if len(dif) >= 2:
            # 昨天DIF < DEA，今天DIF >= DEA
            if dif[-2] < dea[-2] and dif[-1] >= dea[-1]:
                golden_cross = True
                # 找到金叉日期
                crossover_date = klines[-1]['date']
        
        # 3. 检查底背离（价格创新低，MACD没创新低）
        if len(prices) >= 20:
            recent_prices = prices[-20:]
            recent_macd = macd[-20:]
            price_low = min(recent_prices)
            macd_low = min(recent_macd)
            
            # 价格是否接近最低
            if abs(prices[-1] - price_low) < prices[-1] * 0.02:  # 2%以内
                # MACD没有创新低
                if latest_macd > macd_low * 0.8:  # 放宽条件
                    bottom_divergence = True
        
        # 4. 检查顶背离（价格创新高，MACD没创新高）
        if len(prices) >= 20:
            recent_prices = prices[-20:]
            recent_macd = macd[-20:]
            price_high = max(recent_prices)
            macd_high = max(recent_macd)
            
            # 价格是否接近最高
            if abs(prices[-1] - price_high) < prices[-1] * 0.02:
                # MACD没有创新高
                if latest_macd < macd_high * 0.8:
                    top_divergence = True
        
        # 5. 检查持续绿柱（空头动能）
        continuous_green = all(h < 0 for h in macd[-5:]) if len(macd) >= 5 else False
        green_shrinking = len(macd) >= 3 and 0 > macd[-1] > macd[-2] > macd[-3]  # 绿柱缩短
        
        # 6. 检查红柱缩短（多头走弱）
        continuous_red = all(h > 0 for h in macd[-5:]) if len(macd) >= 5 else False
        red_shrinking = len(macd) >= 3 and macd[-1] > 0 and macd[-1] < macd[-2] < macd[-3]  # 红柱缩短
        
        # 综合判断
        if top_divergence:
            # 高位顶背离 - 剔除
            signal_type = '高位顶背离'
            description = '价格创新高但MACD未跟随，顶部背离信号'
            recommendation = '❌ 剔除：高位的顶背离，下跌风险大'
            macd_status = 'FAIL'
        
        elif continuous_green and not green_shrinking:
            # 持续绿柱无拐头 - 剔除
            signal_type = '持续绿柱'
            description = 'MACD持续绿柱，空头动能未减弱'
            recommendation = '❌ 剔除：空头持续主导'
            macd_status = 'FAIL'
        
        elif not above_zero and golden_cross:
            # 0轴下方弱势金叉 - 剔除
            signal_type = '0轴下方弱势金叉'
            description = 'MACD在0轴下方金叉，弱势信号'
            recommendation = '❌ 剔除：0轴下方的弱势金叉，反弹力度有限'
            macd_status = 'FAIL'
        
        elif red_shrinking and continuous_red:
            # 红柱缩短多头走弱 - 剔除
            signal_type = '多头动能走弱'
            description = '红柱持续缩短，多头力量衰退'
            recommendation = '❌ 剔除：多头动能走弱，上涨乏力'
            macd_status = 'FAIL'
        
        elif above_zero and golden_cross:
            # 0轴上方金叉 - 通过
            signal_type = '0轴上方金叉'
            description = f'MACD在0轴上方形成金叉，金叉日期：{crossover_date}'
            recommendation = '✅ 通过：强势金叉信号'
            macd_status = 'PASS'
        
        elif bottom_divergence and golden_cross:
            # 底背离后金叉确认 - 通过
            signal_type = '底背离后金叉'
            description = f'股价创新低但MACD未跟随，底背离后金叉确认'
            recommendation = '✅ 通过：底部反转信号'
            macd_status = 'PASS'
        
        elif golden_cross:
            # 普通金叉但位置不佳 - 需谨慎
            signal_type = '普通金叉'
            description = f'MACD金叉但不在强势区域'
            recommendation = '⚠️ 谨慎：需结合其他指标判断'
            macd_status = 'CONDITIONAL'
        
        else:
            # 无明确信号
            signal_type = '等待信号'
            description = 'MACD暂无明确买入信号'
            recommendation = '⏸️ 等待：等待金叉或底背离确认'
            macd_status = 'WAIT'
        
        return {
            'code': code,
            'name': klines[-1].get('name', ''),
            'macd_status': macd_status,
            'signal_type': signal_type,
            'dif': round(latest_dif, 4),
            'dea': round(latest_dea, 4),
            'macd_histogram': round(latest_macd, 4),
            'histogram_list': [round(h, 4) for h in recent_histograms],
            'crossover_date': crossover_date,
            'bottom_divergence': bottom_divergence,
            'top_divergence': top_divergence,
            'above_zero': above_zero,
            'golden_cross': golden_cross,
            'description': description,
            'recommendation': recommendation
        }
    
    def batch_analyze(self, codes: List[str]) -> List[Dict]:
        """批量分析MACD"""
        results = []
        for code in codes:
            result = self.analyze_macd(code)
            results.append(result)
        
        # 按MACD状态排序：PASS > CONDITIONAL > WAIT > FAIL
        status_order = {'PASS': 0, 'CONDITIONAL': 1, 'WAIT': 2, 'FAIL': 3}
        results.sort(key=lambda x: status_order.get(x['macd_status'], 4))
        
        return results


def test_macd():
    """测试MACD模块"""
    print("=" * 60)
    print("MACD指标计算模块 V3.4 测试")
    print("=" * 60)
    
    calc = MACDCalculator(fast=6, slow=13, signal=5)
    
    # 测试股票
    test_codes = ['600530', '600748', '000425']
    
    for code in test_codes:
        print(f"\n分析股票: {code}")
        result = calc.analyze_macd(code)
        
        print(f"  MACD状态: {result['macd_status']}")
        print(f"  信号类型: {result['signal_type']}")
        print(f"  DIF: {result.get('dif', 0):.4f}")
        print(f"  DEA: {result.get('dea', 0):.4f}")
        print(f"  MACD柱: {result.get('macd_histogram', 0):.4f}")
        print(f"  描述: {result['description']}")
        print(f"  建议: {result['recommendation']}")


if __name__ == '__main__':
    test_macd()
