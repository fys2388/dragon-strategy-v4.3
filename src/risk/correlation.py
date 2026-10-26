"""
组合相关性分析模块

功能：
- 计算持仓股票之间的相关性矩阵
- 检测高相关性持仓（避免集中风险）
- 计算组合波动率
- 提供相关性优化建议

用法：
    from src.risk.correlation import CorrelationAnalyzer
    analyzer = CorrelationAnalyzer()
    report = analyzer.analyze(positions)
"""

import logging
from typing import List, Dict, Optional
import numpy as np
import pandas as pd

from src.data.source import data_source

logger = logging.getLogger(__name__)


class CorrelationAnalyzer:
    """组合相关性分析器"""

    def __init__(self, lookback_days: int = 60):
        self.lookback_days = lookback_days
        self.corr_threshold_high = 0.8   # 高相关阈值
        self.corr_threshold_med = 0.6    # 中相关阈值

    def analyze(self, positions: List[Dict]) -> Dict:
        """
        分析组合相关性

        Args:
            positions: 持仓列表，每项包含 code, name

        Returns:
            {
                "correlation_matrix": DataFrame,
                "high_correlations": List[Dict],  # 高相关对
                "medium_correlations": List[Dict],
                "portfolio_volatility": float,
                "industry_concentration": Dict,
                "recommendations": List[str],
            }
        """
        if len(positions) < 2:
            return {
                "correlation_matrix": None,
                "high_correlations": [],
                "medium_correlations": [],
                "portfolio_volatility": 0,
                "recommendations": ["持仓不足2只，无法分析相关性"],
            }

        codes = [p["code"] for p in positions]
        names = [p.get("name", p["code"]) for p in positions]

        # 1. 获取各股票的历史收益率
        returns_dict = {}
        for code in codes:
            try:
                kline = data_source.get_kline(code, days=self.lookback_days)
                if kline is not None and len(kline) > 10:
                    kline["return"] = kline["close"].pct_change().dropna()
                    returns_dict[code] = kline["return"]
            except Exception as e:
                logger.warning(f"获取 {code} 收益率失败: {e}")

        if len(returns_dict) < 2:
            return {
                "correlation_matrix": None,
                "high_correlations": [],
                "medium_correlations": [],
                "portfolio_volatility": 0,
                "recommendations": ["数据不足，无法分析相关性"],
            }

        # 2. 构建收益率矩阵
        returns_df = pd.DataFrame(returns_dict)
        returns_df = returns_df.dropna()

        if len(returns_df) < 20:
            return {
                "correlation_matrix": None,
                "high_correlations": [],
                "medium_correlations": [],
                "portfolio_volatility": 0,
                "recommendations": ["有效数据不足20天，无法分析"],
            }

        # 3. 计算相关性矩阵
        corr_matrix = returns_df.corr()

        # 4. 提取高相关对中低相关对
        high_corrs = []
        medium_corrs = []
        checked = set()

        for i, code1 in enumerate(codes):
            for j, code2 in enumerate(codes):
                if i >= j:
                    continue
                if code1 not in corr_matrix.columns or code2 not in corr_matrix.columns:
                    continue

                key = tuple(sorted([code1, code2]))
                if key in checked:
                    continue
                checked.add(key)

                corr = corr_matrix.loc[code1, code2]
                name1 = names[i] if i < len(names) else code1
                name2 = names[j] if j < len(names) else code2

                if corr >= self.corr_threshold_high:
                    high_corrs.append({
                        "code1": code1, "name1": name1,
                        "code2": code2, "name2": name2,
                        "correlation": round(corr, 2),
                        "level": "high",
                    })
                elif corr >= self.corr_threshold_med:
                    medium_corrs.append({
                        "code1": code1, "name1": name1,
                        "code2": code2, "name2": name2,
                        "correlation": round(corr, 2),
                        "level": "medium",
                    })

        # 5. 计算组合波动率
        # 假设等权重
        weights = np.ones(len(codes)) / len(codes)
        cov_matrix = returns_df.cov().values
        portfolio_var = weights @ cov_matrix @ weights
        portfolio_vol = np.sqrt(portfolio_var) * np.sqrt(250)  # 年化

        # 6. 生成建议
        recommendations = []

        if high_corrs:
            recommendations.append(
                f"⚠️ {len(high_corrs)} 对高相关持仓（≥{self.corr_threshold_high}），"
                f"建议减仓或替换以降低集中风险"
            )
            for hc in high_corrs:
                recommendations.append(
                    f"   {hc['name1']} ↔ {hc['name2']}: 相关系数 {hc['correlation']:.2f}"
                )

        if medium_corrs:
            recommendations.append(
                f"⚡ {len(medium_corrs)} 对中相关持仓（≥{self.corr_threshold_med}），"
                f"建议关注但无需立即调整"
            )

        if not high_corrs and not medium_corrs:
            recommendations.append("✅ 持仓相关性良好，无明显集中风险")

        if portfolio_vol > 0.5:
            recommendations.append(f"⚠️ 组合年化波动率 {portfolio_vol*100:.1f}%，偏高")
        elif portfolio_vol > 0.3:
            recommendations.append(f"⚡ 组合年化波动率 {portfolio_vol*100:.1f}%，中等")
        else:
            recommendations.append(f"✅ 组合年化波动率 {portfolio_vol*100:.1f}%，可控")

        return {
            "correlation_matrix": corr_matrix,
            "high_correlations": high_corrs,
            "medium_correlations": medium_corrs,
            "portfolio_volatility": round(float(portfolio_vol), 4),
            "portfolio_vol_pct": round(float(portfolio_vol) * 100, 2),
            "recommendations": recommendations,
            "lookback_days": self.lookback_days,
            "stock_count": len(codes),
        }

    def check_before_add(self, new_code: str, positions: List[Dict]) -> Dict:
        """
        添加持仓前的相关性检查

        Returns:
            {
                "should_add": bool,
                "warnings": List[str],
                "correlations": Dict[str, float],
            }
        """
        if not positions:
            return {"should_add": True, "warnings": [], "correlations": {}}

        try:
            new_kline = data_source.get_kline(new_code, days=self.lookback_days)
            if new_kline is None or len(new_kline) < 10:
                return {"should_add": True, "warnings": ["新股票数据不足"], "correlations": {}}

            new_kline["return"] = new_kline["close"].pct_change().dropna()
            new_returns = new_kline["return"]

            warnings = []
            correlations = {}

            for pos in positions:
                pos_code = pos["code"]
                try:
                    pos_kline = data_source.get_kline(pos_code, days=self.lookback_days)
                    if pos_kline is None or len(pos_kline) < 10:
                        continue

                    pos_kline["return"] = pos_kline["close"].pct_change().dropna()
                    pos_returns = pos_kline["return"]

                    # 对齐日期
                    combined = pd.DataFrame({
                        "new": new_returns,
                        "pos": pos_returns,
                    }).dropna()

                    if len(combined) < 20:
                        continue

                    corr = combined["new"].corr(combined["pos"])
                    correlations[pos_code] = round(corr, 2)

                    if corr >= self.corr_threshold_high:
                        warnings.append(
                            f"⚠️ 与 {pos.get('name', pos_code)} 高相关 ({corr:.2f})，"
                            f"建议避免同时持有"
                        )
                    elif corr >= self.corr_threshold_med:
                        warnings.append(
                            f"⚡ 与 {pos.get('name', pos_code)} 中相关 ({corr:.2f})，"
                            f"注意风险集中"
                        )

                except Exception as e:
                    logger.warning(f"计算相关性失败 {pos_code}: {e}")

            should_add = len([w for w in warnings if "高相关" in w]) == 0

            return {
                "should_add": should_add,
                "warnings": warnings,
                "correlations": correlations,
            }

        except Exception as e:
            logger.error(f"相关性检查失败: {e}")
            return {"should_add": True, "warnings": [f"检查失败: {e}"], "correlations": {}}


# 全局实例
correlation_analyzer = CorrelationAnalyzer()
