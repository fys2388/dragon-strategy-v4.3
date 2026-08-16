#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V4.3.1 量化选股扫描器
双路径独立匹配 + 周线五大形态量化识别
数据源：东方财富（免费API）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.v4_data_source import V4DataSource
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple


# ============================================================
# MACD指标计算
# ============================================================
class MACDCalculator:
    """MACD指标计算器"""
    
    @staticmethod
    def calculate(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """计算MACD指标"""
        if len(prices) < slow:
            return {'dif': [], 'dea': [], 'histogram': []}
        
        ema_fast = MACDCalculator._ema(prices, fast)
        ema_slow = MACDCalculator._ema(prices, slow)
        
        # 对齐长度
        offset = slow - fast
        dif = [ema_fast[i] - ema_slow[i + offset] for i in range(len(ema_slow))]
        dea = MACDCalculator._ema(dif, signal)
        
        # 对齐长度
        offset2 = signal - 1
        histogram = [2 * (dif[i + offset2] - dea[i]) for i in range(len(dea))]
        
        return {'dif': dif, 'dea': dea, 'histogram': histogram}
    
    @staticmethod
    def _ema(prices: List[float], period: int) -> List[float]:
        """计算指数移动平均"""
        if len(prices) < period:
            return []
        
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        
        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        
        return ema
    
    @staticmethod
    def check_bottom_divergence(closes: List[float], diff_window: int = 6) -> bool:
        """
        检查日线MACD底背离
        量化定义：
        - 第一个低点A：在其前后5个交易日中，该日收盘价最低
        - 第二个低点B：在低点A之后至少10个交易日，且在其前后5个交易日中收盘价最低
        - 低点B收盘价 < 低点A收盘价（价格创新低）
        - 低点B当日DIF值 > 低点A当日DIF值（指标未创新低）
        """
        if len(closes) < 30:
            return False
        
        # 计算MACD(6,13,5)
        macd = MACDCalculator.calculate(closes, fast=6, slow=13, signal=5)
        dif = macd['dif']
        
        if len(dif) < 20:
            return False
        
        # 找局部低点
        lows = []
        for i in range(5, len(closes) - 5):
            window = closes[i-5:i+6]
            if closes[i] == min(window):
                dif_val = dif[i] if i < len(dif) else 0
                lows.append({'index': i, 'close': closes[i], 'dif': dif_val})
        
        # 检查底背离
        for i in range(len(lows) - 1):
            if lows[i+1]['index'] - lows[i]['index'] >= 10:
                # 价格创新低，但DIF没创新低
                if lows[i+1]['close'] < lows[i]['close'] and lows[i+1]['dif'] > lows[i]['dif']:
                    return True
        
        return False
    
    @staticmethod
    def check_zero_axis_golden_cross(closes: List[float]) -> bool:
        """
        检查零轴上方MACD金叉 + 红柱逐日放大
        """
        if len(closes) < 20:
            return False
        
        macd = MACDCalculator.calculate(closes, fast=6, slow=13, signal=5)
        dif = macd['dif']
        dea = macd['dea']
        histogram = macd['histogram']
        
        if len(dif) < 3:
            return False
        
        # 找金叉
        golden_idx = -1
        for i in range(1, min(len(dif), len(dea))):
            if dif[i-1] <= dea[i-1] and dif[i] > dea[i]:
                if dif[i] > 0:  # 零轴上方
                    golden_idx = i
                    break
        
        if golden_idx == -1 or golden_idx + 2 >= len(histogram):
            return False
        
        # 检查红柱连续3天放大
        red_bars = histogram[golden_idx:]
        consecutive = 0
        for i in range(len(red_bars) - 1):
            if red_bars[i] > 0 and red_bars[i+1] > 0 and red_bars[i+1] > red_bars[i]:
                consecutive += 1
                if consecutive >= 3:
                    return True
            elif red_bars[i] <= 0:
                break
            else:
                consecutive = 0
        
        return consecutive >= 3
    
    @staticmethod
    def check_low_position_golden_cross(closes: List[float]) -> bool:
        """检查零轴下方低位金叉"""
        if len(closes) < 20:
            return False
        
        macd = MACDCalculator.calculate(closes, fast=6, slow=13, signal=5)
        dif = macd['dif']
        dea = macd['dea']
        
        for i in range(1, min(len(dif), len(dea))):
            if dif[i-1] <= dea[i-1] and dif[i] > dea[i]:
                if dif[i] <= 0 and dif[i] > -0.5:
                    return True
        
        return False


# ============================================================
# 大盘环境评分
# ============================================================
class MarketEnvironment:
    """大盘环境评分（总分7分，≥4分才可开仓）"""
    
    def __init__(self, client: V4DataSource):
        self.client = client
    
    def score(self) -> Tuple[int, str]:
        """计算大盘环境评分"""
        score = 0
        details = []
        
        # 1. 沪指站上20日均线+1，20日均线拐头向上再+1
        sh_score, sh_detail = self._check_sh_index()
        score += sh_score
        details.append(sh_detail)
        
        # 2. 两市成交额≥8000亿 +1
        vol_score, vol_detail = self._check_volume()
        score += vol_score
        details.append(vol_detail)
        
        # 3. 炸板率<30% +1（简化：用涨停数据估算）
        breakout_score, breakout_detail = self._check_breakout()
        score += breakout_score
        details.append(breakout_detail)
        
        # 4. 跌停家数<10 +1
        limit_down_score, limit_down_detail = self._check_limit_down()
        score += limit_down_score
        details.append(limit_down_detail)
        
        # 5. 市场赚钱效应（简化）
        profit_score, profit_detail = self._check_profit_effect()
        score += profit_score
        details.append(profit_detail)
        
        return score, "\n".join(details)
    
    def _check_sh_index(self) -> Tuple[int, str]:
        """检查沪指均线状态"""
        indices = self.client.get_market_index()
        sh = indices.get('1.000001', {})
        
        if not sh:
            return 0, "❌ 无法获取沪指数据"
        
        price = sh.get('price', 0)
        
        # 获取日线计算MA20
        kline = self.client.get_daily_kline('000001', 25)
        if len(kline) < 20:
            return 0, "❌ 日线数据不足"
        
        ma20 = sum(d['close'] for d in kline[-20:]) / 20
        ma20_prev = sum(d['close'] for d in kline[-21:-1]) / 20
        
        score = 0
        parts = []
        
        # 站上MA20 +1
        if price > ma20:
            score += 1
            parts.append("✓ 沪指站上20日均线(+1)")
        else:
            parts.append(f"✗ 沪指未站上20日均线({price:.0f}<{ma20:.0f})")
        
        # MA20拐头向上 +1
        if ma20 > ma20_prev:
            score += 1
            parts.append("✓ 20日均线拐头向上(+1)")
        else:
            parts.append("✗ 20日均线未拐头向上")
        
        return min(score, 2), "\n  ".join(parts)
    
    def _check_volume(self) -> Tuple[int, str]:
        """检查成交额"""
        market = self.client.get_market_amplitude()
        total = market.get('total_volume', 0)
        
        if total >= 8000:
            return 1, f"✓ 两市成交额{total:.0f}亿≥8000亿(+1)"
        return 0, f"✗ 两市成交额{total:.0f}亿<8000亿"
    
    def _check_breakout(self) -> Tuple[int, str]:
        """检查炸板率（简化估算）"""
        # 简化：涨停多则炸板率低
        limit_up = self.client.get_limit_up_stocks()
        count = limit_up.get('mainboard_count', 0)
        
        if count >= 30:
            return 1, f"✓ 涨停家数{count}≥30(+1)"
        return 0, f"✗ 涨停家数{count}<30"
    
    def _check_limit_down(self) -> Tuple[int, str]:
        """检查跌停家数"""
        market = self.client.get_market_amplitude()
        count = market.get('limit_down_count', 999)
        
        if count < 10:
            return 1, f"✓ 跌停家数{count}<10(+1)"
        return 0, f"✗ 跌停家数{count}≥10"
    
    def _check_profit_effect(self) -> Tuple[int, str]:
        """检查赚钱效应（简化：涨停家数）"""
        limit_up = self.client.get_limit_up_stocks()
        count = limit_up.get('mainboard_count', 0)
        
        if count >= 50:
            return 2, f"✓ 涨停家数{count}≥50(+2)"
        elif count >= 30:
            return 1, f"✓ 涨停家数{count}≥30(+1)"
        return 0, f"✗ 涨停家数{count}<30"


# ============================================================
# 周线形态识别器
# ============================================================
class WeeklyPattern:
    """周线五大形态量化识别"""
    
    @staticmethod
    def _calc_ma(closes: List[float], period: int) -> List[float]:
        """计算移动平均"""
        result = []
        for i in range(period - 1, len(closes)):
            result.append(sum(closes[i-period+1:i+1]) / period)
        return result
    
    @staticmethod
    def check_stand_on_5w(weekly_data: List[Dict], yearly_change: float) -> Tuple[bool, str]:
        """
        形态1：站稳五周线
        - 本周收盘价 > 5周均线
        - 本周最低价不低于上周最低价
        - 本周收阳线
        - 本周成交量 ≥ 5周均量1.1倍
        """
        if len(weekly_data) < 5:
            return False, "数据不足"
        
        closes = [w['close'] for w in weekly_data]
        volumes = [w['volume'] for w in weekly_data]
        
        # 计算5周均量
        ma5_vol = sum(volumes[-5:]) / 5
        
        current = weekly_data[-1]
        prev = weekly_data[-2]
        
        # 计算5周均线
        ma5_closes = WeeklyPattern._calc_ma(closes, 5)
        ma5 = ma5_closes[-1] if ma5_closes else current['close']
        
        conditions = []
        
        # 收盘>MA5
        c1 = current['close'] > ma5
        conditions.append(("收盘>MA5", c1))
        
        # 不创新低
        c2 = current['low'] >= prev['low']
        conditions.append(("不创新低", c2))
        
        # 收阳线
        c3 = current['close'] > current['open']
        conditions.append(("收阳线", c3))
        
        # 放量
        c4 = current['volume'] >= ma5_vol * 1.1
        conditions.append(("成交量放大", c4))
        
        passed = all(c[1] for c in conditions)
        detail = "✓" + ", ".join([c[0] for c in conditions if c[1]]) if passed else "✗失败: " + ", ".join([c[0] for c in conditions if not c[1]])
        
        return passed, detail
    
    @staticmethod
    def check_volume_pile_pullback(weekly_data: List[Dict]) -> Tuple[bool, str]:
        """
        形态2：周线堆量回调
        """
        if len(weekly_data) < 7:
            return False, "数据不足"
        
        recent = weekly_data[-4:]
        volumes = [w['volume'] for w in recent]
        
        # 前3周递增
        increasing = all(volumes[i] < volumes[i+1] for i in range(2))
        
        # 最后一成交量明显缩量
        max_vol = max(volumes[:3])
        pullback = volumes[-1] <= max_vol * 0.7
        
        # 回调周守线
        closes = [w['close'] for w in recent]
        ma5 = sum(closes[:4]) / 4
        ma20 = sum(closes) / 4
        pullback_valid = recent[-1]['close'] > ma5 and recent[-1]['close'] > ma20
        
        passed = increasing and pullback and pullback_valid
        detail = f"堆量递增:{increasing}, 缩量:{pullback}, 守线:{pullback_valid}"
        
        return passed, detail
    
    @staticmethod
    def check_breakout_platform(weekly_data: List[Dict]) -> Tuple[bool, str]:
        """
        形态3：周线突破震荡平台
        """
        if len(weekly_data) < 5:
            return False, "数据不足"
        
        current = weekly_data[-1]
        
        # 近4周实体最高价
        body_highs = [max(w['close'], w['open']) for w in weekly_data[-5:-1]]
        max_high = max(body_highs)
        
        # 5周均量
        volumes = [w['volume'] for w in weekly_data[-5:]]
        ma5_vol = sum(volumes) / 5
        
        breakout = current['close'] > max_high
        volume_ok = current['volume'] >= ma5_vol * 1.2
        
        passed = breakout and volume_ok
        detail = f"突破{max_high:.2f}:{breakout}, 放量:{volume_ok}"
        
        return passed, detail
    
    @staticmethod
    def check_three_star_bottom(weekly_data: List[Dict], yearly_change: float) -> Tuple[bool, str]:
        """
        形态4：周线三星探底
        - 连续3周K线实体振幅≤1.5%
        - 近12个月跌幅≥30%
        - 最后一周收盘价站上5周均线
        """
        if len(weekly_data) < 4:
            return False, "数据不足"
        
        # 3周小振幅
        small = []
        for w in weekly_data[-4:-1]:
            body_range = abs(w['close'] - w['open']) / w['open'] * 100
            small.append(body_range <= 1.5)
        
        # 年跌幅
        long_term = yearly_change <= -30
        
        # 站上5周线
        closes = [w['close'] for w in weekly_data]
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else closes[-1]
        stand = weekly_data[-1]['close'] > ma5
        
        passed = all(small) and long_term and stand
        detail = f"3周小振幅:{all(small)}, 年跌{yearly_change:.0f}%:{long_term}, 站5周线:{stand}"
        
        return passed, detail
    
    @staticmethod
    def check_multi_ma_bullish(weekly_data: List[Dict]) -> Tuple[bool, str]:
        """
        形态5：周线多均线多头排列
        """
        if len(weekly_data) < 3:
            return False, "数据不足"
        
        closes = [w['close'] for w in weekly_data]
        
        # 计算MA
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else closes[-1]
        ma5_prev = sum(closes[-6:-1]) / 5 if len(closes) >= 6 else closes[-2]
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else sum(closes) / len(closes)
        ma20_prev = sum(closes[-21:-1]) / 21 if len(closes) >= 21 else sum(closes[:-1]) / (len(closes)-1)
        
        # 拐头向上
        ma5_turn = ma5 > ma5_prev
        ma20_turn = ma20 > ma20_prev
        
        # 多头排列
        ma_bullish = ma5 > ma20
        
        # 沿线上行
        along_5w = all(w['close'] > ma5 for w in weekly_data[-2:])
        
        # 成交量温和放大
        vol_increasing = weekly_data[-1]['volume'] > weekly_data[-4]['volume'] if len(weekly_data) >= 4 else True
        
        passed = ma5_turn and ma20_turn and ma_bullish and along_5w
        detail = f"MA5拐:{ma5_turn}, MA20拐:{ma20_turn}, 多头:{ma_bullish}, 沿线:{along_5w}"
        
        return passed, detail


# ============================================================
# 日线路径筛选器
# ============================================================
class DailyPathFilter:
    """日线双路径筛选"""
    
    def __init__(self, client: V4DataSource):
        self.client = client
    
    def filter_path_a(self, code: str, name: str) -> Tuple[bool, str]:
        """
        路径A：超跌反弹左侧池
        - 近12个月跌幅≥30%
        - 近2个月振幅≤20%
        - MACD底背离或零轴下方低位金叉
        """
        daily = self.client.get_daily_kline(code, 250)
        if len(daily) < 60:
            return False, "数据不足"
        
        closes = [d['close'] for d in daily]
        
        # 近12月跌幅
        price_12m = closes[0] if len(closes) >= 250 else closes[-250]
        price_now = closes[-1]
        change_12m = (price_now - price_12m) / price_12m * 100
        
        if change_12m >= -30:
            return False, f"近12月跌幅{change_12m:.1f}%<30%"
        
        # 近2月振幅
        price_2m = closes[-45] if len(closes) >= 45 else closes[0]
        max_2m = max(closes[-45:])
        min_2m = min(closes[-45:])
        amp_2m = (max_2m - min_2m) / min_2m * 100
        
        if amp_2m > 20:
            return False, f"近2月振幅{amp_2m:.1f}%>20%"
        
        # MACD信号
        has_div = MACDCalculator.check_bottom_divergence(closes)
        has_low_gc = MACDCalculator.check_low_position_golden_cross(closes)
        
        if not (has_div or has_low_gc):
            return False, "无MACD底背离/低位金叉"
        
        detail = f"年跌{change_12m:.0f}%, 振幅{amp_2m:.0f}%, {'底背离' if has_div else '低位金叉'}"
        return True, detail
    
    def filter_path_b(self, code: str, name: str) -> Tuple[bool, str]:
        """
        路径B：强势龙头右侧池
        - 近3月跌幅10-25%，近12月<30%
        - 连续3日站稳60日线
        - 放量≥60日均量1.5倍
        - MACD零轴上方金叉+红柱放大
        """
        daily = self.client.get_daily_kline(code, 120)
        if len(daily) < 60:
            return False, "数据不足"
        
        closes = [d['close'] for d in daily]
        
        # 近3月跌幅
        price_3m = closes[-60] if len(closes) >= 60 else closes[0]
        change_3m = (closes[-1] - price_3m) / price_3m * 100
        
        if not (-25 <= change_3m <= -10):
            return False, f"近3月跌幅{change_3m:.1f}%不在10-25%区间"
        
        # 近12月跌幅
        price_12m = closes[0] if len(closes) >= 250 else closes[-250]
        change_12m = (closes[-1] - price_12m) / price_12m * 100
        
        if change_12m <= -30:
            return False, f"近12月跌幅{change_12m:.1f}%≥30%"
        
        # 站稳60日线
        ma60 = sum(closes[-60:]) / 60
        stand_60 = all(daily[-3:][i]['low'] >= ma60 for i in range(3))
        
        if not stand_60:
            return False, "未站稳60日线"
        
        # 放量
        volumes = [d['volume'] for d in daily]
        ma60_vol = sum(volumes[-60:]) / 60
        surge = daily[-1]['volume'] >= ma60_vol * 1.5
        
        if not surge:
            return False, "未放量"
        
        # MACD零轴金叉+红柱放大
        has_gc = MACDCalculator.check_zero_axis_golden_cross(closes)
        
        if not has_gc:
            return False, "无MACD零轴金叉"
        
        detail = f"3月跌{change_3m:.0f}%, 站稳60线, 放量, 零轴金叉"
        return True, detail


# ============================================================
# 硬性准入条件
# ============================================================
class HardFilter:
    """硬性准入条件过滤"""
    
    @staticmethod
    def check(client: V4DataSource, code: str, name: str) -> Tuple[bool, str]:
        """
        1. 仅限60、00开头沪深主板
        2. 现价5~20元
        3. 流通市值40亿~200亿
        4. 近20日日均成交额≥8000万
        5. 非ST/*ST
        """
        # 1. 股票代码
        if not (code.startswith('60') or code.startswith('00')):
            return False, f"非沪深主板({code})"
        
        # 2. ST过滤
        if 'ST' in name or 'st' in name or '*' in name:
            return False, f"ST股票({name})"
        
        # 3. 价格和市值
        quote = client.get_realtime_quote([code])
        if not quote:
            return False, "无法获取行情"
        
        q = quote[0]
        price = q.get('price', 0)
        float_cap = q.get('float_cap', 0)  # 亿
        
        if price < 5 or price > 20:
            return False, f"价格{price}不在5-20元"
        
        if float_cap < 40 or float_cap > 200:
            return False, f"流通市值{float_cap:.0f}亿不在40-200亿"
        
        # 4. 成交额
        daily = client.get_daily_kline(code, 20)
        if len(daily) >= 20:
            avg_amount = sum(d['amount'] for d in daily) / 20
            if avg_amount < 8000:  # 万
                return False, f"日均成交{avg_amount/10000:.0f}亿<0.8亿"
        
        return True, f"准入通过: 价{price}元, 市值{float_cap:.0f}亿"


# ============================================================
# 主选股扫描器
# ============================================================
class V4QuantScanner:
    """V4.3.1量化选股扫描器"""
    
    def __init__(self):
        self.client = V4DataSource()
        self.market_env = MarketEnvironment(self.client)
        self.path_filter = DailyPathFilter(self.client)
    
    def scan(self, max_stocks: int = 200) -> Dict:
        """
        执行完整选股扫描
        """
        # 1. 大盘评分
        market_score, market_detail = self.market_env.score()
        
        result = {
            'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'market_score': market_score,
            'market_detail': market_detail,
            'can_trade': market_score >= 4,
            'path_a_pool': [],
            'path_b_pool': [],
            'recommendations': []
        }
        
        if market_score < 4:
            result['message'] = f"⚠️ 大盘评分{market_score}<4分，空仓观望"
            return result
        
        # 2. 获取主板股票列表（限制数量避免超时）
        all_stocks = self.client.get_mainboard_stocks()
        
        # 按成交额排序，取活跃的
        all_stocks.sort(key=lambda x: x.get('amount', 0), reverse=True)
        all_stocks = all_stocks[:max_stocks]
        
        print(f"开始扫描 {len(all_stocks)} 只股票...")
        
        # 3. 逐个筛选
        for i, stock in enumerate(all_stocks):
            code = stock['code']
            name = stock['name']
            
            if (i + 1) % 20 == 0:
                print(f"  已扫描 {i+1}/{len(all_stocks)}...")
            
            # 硬性准入
            hard_pass, hard_detail = HardFilter.check(self.client, code, name)
            if not hard_pass:
                continue
            
            # 获取K线
            daily = self.client.get_daily_kline(code, 250)
            weekly = self.client.get_weekly_kline(code, 60)
            
            if len(daily) < 60 or len(weekly) < 5:
                continue
            
            # 年跌幅
            closes = [d['close'] for d in daily]
            yearly_change = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
            
            # 路径A
            path_a_pass, path_a_detail = self.path_filter.filter_path_a(code, name)
            if path_a_pass:
                for pattern_func, pattern_name in [
                    (WeeklyPattern.check_three_star_bottom, '三星探底'),
                    (WeeklyPattern.check_stand_on_5w, '站稳五周线'),
                    (WeeklyPattern.check_volume_pile_pullback, '堆量回调'),
                    (WeeklyPattern.check_breakout_platform, '突破平台'),
                    (WeeklyPattern.check_multi_ma_bullish, '多均线多头'),
                ]:
                    pat_pass, pat_detail = pattern_func(weekly, yearly_change)
                    if pat_pass:
                        result['path_a_pool'].append({
                            'code': code,
                            'name': name,
                            'path': 'A',
                            'pattern': pattern_name,
                            'daily_reason': path_a_detail,
                            'weekly_reason': pat_detail,
                            'price': closes[-1],
                            'buy_zone': self._calc_path_a_zone(closes[-1]),
                        })
                        break
            
            # 路径B
            path_b_pass, path_b_detail = self.path_filter.filter_path_b(code, name)
            if path_b_pass:
                for pattern_func, pattern_name in [
                    (WeeklyPattern.check_stand_on_5w, '站稳五周线'),
                    (WeeklyPattern.check_volume_pile_pullback, '堆量回调'),
                    (WeeklyPattern.check_breakout_platform, '突破平台'),
                    (WeeklyPattern.check_multi_ma_bullish, '多均线多头'),
                ]:
                    pat_pass, pat_detail = pattern_func(weekly, yearly_change)
                    if pat_pass:
                        result['path_b_pool'].append({
                            'code': code,
                            'name': name,
                            'path': 'B',
                            'pattern': pattern_name,
                            'daily_reason': path_b_detail,
                            'weekly_reason': pat_detail,
                            'price': closes[-1],
                            'buy_zone': self._calc_path_b_zone(daily),
                        })
                        break
        
        # 4. 生成推荐
        result['recommendations'] = self._generate_rec(result)
        
        return result
    
    def _calc_path_a_zone(self, price: float) -> Dict:
        """路径A低吸区间：收盘价的-3%至+1%"""
        return {'low': round(price * 0.97, 2), 'high': round(price * 1.01, 2)}
    
    def _calc_path_b_zone(self, daily: List[Dict]) -> Dict:
        """路径B低吸区间：60日线至5日线"""
        closes = [d['close'] for d in daily]
        ma5 = sum(closes[-5:]) / 5
        ma60 = sum(closes[-60:]) / 60
        
        if abs(ma5 - ma60) < 0.005 * max(ma5, ma60):
            return {'low': None, 'high': None, 'note': '观望'}
        
        if ma5 >= ma60:
            return {'low': round(ma60, 2), 'high': round(ma5, 2)}
        else:
            return {'low': round(ma5, 2), 'high': round(ma60, 2)}
    
    def _generate_rec(self, result: Dict) -> List[Dict]:
        """生成推荐"""
        recs = []
        
        # 路径A：选跌幅更大
        for s in sorted(result['path_a_pool'], key=lambda x: x['price'], reverse=True)[:3]:
            recs.append({
                'code': s['code'],
                'name': s['name'],
                'path': 'A',
                'pattern': s['pattern'],
                'current_price': s['price'],
                'buy_zone': s['buy_zone'],
                'reason': f"{s['daily_reason']} | {s['weekly_reason']}"
            })
        
        # 路径B：选放量更明显
        for s in sorted(result['path_b_pool'], key=lambda x: x['daily_reason'].find('放量'), reverse=True)[:3]:
            recs.append({
                'code': s['code'],
                'name': s['name'],
                'path': 'B',
                'pattern': s['pattern'],
                'current_price': s['price'],
                'buy_zone': s['buy_zone'],
                'reason': f"{s['daily_reason']} | {s['weekly_reason']}"
            })
        
        return recs
    
    def format_report(self, result: Dict) -> str:
        """格式化报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("📊 V4.3.1 量化选股扫描报告")
        lines.append("=" * 60)
        lines.append(f"\n⏰ 扫描时间: {result['scan_time']}")
        
        lines.append(f"\n📈 大盘环境评分: {result['market_score']}/7")
        for detail in result['market_detail'].split('\n'):
            if detail.strip():
                lines.append(f"  {detail}")
        
        if not result['can_trade']:
            lines.append(f"\n🚫 大盘评分不足4分，空仓观望")
            lines.append("=" * 60)
            return "\n".join(lines)
        
        lines.append(f"\n✅ 大盘环境合格，可进行选股")
        
        lines.append(f"\n📋 路径A（超跌反弹左侧池）: {len(result['path_a_pool'])}只")
        for s in result['path_a_pool'][:5]:
            zone = s['buy_zone']
            zone_str = f"{zone['low']}-{zone['high']}" if zone.get('low') else "观望"
            lines.append(f"  • {s['code']} {s['name']} | {s['pattern']} | {s['price']} | 区间:{zone_str}")
        
        lines.append(f"\n📋 路径B（强势龙头右侧池）: {len(result['path_b_pool'])}只")
        for s in result['path_b_pool'][:5]:
            zone = s['buy_zone']
            zone_str = f"{zone['low']}-{zone['high']}" if zone.get('low') else zone.get('note', '观望')
            lines.append(f"  • {s['code']} {s['name']} | {s['pattern']} | {s['price']} | 区间:{zone_str}")
        
        if result['recommendations']:
            lines.append(f"\n🎯 重点关注 ({len(result['recommendations'])}只)")
            for r in result['recommendations']:
                zone = r['buy_zone']
                zone_str = f"{zone['low']}-{zone['high']}" if zone.get('low') else zone.get('note', '观望')
                lines.append(f"\n  ★ {r['code']} {r['name']}")
                lines.append(f"    路径{r['path']} | {r['pattern']}")
                lines.append(f"    现价: {r['current_price']} | 低吸区间: {zone_str}")
                lines.append(f"    逻辑: {r['reason']}")
        
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ==================== 主入口 ====================

if __name__ == '__main__':
    import time
    
    print("启动V4.3.1量化选股扫描...")
    
    start = time.time()
    scanner = V4QuantScanner()
    
    # 执行扫描（限制股票数量加快速度）
    result = scanner.scan(max_stocks=100)
    
    # 输出报告
    print(scanner.format_report(result))
    
    print(f"\n耗时: {time.time() - start:.1f}秒")
    
    # 保存结果
    import json
    import os
    os.makedirs('reports/output', exist_ok=True)
    with open('reports/output/scan_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n结果已保存到 reports/output/scan_result.json")
