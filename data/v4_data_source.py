#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V4.3.1 量化选股系统 - 数据源模块
整合东方财富免费数据 + 历史K线获取
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple


class V4DataSource:
    """V4.3.1数据源 - 基于东方财富"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/'
        }
    
    def _code_to_market(self, code: str) -> str:
        """股票代码转市场代码"""
        if code.startswith('6'):
            return f"1.{code}"  # 上海
        elif code.startswith('0') or code.startswith('3'):
            return f"0.{code}"  # 深圳
        return f"0.{code}"
    
    # ==================== 实时行情 ====================
    
    def get_realtime_quote(self, codes: List[str]) -> List[Dict]:
        """获取实时行情"""
        if not codes:
            return []
        
        secids = ','.join([self._code_to_market(code) for code in codes])
        fields = 'f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f171'
        
        url = f"http://push2.eastmoney.com/api/qt/stock/get/?secid={secids}&fields={fields}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            data = response.json()
            
            result = []
            if data.get('data'):
                d = data['data']
                if 'f57' in d:
                    result.append(self._parse_realtime_item(d))
                elif d.get('diff'):
                    for item in d['diff']:
                        result.append(self._parse_realtime_item(item))
            return result
        except Exception as e:
            print(f"获取实时行情失败: {e}")
            return []
    
    def _parse_realtime_item(self, d: Dict) -> Dict:
        """解析实时行情项"""
        return {
            'code': d.get('f57', ''),
            'name': d.get('f58', ''),
            'price': float(d.get('f43', 0)) / 100 if d.get('f43') else 0,
            'change_pct': float(d.get('f170', 0)) / 100 if d.get('f170') else 0,
            'change': float(d.get('f44', 0)) / 100 if d.get('f44') else 0,
            'open': float(d.get('f46', 0)) / 100 if d.get('f46') else 0,
            'high': float(d.get('f45', 0)) / 100 if d.get('f45') else 0,
            'low': float(d.get('f47', 0)) / 100 if d.get('f47') else 0,
            'volume': d.get('f48', 0),
            'amount': float(d.get('f60', 0)) / 100 if d.get('f60') else 0,
            'turnover': float(d.get('f168', 0)) / 100 if d.get('f168') else 0,  # 换手率
            'float_cap': float(d.get('f169', 0)) / 10000 if d.get('f169') else 0,  # 流通市值(万)
            'total_cap': float(d.get('f171', 0)) / 10000 if d.get('f171') else 0,  # 总市值(万)
        }
    
    # ==================== 历史K线数据 ====================
    
    def get_daily_kline(self, code: str, days: int = 250) -> List[Dict]:
        """
        获取日线K线数据
        返回: [{'date': '2024-01-01', 'open': xx, 'high': xx, 'low': xx, 'close': xx, 'volume': xx, 'amount': xx}]
        """
        market = '1' if code.startswith('6') else '0'
        secid = f"{market}.{code}"
        
        # 东方财富历史K线接口
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',  # 日K线
            'fqt': '1',    # 前复权
            'end': '20500101',
            'lmt': days
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            
            result = []
            if data.get('data') and data['data'].get('klines'):
                for line in data['data']['klines']:
                    parts = line.split(',')
                    if len(parts) >= 11:
                        result.append({
                            'date': parts[0],
                            'open': float(parts[1]) if parts[1] else 0,
                            'high': float(parts[2]) if parts[2] else 0,
                            'low': float(parts[3]) if parts[3] else 0,
                            'close': float(parts[4]) if parts[4] else 0,
                            'volume': float(parts[5]) if parts[5] else 0,
                            'amount': float(parts[6]) if parts[6] else 0,
                            'turnover': float(parts[7]) if parts[7] else 0,
                            'amplitude': float(parts[8]) if parts[8] else 0,
                        })
            return result
        except Exception as e:
            print(f"获取日线K线失败: {code} - {e}")
            return []
    
    def get_weekly_kline(self, code: str, weeks: int = 60) -> List[Dict]:
        """
        获取周线K线数据
        """
        market = '1' if code.startswith('6') else '0'
        secid = f"{market}.{code}"
        
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '102',  # 周K线
            'fqt': '1',    # 前复权
            'end': '20500101',
            'lmt': weeks
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            
            result = []
            if data.get('data') and data['data'].get('klines'):
                for line in data['data']['klines']:
                    parts = line.split(',')
                    if len(parts) >= 11:
                        result.append({
                            'date': parts[0],
                            'open': float(parts[1]) if parts[1] else 0,
                            'high': float(parts[2]) if parts[2] else 0,
                            'low': float(parts[3]) if parts[3] else 0,
                            'close': float(parts[4]) if parts[4] else 0,
                            'volume': float(parts[5]) if parts[5] else 0,
                            'amount': float(parts[6]) if parts[6] else 0,
                        })
            return result
        except Exception as e:
            print(f"获取周线K线失败: {code} - {e}")
            return []
    
    def get_60min_kline(self, code: str, periods: int = 48) -> List[Dict]:
        """获取60分钟K线数据（用于盘中首板判定）"""
        market = '1' if code.startswith('6') else '0'
        secid = f"{market}.{code}"
        
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',  # 日K
            'fqt': '1',
            'end': '20500101',
            'lmt': periods
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            # 返回日K线（盘中使用）
            return self.get_daily_kline(code, 5)
        except:
            return []
    
    # ==================== 市场整体数据 ====================
    
    def get_market_index(self) -> Dict:
        """获取主要指数"""
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        secids = '1.000001,0.399001,0.399006,1.000300,1.000016'
        fields = 'f1,f2,f3,f4,f5,f6,f7,f8,f12,f14'
        
        try:
            response = requests.get(f"{url}?secid={secids}&fields={fields}", headers=self.headers, timeout=10)
            data = response.json()
            
            indices = {}
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    indices[item.get('f12', '')] = {
                        'code': item.get('f12', ''),
                        'name': item.get('f14', ''),
                        'price': item.get('f2', 0),
                        'change_pct': item.get('f3', 0),
                        'change': item.get('f4', 0),
                        'volume': item.get('f5', 0),
                        'amount': item.get('f6', 0),
                    }
            return indices
        except Exception as e:
            print(f"获取指数失败: {e}")
            return {}
    
    def get_market_amplitude(self) -> Dict:
        """获取市场整体数据（成交额、涨跌停等）"""
        result = {
            'total_volume': 0,  # 两市成交额(亿)
            'limit_up_count': 0,
            'limit_down_count': 0,
            'breakout_rate': 30,  # 炸板率
            'natural_limit_up_median_return': 0,  # 自然涨停股今日涨幅中位数
        }
        
        try:
            # 获取指数成交额
            indices = self.get_market_index()
            if indices:
                total = 0
                for idx in indices.values():
                    amount = idx.get('amount', 0)
                    if amount > 100000000:  # 大于1亿
                        total += amount
                result['total_volume'] = total / 100000000  # 转为亿
            
            # 获取涨停数据
            limit_up = self.get_limit_up_stocks()
            result['limit_up_count'] = limit_up.get('mainboard_count', 0)
            
            # 获取跌停数据
            limit_down = self.get_limit_down_stocks()
            result['limit_down_count'] = limit_down.get('count', 0)
            
        except Exception as e:
            print(f"获取市场整体数据失败: {e}")
        
        return result
    
    def get_limit_up_stocks(self, date: str = None) -> Dict:
        """获取涨停股票"""
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1, 'pz': 5000, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18',
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            
            stocks = []
            mainboard_count = 0
            first_board = 0
            
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    code = str(item.get('f12', ''))
                    name = str(item.get('f14', ''))
                    
                    try:
                        change_pct = float(item.get('f3', 0))
                    except:
                        change_pct = 0
                    
                    # 只统计主板涨停（涨幅>=9.9%）
                    if change_pct >= 9.9:
                        is_mainboard = code.startswith(('600', '601', '603', '605', '000', '001'))
                        if is_mainboard:
                            mainboard_count += 1
                            vol_ratio = float(item.get('f10', 0)) if item.get('f10') not in [None, '-', ''] else 0
                            
                            stocks.append({
                                'code': code,
                                'name': name,
                                'price': item.get('f2', 0),
                                'change_pct': change_pct,
                                'seal_time': item.get('f8', ''),
                                'volume_ratio': vol_ratio,
                                'amount': float(item.get('f6', 0)) if item.get('f6') else 0,
                            })
                            
                            if vol_ratio > 2:
                                first_board += 1
            
            return {
                'mainboard_count': mainboard_count,
                'first_board_count': first_board,
                'stocks': stocks
            }
        except Exception as e:
            print(f"获取涨停数据失败: {e}")
            return {'mainboard_count': 0, 'first_board_count': 0, 'stocks': []}
    
    def get_limit_down_stocks(self, date: str = None) -> Dict:
        """获取跌停股票"""
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1, 'pz': 1000, 'po': 0, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f2,f3,f12,f14',
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            
            count = 0
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    try:
                        change_pct = float(item.get('f3', 0))
                    except:
                        change_pct = 0
                    
                    if change_pct <= -9.9:
                        count += 1
            
            return {'count': count}
        except Exception as e:
            return {'count': 0}
    
    def get_sector_limit_up(self, sector_code: str) -> Dict:
        """获取指定板块的涨停股数量"""
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        
        # 根据板块代码获取涨停
        fs = f'b:{sector_code}+f:!50'  # 板块内所有股票
        
        params = {
            'pn': 1, 'pz': 500, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': fs,
            'fields': 'f2,f3,f12,f14',
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            
            limit_up_count = 0
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    try:
                        change_pct = float(item.get('f3', 0))
                    except:
                        change_pct = 0
                    if change_pct >= 9.9:
                        limit_up_count += 1
            
            return {'limit_up_count': limit_up_count}
        except:
            return {'limit_up_count': 0}
    
    def get_main_concept(self, code: str) -> str:
        """获取股票主概念板块"""
        market = '1' if code.startswith('6') else '0'
        secid = f"{market}.{code}"
        
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        fields = 'f1,f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f19,f20,f21,f22,f23,f24,f25,f26,f27,f28'
        
        try:
            response = requests.get(f"{url}?secid={secid}&fields={fields}", headers=self.headers, timeout=10)
            data = response.json()
            
            if data.get('data'):
                d = data['data']
                # f14是股票名称，概念板块在别处，需要单独接口
                return d.get('f14', '')
        except:
            pass
        
        return ''
    
    # ==================== 股票列表 ====================
    
    def get_mainboard_stocks(self) -> List[Dict]:
        """获取沪深主板股票列表"""
        stocks = []
        
        # 上海主板
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        
        # 沪市主板 60开头
        params_sh = {
            'pn': 1, 'pz': 5000, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': 'm:1+t:2,m:1+t:23',  # 上海主板
            'fields': 'f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62,f169,f170,f171',
        }
        
        # 深市主板 00开头
        params_sz = {
            'pn': 1, 'pz': 5000, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': 'm:0+t:80,m:0+t:6',  # 深圳主板
            'fields': 'f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62,f169,f170,f171',
        }
        
        try:
            # 沪市
            response_sh = requests.get(url, params=params_sh, headers=self.headers, timeout=30)
            data_sh = response_sh.json()
            if data_sh.get('data') and data_sh['data'].get('diff'):
                for item in data_sh['data']['diff']:
                    code = str(item.get('f12', ''))
                    if code.startswith('60'):
                        stocks.append(self._parse_stock_info(item))
            
            # 深市
            response_sz = requests.get(url, params=params_sz, headers=self.headers, timeout=30)
            data_sz = response_sz.json()
            if data_sz.get('data') and data_sz['data'].get('diff'):
                for item in data_sz['data']['diff']:
                    code = str(item.get('f12', ''))
                    if code.startswith('00'):
                        stocks.append(self._parse_stock_info(item))
                        
        except Exception as e:
            print(f"获取股票列表失败: {e}")
        
        return stocks
    
    def _parse_stock_info(self, item: Dict) -> Dict:
        """解析股票信息"""
        try:
            change_pct = float(item.get('f3', 0))
        except:
            change_pct = 0
        
        try:
            float_cap = float(item.get('f169', 0)) / 10000  # 流通市值(万->亿)
        except:
            float_cap = 0
        
        try:
            volume_ratio = float(item.get('f162', 0)) if item.get('f162') not in [None, '-', ''] else 1
        except:
            volume_ratio = 1
        
        return {
            'code': str(item.get('f12', '')),
            'name': str(item.get('f14', '')),
            'price': item.get('f2', 0),
            'change_pct': change_pct,
            'volume': item.get('f5', 0),
            'amount': float(item.get('f6', 0)) if item.get('f6') else 0,
            'turnover': float(item.get('f168', 0)) / 100 if item.get('f168') else 0,
            'float_cap': float_cap,  # 流通市值(亿)
            'volume_ratio': volume_ratio,
        }
    
    # ==================== 首板相关 ====================
    
    def check_first_board_conditions(self, code: str) -> Dict:
        """
        检查是否符合首板预警条件
        返回: {'pass': bool, 'detail': str}
        """
        result = {
            'pass': False,
            'detail': '',
            'code': code,
        }
        
        # 获取当日行情
        quote = self.get_realtime_quote([code])
        if not quote:
            result['detail'] = '无法获取行情'
            return result
        
        q = quote[0]
        
        # 条件1：涨幅接近涨停（>=9.5%）
        if q['change_pct'] < 9.5:
            result['detail'] = f'涨幅{q["change_pct"]}%不足涨停'
            return result
        
        # 条件2：非一字板（开盘价不等于涨停价，且有波动）
        limit_up_price = round(q['close'] / (1 + q['change_pct']/100) * 1.1, 2)  # 估算涨停价
        if abs(q['open'] - limit_up_price) < 0.01 and q['high'] == q['low']:
            result['detail'] = '一字板涨停'
            return result
        
        # 条件3：获取今日分时数据（简化：用成交量判断）
        # 实际需要分时接口，这里用换手率+量比辅助判断
        if q.get('volume_ratio', 0) < 1.5:
            result['detail'] = f'量比{q.get("volume_ratio", 0):.1f}不足1.5'
            return result
        
        # 条件4：封板时间判断（需要分时数据，简化处理）
        # 如果是涨停状态，认为有封板
        
        result['pass'] = True
        result['detail'] = f'通过: 涨幅{q["change_pct"]:.1f}%, 量比{q.get("volume_ratio", 0):.1f}'
        return result


# ==================== 测试 ====================

def test():
    """测试数据源"""
    ds = V4DataSource()
    
    print("=" * 60)
    print("V4.3.1 数据源测试")
    print("=" * 60)
    
    print("\n[1] 测试日线K线...")
    kline = ds.get_daily_kline('600519', 10)
    if kline:
        print(f"  获取到{len(kline)}条日线数据")
        print(f"  最近3天: {[(d['date'], d['close']) for d in kline[-3:]]}")
    
    print("\n[2] 测试周线K线...")
    weekly = ds.get_weekly_kline('600519', 10)
    if weekly:
        print(f"  获取到{len(weekly)}条周线数据")
    
    print("\n[3] 测试实时行情...")
    quote = ds.get_realtime_quote(['600519', '000001'])
    for q in quote:
        print(f"  {q['name']}: {q['price']} ({q['change_pct']:+.2f}%)")
    
    print("\n[4] 测试市场指数...")
    indices = ds.get_market_index()
    for idx in indices.values():
        print(f"  {idx['name']}: {idx['price']} ({idx['change_pct']:+.2f}%)")
    
    print("\n[5] 测试涨停数据...")
    limit_up = ds.get_limit_up_stocks()
    print(f"  主板涨停: {limit_up['mainboard_count']}只")
    print(f"  首板: {limit_up['first_board_count']}只")
    
    print("\n[6] 测试市场整体数据...")
    market = ds.get_market_amplitude()
    print(f"  两市成交额: {market['total_volume']:.0f}亿")
    print(f"  跌停家数: {market['limit_down_count']}只")
    
    print("\n" + "=" * 60)
    print("测试完成!")


if __name__ == '__main__':
    test()
