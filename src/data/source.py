"""
数据源模块

多源降级链：AkShare → 东方财富直连 → 新浪直连
每层独立 try/except，失败自动降级，不阻断流程。
"""

import time
import logging
import requests
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

from config.settings import DATA_SOURCE, CACHE_DIR

logger = logging.getLogger(__name__)

# 代理设置
PROXY = DATA_SOURCE.get("proxy")
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None


class DataSource:
    """A股数据源，支持多源降级"""

    def __init__(self):
        self.timeout = DATA_SOURCE["request_timeout"]
        self.retry = DATA_SOURCE["request_retry"]

    # ────────────────────────────────────────────
    # 全市场快照（实时行情）
    # ────────────────────────────────────────────
    def get_spot_all(self) -> pd.DataFrame:
        """
        获取全A股实时行情快照

        Returns:
            DataFrame with columns:
            代码, 名称, 最新价, 涨跌幅, 成交量, 成交额,
            换手率, 市盈率-动态, 市净率, 总市值, 流通市值,
            涨速, 5分钟涨跌, 60日涨跌幅, 年初至今涨跌幅
        """
        sources = DATA_SOURCE["sources"]
        last_error = None

        for src in sources:
            try:
                if src == "akshare":
                    return self._spot_akshare()
                elif src == "eastmoney":
                    return self._spot_eastmoney()
                elif src == "sina":
                    return self._spot_sina()
            except Exception as e:
                last_error = e
                logger.warning(f"数据源 {src} 失败: {e}, 尝试降级...")
                continue

        raise RuntimeError(f"所有数据源均失败, 最后错误: {last_error}")

    def _spot_akshare(self) -> pd.DataFrame:
        """AkShare 数据源（基于东方财富接口）"""
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        # 标准化列名
        col_map = {
            "代码": "code", "名称": "name", "最新价": "price",
            "涨跌幅": "change_pct", "成交量": "volume", "成交额": "amount",
            "换手率": "turnover", "市盈率-动态": "pe_ttm",
            "市净率": "pb", "总市值": "total_cap", "流通市值": "float_cap",
            "涨速": "speed", "5分钟涨跌": "change_5min",
            "60日涨跌幅": "change_60d", "年初至今涨跌幅": "change_ytd",
        }
        df = df.rename(columns=col_map)
        logger.info(f"AkShare 快照: {len(df)} 只股票")
        return df

    def _spot_eastmoney(self) -> pd.DataFrame:
        """东方财富直连（备用）"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1, "pz": 100, "po": 1, "np": 1,
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": "m:0 t:6 m:0 t:80 m:1 t:2 m:1 t:23",
            "fields": "f2,f3,f5,f6,f8,f9,f12,f14,f20,f21,f22,f115",
        }
        # 需要分页获取全部
        all_data = []
        page = 1
        while True:
            r = requests.get(url, params={**params, "pn": page},
                             timeout=self.timeout, proxies=PROXIES)
            r.raise_for_status()
            data = r.json().get("data", {})
            items = data.get("diff", [])
            if not items:
                break
            all_data.extend(items)
            page += 1
            if page > 100:  # 安全限制
                break
            time.sleep(0.1)

        df = pd.DataFrame(all_data)
        col_map = {
            "f2": "price", "f3": "change_pct", "f5": "volume",
            "f6": "amount", "f8": "turnover", "f9": "pe_ttm",
            "f12": "code", "f14": "name", "f20": "total_cap",
            "f21": "float_cap", "f115": "pb",
        }
        df = df.rename(columns=col_map)
        return df

    def _spot_sina(self) -> pd.DataFrame:
        """新浪直连（最终备用）"""
        url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
        params = {
            "MarketCenter.getHQNodeData": "hs_a",
            "num": 80, "page": 1,
        }
        all_data = []
        page = 1
        while True:
            r = requests.get(url, params={**params, "page": page},
                             timeout=self.timeout, proxies=PROXIES)
            r.raise_for_status()
            items = r.json()
            if not items:
                break
            all_data.extend(items)
            page += 1
            if page > 100:
                break
            time.sleep(0.1)

        df = pd.DataFrame(all_data)
        col_map = {
            "symbol": "code", "name": "name", "trade": "price",
            "changepercent": "change_pct", "volume": "volume",
            "amount": "amount", "turnoverratio": "turnover",
            "mktcap": "total_cap", "nmc": "float_cap",
        }
        df = df.rename(columns=col_map)
        return df

    # ────────────────────────────────────────────
    # 历史 K 线
    # ────────────────────────────────────────────
    def get_kline(self, code: str, days: int = 250) -> pd.DataFrame:
        """
        获取个股日 K 线（多源降级：AkShare → 东财直连）
        """
        try:
            return self._kline_akshare(code, days)
        except Exception as e:
            logger.warning(f"AkShare K线失败 {code}: {e}, 降级到东财直连...")

        try:
            return self._kline_eastmoney(code, days)
        except Exception as e:
            logger.warning(f"东财K线也失败 {code}: {e}")

        return pd.DataFrame()

    def _kline_akshare(self, code: str, days: int) -> pd.DataFrame:
        """AkShare K线（主源）"""
        import akshare as ak
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date,
            adjust="qfq"
        )
        col_map = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df.tail(days)

    def _kline_eastmoney(self, code: str, days: int) -> pd.DataFrame:
        """东财直连 K 线（备用源）"""
        # 东财 K 线 API
        market = "1" if code.startswith("6") else "0"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": f"{market}.{code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": 101,  # 日线
            "fqt": 1,    # 前复权
            "end": "20500101",
            "lmt": days,
        }
        r = requests.get(url, params=params, timeout=self.timeout, proxies=PROXIES)
        r.raise_for_status()
        data = r.json().get("data", {})
        klines = data.get("klines", [])

        if not klines:
            return pd.DataFrame()

        records = []
        for k in klines:
            parts = k.split(",")
            if len(parts) >= 6:
                records.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(parts[5]) if parts[5] else 0,
                    "amount": 0,
                })

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df.tail(days)

    # ────────────────────────────────────────────
    # 财务数据
    # ────────────────────────────────────────────
    def get_financial_indicator(self, code: str) -> dict:
        """
        获取个股关键财务指标

        Returns:
            dict with keys: roe, revenue_growth, net_profit_growth,
                           gross_margin, debt_ratio
        """
        import akshare as ak
        try:
            # 使用财务摘要接口
            df = ak.stock_financial_abstract(symbol=code)
            if df is None or df.empty:
                return {}

            result = {}
            # 提取关键指标（取最新一期）
            latest = df.iloc[0] if not df.empty else {}

            # 尝试提取 ROE
            for col in df.columns:
                if "净资产收益率" in str(col) or "ROE" in str(col).upper():
                    try:
                        result["roe"] = float(latest.get(col, 0))
                    except:
                        pass
                if "营业收入" in str(col) and "增长" in str(col):
                    try:
                        result["revenue_growth"] = float(latest.get(col, 0))
                    except:
                        pass

            return result
        except Exception as e:
            logger.warning(f"财务指标获取失败 {code}: {e}")
            return {}

    # ────────────────────────────────────────────
    # 资金流
    # ────────────────────────────────────────────
    def get_money_flow(self, code: str, days: int = 5) -> dict:
        """
        获取个股资金流（近 N 日）

        Returns:
            dict with keys: main_net_inflow, main_net_ratio,
                           super_large_net, large_net, medium_net, small_net
        """
        import akshare as ak
        try:
            df = ak.stock_individual_fund_flow(stock=code, market="sh")  # 默认沪市
            if df is None or df.empty:
                return {}

            # 获取前市（沪市/深市判断）
            if code.startswith("6"):
                df = ak.stock_individual_fund_flow(stock=code, market="sh")
            else:
                df = ak.stock_individual_fund_flow(stock=code, market="sz")

            if df is None or df.empty:
                return {}

            # 取最近 N 日汇总
            recent = df.tail(days)
            result = {
                "main_net_inflow": recent.get("主力净流入-净额", pd.Series([0])).sum(),
                "main_net_ratio": recent.get("主力净流入-净占比", pd.Series([0])).sum(),
            }
            return result
        except Exception as e:
            logger.warning(f"资金流获取失败 {code}: {e}")
            return {}

    # ────────────────────────────────────────────
    # 北向资金
    # ────────────────────────────────────────────
    def get_northbound_flow(self) -> dict:
        """获取北向资金净流入"""
        import akshare as ak
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is not None and not df.empty:
                return {
                    "net_inflow": float(df.iloc[-1].get("资金净流入", 0)),
                    "buy_amount": float(df.iloc[-1].get("成交净买额", 0)),
                }
            return {}
        except Exception as e:
            logger.warning(f"北向资金获取失败: {e}")
            return {}

    # ────────────────────────────────────────────
    # 板块数据
    # ────────────────────────────────────────────
    def get_sector_list(self) -> pd.DataFrame:
        """获取板块列表及行情"""
        import akshare as ak
        try:
            df = ak.stock_board_industry_name_em()
            return df
        except Exception as e:
            logger.warning(f"板块列表获取失败: {e}")
            return pd.DataFrame()

    # ────────────────────────────────────────────
    # 大盘指数
    # ────────────────────────────────────────────
    def get_index_kline(self, code: str = "000300", days: int = 250) -> pd.DataFrame:
        """获取指数 K 线"""
        import akshare as ak
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            df = ak.stock_zh_index_daily(
                symbol=f"sh{code}" if code.startswith("000") else f"sh{code}"
            )
            col_map = {
                "date": "date", "open": "open", "close": "close",
                "high": "high", "low": "low", "volume": "volume",
            }
            df = df.rename(columns=col_map)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df.tail(days)
        except Exception as e:
            logger.warning(f"指数K线获取失败 {code}: {e}")
            return pd.DataFrame()


# 全局实例
data_source = DataSource()
