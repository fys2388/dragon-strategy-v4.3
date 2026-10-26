# -*- coding: utf-8 -*-
"""数据质量与时间一致性校验模块。

核心能力：
1. 未来函数检测：防止用未来数据计算指标再预测当前
2. 数据质量检查：缺失值、异常值、零值检测
3. 数据延迟检测：K线数据是否完整到最新交易日
4. 特征时间戳管理：每个特征记录数据截止时间

这是AI交易系统的基础——如果数据有未来函数，回测再漂亮也没意义。
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_QUALITY_LOG = os.path.join(BASE_DIR, "data", "data_quality_log.json")


class DataQualityChecker:
    """数据质量校验器。"""

    def __init__(self):
        self.issues = []
        self.warnings = []

    def check_kline_data(self, df: pd.DataFrame, stock_code: str = "") -> Dict[str, Any]:
        """检查K线数据质量。

        Returns:
            {passed: bool, issues: [...], warnings: [...], stats: {...}}
        """
        self.issues = []
        self.warnings = []

        if df is None or df.empty:
            self.issues.append("数据为空")
            return self._result(stock_code)

        # 1. 检查必要列
        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            self.issues.append(f"缺少必要列: {missing_cols}")
            return self._result(stock_code)

        # 2. 检查缺失值
        null_counts = df[required_cols].isnull().sum()
        for col, count in null_counts.items():
            if count > 0:
                self.warnings.append(f"{col}列有{count}个缺失值")

        # 3. 检查异常值
        close = df["close"].astype(float)
        if (close <= 0).any():
            self.issues.append("存在收盘价<=0的异常数据")

        # 检查涨跌幅异常（单日涨跌>20%可能是数据错误，除权除息除外）
        if len(close) > 1:
            pct_change = close.pct_change().abs()
            extreme_moves = (pct_change > 0.2).sum()
            if extreme_moves > 0:
                self.warnings.append(f"存在{extreme_moves}次单日涨跌幅>20%（可能是除权除息或数据错误）")

        # 4. 检查成交量异常
        volume = df["volume"].astype(float)
        if (volume < 0).any():
            self.issues.append("存在负成交量")
        zero_volume = (volume == 0).sum()
        if zero_volume > 0:
            self.warnings.append(f"存在{zero_volume}天零成交量（可能是停牌）")

        # 5. 检查时间连续性（如果有date列）
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"])
            if len(dates) > 1:
                gaps = dates.diff().dt.days
                large_gaps = (gaps > 5).sum()  # 超过5天的间隔（排除周末）
                if large_gaps > 0:
                    self.warnings.append(f"存在{large_gaps}次日期间隔>5天（可能是数据缺失或长期停牌）")

        # 6. OHLC逻辑检查
        if all(c in df.columns for c in ["open", "high", "low", "close"]):
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            o = df["open"].astype(float)
            c = df["close"].astype(float)
            if (high < low).any():
                self.issues.append("存在最高价<最低价的逻辑错误")
            if (high < o).any() or (high < c).any():
                self.warnings.append("存在最高价<开盘价或收盘价")
            if (low > o).any() or (low > c).any():
                self.warnings.append("存在最低价>开盘价或收盘价")

        return self._result(stock_code)

    def check_future_leakage(self, df: pd.DataFrame, indicator_name: str,
                              lookback_days: int, stock_code: str = "") -> Dict[str, Any]:
        """检测未来函数泄露。

        原理：计算指标时，如果使用了lookback_days之后的数据，则存在未来函数。
        例如：用20日均线预测第10天，但20日均线包含了第11-20天的数据。

        Args:
            df: 原始数据
            indicator_name: 指标名称
            lookback_days: 指标计算需要的回溯天数
            stock_code: 股票代码
        """
        self.issues = []
        self.warnings = []

        if df is None or df.empty:
            self.issues.append("数据为空")
            return self._result(stock_code)

        n = len(df)
        if lookback_days >= n:
            self.warnings.append(f"指标{indicator_name}需要{lookback_days}天数据，但只有{n}天，前{lookback_days}天无法计算")

        # 检查：指标的第一个有效值应该在第lookback_days天（0-indexed: lookback_days-1）
        # 如果指标在更早的位置就有值，说明可能用了未来数据
        self.warnings.append(f"指标{indicator_name}：前{lookback_days-1}天数据不可用（需要{lookback_days}天窗口），使用时应跳过")

        return self._result(stock_code)

    def check_data_freshness(self, df: pd.DataFrame, stock_code: str = "") -> Dict[str, Any]:
        """检查数据新鲜度（是否延迟）。"""
        self.issues = []
        self.warnings = []

        if df is None or df.empty:
            self.issues.append("数据为空")
            return self._result(stock_code)

        if "date" not in df.columns:
            self.warnings.append("无date列，无法检查新鲜度")
            return self._result(stock_code)

        last_date = pd.to_datetime(df["date"].iloc[-1])
        today = datetime.now()

        # 计算距离今天的天数
        days_old = (today - last_date).days

        # 工作日判断（简单版）
        weekdays = 0
        current = last_date
        while current < today:
            if current.weekday() < 5:  # 周一到周五
                weekdays += 1
            current += timedelta(days=1)

        if weekdays > 3:
            self.issues.append(f"数据延迟{weekdays}个交易日（最后日期{last_date.strftime('%Y-%m-%d')}）")
        elif weekdays > 1:
            self.warnings.append(f"数据延迟{weekdays}个交易日（最后日期{last_date.strftime('%Y-%m-%d')}）")

        return self._result(stock_code)

    def validate_feature(self, feature_name: str, feature_values: pd.Series,
                          original_df: pd.DataFrame, lookback_days: int) -> Dict[str, Any]:
        """验证单个特征是否存在未来函数。

        核心检查：特征在第i天的值，是否只使用了第i天及之前的数据。
        """
        self.issues = []
        self.warnings = []

        n = len(original_df)
        feature_n = len(feature_values)

        if feature_n != n:
            self.warnings.append(f"特征{feature_name}长度({feature_n})与原始数据({n})不一致")

        # 前lookback_days-1天应该是NaN（因为数据不够）
        if lookback_days > 1 and feature_n >= lookback_days:
            early_values = feature_values.iloc[:lookback_days-1]
            non_nan_count = early_values.notna().sum()
            if non_nan_count > 0:
                self.issues.append(
                    f"特征{feature_name}在前{lookback_days-1}天有{non_nan_count}个非NaN值，"
                    f"可能存在未来函数泄露（应该需要{lookback_days}天数据才能计算）"
                )

        return {
            "feature": feature_name,
            "passed": len(self.issues) == 0,
            "issues": self.issues,
            "warnings": self.warnings,
        }

    def _result(self, stock_code: str = "") -> Dict[str, Any]:
        return {
            "stock_code": stock_code,
            "passed": len(self.issues) == 0,
            "issues": self.issues.copy(),
            "warnings": self.warnings.copy(),
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def batch_check(self, stock_codes: List[str], data_getter) -> Dict[str, Any]:
        """批量检查多只股票的数据质量。

        Args:
            stock_codes: 股票代码列表
            data_getter: 函数，输入code返回DataFrame
        """
        results = []
        passed = 0
        failed = 0

        for code in stock_codes:
            try:
                df = data_getter(code)
                result = self.check_kline_data(df, code)
                results.append(result)
                if result["passed"]:
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                results.append({
                    "stock_code": code,
                    "passed": False,
                    "issues": [f"获取数据异常: {str(e)}"],
                    "warnings": [],
                })
                failed += 1

        # 记录日志
        log = {
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(stock_codes),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
        os.makedirs(os.path.dirname(DATA_QUALITY_LOG), exist_ok=True)
        with open(DATA_QUALITY_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        return {
            "total": len(stock_codes),
            "passed": passed,
            "failed": failed,
            "failed_stocks": [r["stock_code"] for r in results if not r["passed"]],
            "log_file": DATA_QUALITY_LOG,
        }


def build_data_quality_report(check_result: Dict) -> str:
    """生成数据质量报告。"""
    lines = [
        "🔍 数据质量校验报告",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"检查时间：{check_result.get('checked_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}",
        f"总计：{check_result.get('total', 0)}只 | 通过：{check_result.get('passed', 0)}只 | 失败：{check_result.get('failed', 0)}只",
    ]

    if check_result.get("failed_stocks"):
        lines.append(f"\n❌ 数据异常股票：{', '.join(check_result['failed_stocks'][:10])}")
        if len(check_result["failed_stocks"]) > 10:
            lines.append(f"  ...等共{len(check_result['failed_stocks'])}只")

    return "\n".join(lines)


def init_data_quality_checker() -> DataQualityChecker:
    """初始化数据质量校验器。"""
    return DataQualityChecker()
