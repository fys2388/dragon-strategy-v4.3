"""
数据校验模块

功能：
- 校验行情数据完整性（缺失值、异常值）
- 校验K线数据（日期连续性、价格合理性）
- 校验快照数据（市值、换手率范围）
- 生成数据质量报告

用法：
    from src.data.validator import DataValidator
    validator = DataValidator()
    report = validator.validate_spot(spot_df)
    report = validator.validate_kline(kline_df, code)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataValidator:
    """数据校验器"""

    # 合理范围定义
    PRICE_RANGE = (1, 10000)        # 股价范围
    TURNOVER_RANGE = (0, 100)       # 换手率范围（%）
    PE_RANGE = (0, 500)             # 市盈率范围
    PB_RANGE = (0, 100)             # 市净率范围
    MARKET_CAP_MIN = 1e8            # 最小市值（1亿）
    VOLUME_MIN = 0                  # 最小成交量
    VOLUME_MAX_RATIO = 100          # 单日最大成交量倍数（相对5日均量）

    def __init__(self):
        self.stats = {
            "validated": 0,
            "errors": 0,
            "warnings": 0,
        }

    def validate_spot(self, spot_df: pd.DataFrame) -> Dict:
        """
        校验快照数据

        Args:
            spot_df: 快照 DataFrame

        Returns:
            校验报告
        """
        report = {
            "type": "spot",
            "total_rows": len(spot_df),
            "errors": [],
            "warnings": [],
            "quality_score": 100,
        }

        if spot_df is None or spot_df.empty:
            report["errors"].append("数据为空")
            report["quality_score"] = 0
            return report

        # 1. 缺失值检查
        null_counts = spot_df.isnull().sum()
        null_cols = null_counts[null_counts > 0]
        if len(null_cols) > 0:
            for col, count in null_cols.items():
                pct = count / len(spot_df) * 100
                if pct > 10:
                    report["errors"].append(f"{col}: {pct:.1f}% 缺失 ({count}行)")
                    report["quality_score"] -= 10
                else:
                    report["warnings"].append(f"{col}: {pct:.1f}% 缺失 ({count}行)")
                    report["quality_score"] -= 2

        # 2. 股价异常检查
        if "price" in spot_df.columns:
            invalid_price = (spot_df["price"] < self.PRICE_RANGE[0]) | (spot_df["price"] > self.PRICE_RANGE[1])
            invalid_count = invalid_price.sum()
            if invalid_count > 0:
                report["warnings"].append(f"股价异常: {invalid_count} 只 (范围 {self.PRICE_RANGE})")
                report["quality_score"] -= 5

            # 检查零价格
            zero_price = (spot_df["price"] <= 0).sum()
            if zero_price > 0:
                report["errors"].append(f"零/负价格: {zero_price} 只")
                report["quality_score"] -= 20

        # 3. 换手率异常检查
        if "turnover" in spot_df.columns:
            invalid_turnover = (spot_df["turnover"] < 0) | (spot_df["turnover"] > 100)
            invalid_count = invalid_turnover.sum()
            if invalid_count > 0:
                report["warnings"].append(f"换手率异常: {invalid_count} 只")
                report["quality_score"] -= 3

        # 4. 市值检查
        if "total_cap" in spot_df.columns:
            small_cap = (spot_df["total_cap"] < self.MARKET_CAP_MIN).sum()
            if small_cap > 0:
                report["warnings"].append(f"小市值股票: {small_cap} 只 (< 1亿)")

        # 5. 数据量检查
        if len(spot_df) < 100:
            report["errors"].append(f"数据量过少: {len(spot_df)} 只 (预期 > 3000)")
            report["quality_score"] -= 30

        report["errors"].append(f"总错误: {len(report['errors'])}")
        report["warnings"].append(f"总警告: {len(report['warnings'])}")
        report["quality_score"] = max(0, min(100, report["quality_score"]))

        self.stats["validated"] += 1
        self.stats["errors"] += len(report["errors"])
        self.stats["warnings"] += len(report["warnings"])

        return report

    def validate_kline(self, kline_df: pd.DataFrame, code: str) -> Dict:
        """
        校验K线数据

        Args:
            kline_df: K线 DataFrame
            code: 股票代码

        Returns:
            校验报告
        """
        report = {
            "type": "kline",
            "code": code,
            "total_days": len(kline_df),
            "errors": [],
            "warnings": [],
            "quality_score": 100,
        }

        if kline_df is None or kline_df.empty:
            report["errors"].append("数据为空")
            report["quality_score"] = 0
            return report

        # 1. 日期检查
        if "date" in kline_df.columns:
            dates = kline_df["date"].sort_values()
            if len(dates) > 1:
                # 检查日期连续性
                date_diffs = dates.diff().dropna()
                gaps = date_diffs[date_diffs > pd.Timedelta(days=7)]
                if len(gaps) > 0:
                    report["warnings"].append(f"日期断档: {len(gaps)} 处")
                    report["quality_score"] -= 5

                # 检查未来日期
                future_dates = dates[dates > datetime.now()]
                if len(future_dates) > 0:
                    report["errors"].append(f"未来日期: {len(future_dates)} 条")
                    report["quality_score"] -= 20

        # 2. OHLC 一致性检查
        if all(col in kline_df.columns for col in ["open", "high", "low", "close"]):
            # high >= max(open, close)
            invalid_high = (kline_df["high"] < kline_df[["open", "close"]].max(axis=1)).sum()
            if invalid_high > 0:
                report["errors"].append(f"high < max(open,close): {invalid_high} 条")
                report["quality_score"] -= 10

            # low <= min(open, close)
            invalid_low = (kline_df["low"] > kline_df[["open", "close"]].min(axis=1)).sum()
            if invalid_low > 0:
                report["errors"].append(f"low > min(open,close): {invalid_low} 条")
                report["quality_score"] -= 10

        # 3. 价格异常检查
        if "close" in kline_df.columns:
            invalid_price = (kline_df["close"] < 1) | (kline_df["close"] > 10000)
            invalid_count = invalid_price.sum()
            if invalid_count > 0:
                report["warnings"].append(f"收盘价异常: {invalid_count} 条")
                report["quality_score"] -= 5

            zero_price = (kline_df["close"] <= 0).sum()
            if zero_price > 0:
                report["errors"].append(f"零/负收盘价: {zero_price} 条")
                report["quality_score"] -= 20

        # 4. 成交量检查
        if "volume" in kline_df.columns:
            zero_volume = (kline_df["volume"] <= 0).sum()
            if zero_volume > 0:
                report["warnings"].append(f"零成交量: {zero_volume} 条")

        # 5. 涨跌幅检查
        if "close" in kline_df.columns and len(kline_df) > 1:
            returns = kline_df["close"].pct_change().dropna()
            extreme_returns = (returns.abs() > 0.2).sum()  # 单日涨跌 > 20%
            if extreme_returns > 0:
                report["warnings"].append(f"极端涨跌幅: {extreme_returns} 条 (>20%)")

        report["quality_score"] = max(0, min(100, report["quality_score"]))

        self.stats["validated"] += 1
        self.stats["errors"] += len(report["errors"])
        self.stats["warnings"] += len(report["warnings"])

        return report

    def validate_signal(self, signal: Dict) -> Dict:
        """
        校验信号数据

        Args:
            signal: 信号字典

        Returns:
            校验报告
        """
        report = {
            "type": "signal",
            "code": signal.get("code", ""),
            "errors": [],
            "warnings": [],
            "valid": True,
        }

        # 必填字段检查
        required_fields = ["code", "name", "entry_price", "signal_type"]
        for field in required_fields:
            if field not in signal or signal[field] is None:
                report["errors"].append(f"缺少必填字段: {field}")
                report["valid"] = False

        # 价格检查
        entry_price = signal.get("entry_price", 0)
        if entry_price <= 0:
            report["errors"].append(f"入场价异常: {entry_price}")
            report["valid"] = False

        # 止损检查
        stop_loss = signal.get("stop_loss", 0)
        if stop_loss > 0 and stop_loss >= entry_price:
            report["errors"].append(f"止损价 >= 入场价: {stop_loss} >= {entry_price}")
            report["valid"] = False

        # 目标价检查
        target_1 = signal.get("target_1", 0)
        if target_1 > 0 and target_1 <= entry_price:
            report["warnings"].append(f"目标1 <= 入场价: {target_1} <= {entry_price}")

        target_2 = signal.get("target_2", 0)
        if target_2 > 0 and target_2 <= entry_price:
            report["warnings"].append(f"目标2 <= 入场价: {target_2} <= {entry_price}")

        # 盈亏比检查
        if stop_loss > 0 and target_1 > 0:
            risk = entry_price - stop_loss
            reward = target_1 - entry_price
            if risk > 0 and reward > 0:
                ratio = reward / risk
                if ratio < 1.5:
                    report["warnings"].append(f"盈亏比偏低: {ratio:.2f}")

        report["valid"] = len(report["errors"]) == 0
        self.stats["validated"] += 1

        return report

    def get_summary(self) -> Dict:
        """获取校验统计摘要"""
        return self.stats.copy()

    def validate_all(self, spot_df: pd.DataFrame, 
                     klines: Dict[str, pd.DataFrame] = None,
                     signals: List[Dict] = None) -> Dict:
        """
        批量校验所有数据

        Returns:
            综合校验报告
        """
        results = {}

        # 校验快照
        results["spot"] = self.validate_spot(spot_df)

        # 校验K线
        if klines:
            results["klines"] = {}
            for code, kline_df in klines.items():
                results["klines"][code] = self.validate_kline(kline_df, code)

        # 校验信号
        if signals:
            results["signals"] = []
            for sig in signals:
                results["signals"].append(self.validate_signal(sig))

        # 综合评分
        all_scores = [results["spot"]["quality_score"]]
        if "klines" in results:
            all_scores.extend([r["quality_score"] for r in results["klines"].values()])

        avg_score = np.mean(all_scores) if all_scores else 0

        return {
            "overall_score": round(avg_score, 1),
            "spot": results["spot"],
            "klines": results.get("klines", {}),
            "signals": results.get("signals", []),
            "stats": self.get_summary(),
        }


# 全局实例
validator = DataValidator()
