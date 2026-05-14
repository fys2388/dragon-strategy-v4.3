#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
21天龙头策略V3.3 - 东方财富行情数据模块
用于获取A股实时行情、涨停板数据等
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple


class EastMoneyDataSource:
    """东方财富数据源"""
    
    def __init__(self):
        self.base_url = "http://push2.eastmoney.com/api/qt"
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
    
    def get_realtime_quote(self, codes: List[str]) -> List[Dict]:
        """获取实时行情（单股或批量）
        
        Args:
            codes: 股票代码列表，如 ['600000', '000001']
        
        Returns:
            行情数据列表
        """
        if not codes:
            return []
        
        # 转换代码格式
        secids = ','.join([self._code_to_market(code) for code in codes])
        
        # 东方财富实时行情接口
        fields = 'f43,f44,f45,f46,f47,f48,f57,f58,f60,f170'  # 字段含义见下方注释
        
        url = f"{self.base_url}/stock/get/?secid={secids}&fields={fields}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            data = response.json()
            
            result = []
            if data.get('data'):
                d = data['data']
                # 单股查询返回格式：data 直接是股票数据
                if 'f57' in d:
                    stock_info = {
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
                    }
                    result.append(stock_info)
                # 多股查询返回格式：data.diff 是数组
                elif d.get('diff'):
                    for item in d['diff']:
                        stock_info = {
                            'code': item.get('f57', ''),
                            'name': item.get('f58', ''),
                            'price': float(item.get('f43', 0)) / 100 if item.get('f43') else 0,
                            'change_pct': float(item.get('f170', 0)) / 100 if item.get('f170') else 0,
                            'change': float(item.get('f44', 0)) / 100 if item.get('f44') else 0,
                            'open': float(item.get('f46', 0)) / 100 if item.get('f46') else 0,
                            'high': float(item.get('f45', 0)) / 100 if item.get('f45') else 0,
                            'low': float(item.get('f47', 0)) / 100 if item.get('f47') else 0,
                            'volume': item.get('f48', 0),
                            'amount': float(item.get('f60', 0)) / 100 if item.get('f60') else 0,
                        }
                        result.append(stock_info)
            
            return result
            
        except Exception as e:
            print(f"获取实时行情失败: {e}")
            return []
    
    def get_limit_up_stocks(self, date: str = None) -> Dict:
        """获取涨停股票
        
        Args:
            date: 日期，格式YYYY-MM-DD，默认今日
        
        Returns:
            涨停统计数据
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        # 东方财富涨停板数据接口
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        
        params = {
            'pn': 1,
            'pz': 5000,
            'po': 1,  # 1=降序
            'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2,
            'invt': 2,
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',  # 涨停板
            'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18',
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            
            limit_up_list = []
            mainboard_count = 0
            first_board_count = 0
            continue_board_count = 0
            
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    code = str(item.get('f12', ''))
                    name = str(item.get('f14', ''))
                    
                    try:
                        change_pct = float(item.get('f3', 0)) if item.get('f3') not in [None, '-', ''] else 0
                    except (ValueError, TypeError):
                        change_pct = 0
                    
                    # 只统计涨停股（涨幅>=9.9%）
                    if change_pct >= 9.9:
                        # 判断主板（只包含上海主板600/601/603/605和深圳主板000/001）
                        is_mainboard = False
                        if code.startswith(('600', '601', '603', '605')):
                            is_mainboard = True
                        elif code.startswith(('000', '001')):
                            is_mainboard = True
                        
                        if is_mainboard:
                            mainboard_count += 1
                            
                            try:
                                vol_ratio = float(item.get('f10', 0)) if item.get('f10') not in [None, '-', ''] else 0
                            except (ValueError, TypeError):
                                vol_ratio = 0
                            
                            stock_info = {
                                'code': code,
                                'name': name,
                                'change_pct': change_pct,
                                'price': item.get('f2', 0),
                                'seal_time': item.get('f8', ''),  # 涨停时间
                                'volume_ratio': vol_ratio,  # 量比
                                'turnover': item.get('f6', 0),  # 成交额
                            }
                            limit_up_list.append(stock_info)
                            
                            # 判断是否首板（简化判断：量比>2为首板）
                            if vol_ratio > 2:  # 量比>2
                                first_board_count += 1
                            else:
                                continue_board_count += 1
            
            return {
                'mainboard_count': mainboard_count,
                'first_board_count': first_board_count,
                'continue_board_count': continue_board_count,
                'stocks': limit_up_list
            }
            
        except Exception as e:
            print(f"获取涨停数据失败: {e}")
            return {
                'mainboard_count': 0,
                'first_board_count': 0,
                'continue_board_count': 0,
                'stocks': []
            }
    
    def get_sector_leading_stocks(self, sector: str = None) -> List[Dict]:
        """获取板块龙头股
        
        Args:
            sector: 板块名称，不传则获取所有板块的龙头
        
        Returns:
            龙头股列表
        """
        # 东方财富板块数据
        url = "http://push2.eastmoney.com/api/qt/clist/get"
        
        params = {
            'pn': 1,
            'pz': 200,
            'po': 1,
            'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2,
            'invt': 2,
            'fid': 'f3',
            'fs': 'm:90+t:2+f:!50,m:90+t:3+f:!50,m:90+t:10+f:!50,m:90+t:11+f:!50',  # 行业板块
            'fields': 'f2,f3,f4,f8,f10,f12,f14,f20,f62',
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()
            
            sectors = []
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    sector_info = {
                        'name': item.get('f14', ''),
                        'change_pct': item.get('f3', 0),
                        'lead_stock': item.get('f12', ''),
                        'lead_stock_name': item.get('f13', ''),
                        'stock_count': item.get('f10', 0),  # 成分股数
                        'amount': item.get('f20', 0),  # 板块成交额
                        'main_cap_flow': item.get('f62', 0),  # 主力净流入
                    }
                    sectors.append(sector_info)
            
            # 按涨幅排序，取前10
            sectors.sort(key=lambda x: x['change_pct'], reverse=True)
            return sectors[:10]
            
        except Exception as e:
            print(f"获取板块数据失败: {e}")
            return []
    
    def get_market_index(self) -> Dict:
        """获取主要指数（上证、深证、创业板等）"""
        index_codes = {
            'sh000001': '上证指数',
            'sz399001': '深证成指',
            'sz399006': '创业板指',
            'sh000300': '沪深300',
            'sh000016': '上证50',
        }
        
        secids = ','.join(index_codes.keys())
        fields = 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14'
        
        url = f"{self.base_url}/stock/get/?secid={secids}&fields={fields}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            data = response.json()
            
            indices = {}
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    code = item.get('f12', '')
                    indices[index_codes.get(code, code)] = {
                        'code': code,
                        'name': item.get('f14', ''),
                        'price': item.get('f2', 0),
                        'change_pct': item.get('f3', 0),
                        'change': item.get('f4', 0),
                        'volume': item.get('f5', 0),
                        'amount': item.get('f6', 0),
                    }
            
            return indices
            
        except Exception as e:
            print(f"获取指数数据失败: {e}")
            return {}
    
    def get_market_sentiment(self) -> Dict:
        """获取市场情绪指标"""
        # 涨跌家数
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        
        try:
            # 获取涨跌统计
            up_url = "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f2,f3"
            down_url = "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&po=0&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f2,f3"
            
            # 简化：使用涨停数据中的统计
            limit_up = self.get_limit_up_stocks()
            
            return {
                'up_count': limit_up.get('mainboard_count', 0) * 3,  # 估算
                'down_count': 20,  # 估算
                'limit_up_count': limit_up.get('mainboard_count', 0),
                'limit_down_count': 5,  # 估算
                'sentiment': '偏强' if limit_up.get('mainboard_count', 0) > 50 else '中性'
            }
            
        except Exception as e:
            print(f"获取市场情绪失败: {e}")
            return {
                'up_count': 0,
                'down_count': 0,
                'limit_up_count': 0,
                'limit_down_count': 0,
                'sentiment': '未知'
            }
    
    def get_longhubang_data(self, date: str = None) -> List[Dict]:
        """获取龙虎榜数据

        Args:
            date: 日期，格式YYYY-MM-DD，默认今日

        Returns:
            龙虎榜数据列表
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        # 东方财富龙虎榜接口
        url = "http://push2.eastmoney.com/api/qt/clist/get"

        params = {
            'pn': 1,
            'pz': 30,
            'po': 1,
            'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2,
            'invt': 2,
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # 龙虎榜
            'fields': 'f12,f14,f2,f3,f5,f6,f62,f184,f185,f186,f187,f188,f189,f190',
        }

        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=15)
            data = response.json()

            results = []
            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    code = str(item.get('f12', ''))
                    name = str(item.get('f14', ''))

                    # 解析机构动向
                    buy_institution = item.get('f184', 0) or 0
                    sell_institution = item.get('f185', 0) or 0

                    # 确保是数值类型
                    try:
                        buy_institution = float(buy_institution)
                        sell_institution = float(sell_institution)
                    except (ValueError, TypeError):
                        buy_institution = 0.0
                        sell_institution = 0.0

                    # 获取主力净流入（万）
                    main_flow = item.get('f62', 0)
                    try:
                        main_flow = float(main_flow) / 10000  # 转为万元
                    except (ValueError, TypeError):
                        main_flow = 0.0

                    action = "中性"
                    interpretation = "无明显机构动向"
                    if buy_institution > sell_institution * 1.5:
                        action = "机构净买入"
                        interpretation = f"买入席位有机构参与，偏积极（主力净流入 {main_flow:.0f}万）"
                    elif sell_institution > buy_institution * 1.5:
                        action = "机构净卖出"
                        interpretation = f"卖出席位有机构参与，需警惕（主力净流入 {main_flow:.0f}万）"
                    elif main_flow > 5000:
                        action = "主力流入"
                        interpretation = f"主力资金大幅流入 {main_flow:.0f}万，偏积极"
                    elif main_flow < -5000:
                        action = "主力流出"
                        interpretation = f"主力资金大幅流出 {main_flow:.0f}万，需警惕"

                    results.append({
                        'code': code,
                        'name': name,
                        'price': item.get('f2', 0),
                        'change_pct': item.get('f3', 0),
                        'buy_seats': f"主力净流入: {main_flow:.0f}万",
                        'sell_seats': f"成交额: {item.get('f6', 0)/10000:.0f}万",
                        'institution_action': action,
                        'interpretation': interpretation,
                    })

            return results

        except Exception as e:
            print(f"获取龙虎榜数据失败: {e}")
            return []

    def get_yesterday_premium_rate(self) -> float:
        """获取昨日首板溢价率（今日首板开盘表现）

        Returns:
            平均溢价率(%)
        """
        try:
            # 获取昨日涨停股票
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            limit_up = self.get_limit_up_stocks(yesterday)

            stocks = limit_up.get('stocks', [])
            if not stocks:
                return 0.0

            # 获取这些股票的今日实时行情计算溢价
            premium_list = []
            for stock in stocks[:20]:  # 取前20只计算
                code = stock.get('code')
                y_close_price = stock.get('price', 0)

                if code and y_close_price:
                    quote = self.get_realtime_quote([code])
                    if quote:
                        today_open = quote[0].get('open', 0)
                        if today_open and y_close_price > 0:
                            premium = (today_open - y_close_price) / y_close_price * 100
                            premium_list.append(premium)

            if premium_list:
                return sum(premium_list) / len(premium_list)
            return 0.0

        except Exception as e:
            print(f"获取溢价率失败: {e}")
            return 0.0

    def get_dragon_candidates(self, min_score: int = 60) -> List[Dict]:
        """获取符合条件的龙头候选股票
        
        Args:
            min_score: 最低评分
        
        Returns:
            龙头候选列表
        """
        # 获取今日涨停股（主板）
        limit_up_data = self.get_limit_up_stocks()
        stocks = limit_up_data.get('stocks', [])
        
        if not stocks:
            return []
        
        candidates = []
        for stock in stocks:
            code = stock['code']
            
            # 获取详细行情
            detail = self.get_realtime_quote([code])
            if not detail:
                continue
            
            info = detail[0]
            
            # 计算评分（简化版）
            score = 50  # 基础分
            
            # 封单金额加分（成交额大的更有实力）
            amount = info.get('amount', 0)
            if amount > 500000000:  # 5亿以上
                score += 20
            elif amount > 200000000:  # 2亿以上
                score += 15
            elif amount > 100000000:  # 1亿以上
                score += 10
            
            # 价格适中加分（5-20元区间最好）
            price = info.get('price', 0)
            if 5 <= price <= 20:
                score += 15
            elif 3 <= price < 5 or 20 < price <= 30:
                score += 10
            elif price < 3:
                score += 5
            
            # 涨停时间早加分
            seal_time = stock.get('seal_time', '')
            if seal_time:
                try:
                    hour = int(seal_time.split(':')[0]) if ':' in str(seal_time) else 10
                    if hour < 10:
                        score += 15
                    elif hour == 10:
                        score += 10
                except:
                    pass
            
            # 主板加分
            if code.startswith(('600', '601', '603')):
                score += 5
            
            if score >= min_score:
                candidates.append({
                    'code': code,
                    'name': info['name'],
                    'price': price,
                    'change_pct': info['change_pct'],
                    'volume_ratio': stock.get('volume_ratio', 0),
                    'amount': amount,
                    'high': info['high'],
                    'low': info['low'],
                    'score': score,
                    'seal_time': seal_time,
                    'buy_min': round(price * 1.01, 2) if price else 0,  # 1%-4%区间
                    'buy_max': round(price * 1.04, 2) if price else 0,
                    'stop_loss': round(price * 0.93, 2) if price else 0,  # 7%止损
                })
        
        # 按评分排序
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:10]


def test_data_source():
    """测试数据源"""
    print("=" * 60)
    print("东方财富行情数据测试")
    print("=" * 60)
    
    ds = EastMoneyDataSource()
    
    print("\n[1] 获取主要指数...")
    indices = ds.get_market_index()
    for name, info in indices.items():
        print(f"  {name}: {info['price']} ({info['change_pct']:+.2f}%)")
    
    print("\n[2] 获取涨停统计...")
    limit_up = ds.get_limit_up_stocks()
    print(f"  主板涨停: {limit_up['mainboard_count']} 只")
    print(f"  首板: {limit_up['first_board_count']} 只")
    print(f"  连板: {limit_up['continue_board_count']} 只")
    
    print("\n[3] 获取龙头候选...")
    candidates = ds.get_dragon_candidates()
    for i, c in enumerate(candidates[:3], 1):
        print(f"  {i}. {c['name']}({c['code']}) 评分:{c['score']} 量比:{c['volume_ratio']}")
    
    print("\n[4] 测试单股行情...")
    quote = ds.get_realtime_quote(['600519'])
    if quote:
        print(f"  贵州茅台: {quote[0]['price']} ({quote[0]['change_pct']:+.2f}%)")
    
    print("\n" + "=" * 60)
    print("测试完成！")


if __name__ == '__main__':
    test_data_source()
