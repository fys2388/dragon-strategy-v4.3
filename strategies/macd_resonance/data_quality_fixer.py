# -*- coding: utf-8 -*-
"""数据质量自动修复与自学习模块。

功能：
1. 自动检测和修复API数据异常（单位错误、负数、异常值）
2. 记录修复历史，持续学习优化
3. 数据质量评分，异常数据标记

修复规则（持续学习进化）：
- 东财f162(PE)字段单位0.01，需除以100
- 负债率<0标记为异常，显示为"异常"
- PE>1000或PE<-1000标记为异常
- 毛利率>100或<-100标记为异常
- 主力净流入单位：元→亿，需除以1e8
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

# 修复历史记录文件
FIX_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "data_quality_fixes.json"
)


class DataQualityFixer:
    """数据质量自动修复器。"""

    def __init__(self):
        self.fix_history = self._load_fix_history()
        self.fix_count = {"total": 0, "by_type": {}}

    def _load_fix_history(self) -> Dict:
        """加载修复历史。"""
        if os.path.exists(FIX_LOG_FILE):
            try:
                with open(FIX_LOG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"fixes": [], "stats": {}}
        return {"fixes": [], "stats": {}}

    def _save_fix_history(self):
        """保存修复历史。"""
        try:
            os.makedirs(os.path.dirname(FIX_LOG_FILE), exist_ok=True)
            with open(FIX_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.fix_history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _record_fix(self, field: str, original: Any, fixed: Any, reason: str):
        """记录一次修复。"""
        self.fix_count["total"] += 1
        self.fix_count["by_type"][field] = self.fix_count["by_type"].get(field, 0) + 1

        fix_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "field": field,
            "original": original,
            "fixed": fixed,
            "reason": reason,
        }
        self.fix_history["fixes"].append(fix_entry)
        # 只保留最近1000条
        if len(self.fix_history["fixes"]) > 1000:
            self.fix_history["fixes"] = self.fix_history["fixes"][-1000:]

        # 更新统计
        self.fix_history["stats"] = {
            "total_fixes": self.fix_history.get("stats", {}).get("total_fixes", 0) + 1,
            "last_fix_time": fix_entry["time"],
            "by_type": self.fix_count["by_type"],
        }

    def fix_fundamental(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """修复基本面数据。

        Args:
            data: 原始基本面数据

        Returns:
            修复后的数据，新增_data_quality字段
        """
        fixed = dict(data)
        issues = []

        # 1. PE修复：东财f162单位0.01，除以100
        pe = fixed.get("pe", 0)
        if pe and isinstance(pe, (int, float)):
            if abs(pe) > 100:
                original_pe = pe
                fixed["pe"] = round(pe / 100, 2)
                issues.append(f"PE单位修复: {original_pe}→{fixed['pe']}")
                self._record_fix("pe", original_pe, fixed["pe"], "东财f162单位0.01，除以100")
            # 异常PE标记
            if fixed["pe"] > 500 or fixed["pe"] < -500:
                issues.append(f"PE异常: {fixed['pe']}")
                fixed["pe_abnormal"] = True

        # 2. PB修复：通常不需要，但检查异常值
        pb = fixed.get("pb", 0)
        if pb and isinstance(pb, (int, float)):
            if pb > 100:
                issues.append(f"PB异常: {pb}")
                fixed["pb_abnormal"] = True

        # 3. ROE修复：检查异常值
        roe = fixed.get("roe", 0)
        if roe and isinstance(roe, (int, float)):
            if abs(roe) > 100:
                original_roe = roe
                fixed["roe"] = round(roe / 100, 2) if abs(roe) > 1000 else roe
                issues.append(f"ROE异常: {original_roe}→{fixed['roe']}")
                self._record_fix("roe", original_roe, fixed["roe"], "ROE超过100%，可能单位错误")

        # 4. 毛利率修复：检查范围
        gm = fixed.get("gross_margin", 0)
        if gm and isinstance(gm, (int, float)):
            if gm > 100 or gm < -100:
                original_gm = gm
                fixed["gross_margin"] = round(gm / 100, 2) if abs(gm) > 1000 else gm
                issues.append(f"毛利率异常: {original_gm}→{fixed['gross_margin']}")
                self._record_fix("gross_margin", original_gm, fixed["gross_margin"], "毛利率超出合理范围")

        # 5. 负债率修复：不能为负
        dr = fixed.get("debt_ratio", 0)
        if dr and isinstance(dr, (int, float)):
            if dr < 0:
                original_dr = dr
                fixed["debt_ratio"] = 0  # 负数负债率标记为0
                fixed["debt_ratio_abnormal"] = True
                issues.append(f"负债率为负: {original_dr}→0(异常)")
                self._record_fix("debt_ratio", original_dr, 0, "负债率不能为负，标记异常")
            elif dr > 100:
                original_dr = dr
                fixed["debt_ratio"] = round(dr / 100, 2) if dr > 1000 else dr
                issues.append(f"负债率异常: {original_dr}→{fixed['debt_ratio']}")
                self._record_fix("debt_ratio", original_dr, fixed["debt_ratio"], "负债率超过100%，可能单位错误")

        # 6. 营收增速修复：检查异常值
        rg = fixed.get("revenue_growth", 0)
        if rg and isinstance(rg, (int, float)):
            if abs(rg) > 1000:
                original_rg = rg
                fixed["revenue_growth"] = round(rg / 100, 2)
                issues.append(f"营收增速异常: {original_rg}→{fixed['revenue_growth']}")
                self._record_fix("revenue_growth", original_rg, fixed["revenue_growth"], "营收增速超过1000%，可能单位错误")

        # 添加数据质量标记
        fixed["_data_quality"] = {
            "issues": issues,
            "issue_count": len(issues),
            "is_clean": len(issues) == 0,
        }

        return fixed

    def fix_sector_inflow(self, inflow_yuan: float) -> float:
        """修复板块主力净流入单位：元→亿。

        Args:
            inflow_yuan: 原始净流入（元）

        Returns:
            净流入（亿元）
        """
        if not inflow_yuan or not isinstance(inflow_yuan, (int, float)):
            return 0
        # 东财f62单位是元，转换为亿
        result = round(inflow_yuan / 100000000, 2)
        if abs(result) > 10000:
            # 异常大的值，可能已经是万元，再除10000
            result = round(result / 10000, 2)
            self._record_fix("sector_inflow", inflow_yuan, result, "净流入异常大，二次单位转换")
        return result

    def fix_moneyflow(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """修复资金流数据。"""
        fixed = dict(data)
        issues = []

        # 主力净流入：元→万元
        for field in ["main_net_inflow", "small_net_inflow", "medium_net_inflow",
                      "large_net_inflow", "super_large_net_inflow"]:
            val = fixed.get(field, 0)
            if val and isinstance(val, (int, float)):
                if abs(val) > 1000000:  # 超过100万，说明单位是元
                    fixed[field] = round(val / 10000, 2)
                    issues.append(f"{field}单位修复: 元→万元")

        fixed["_data_quality"] = {
            "issues": issues,
            "issue_count": len(issues),
            "is_clean": len(issues) == 0,
        }
        return fixed

    def get_fix_stats(self) -> Dict:
        """获取修复统计。"""
        return {
            "total_fixes": self.fix_count["total"],
            "by_type": self.fix_count["by_type"],
            "history_count": len(self.fix_history.get("fixes", [])),
            "last_fix": self.fix_history.get("stats", {}).get("last_fix_time", "无"),
        }

    def save_and_report(self) -> str:
        """保存修复历史并生成报告。"""
        self._save_fix_history()
        stats = self.get_fix_stats()
        if stats["total_fixes"] > 0:
            lines = [f"🔧 数据质量自动修复报告"]
            lines.append(f"  本次修复: {stats['total_fixes']}处")
            for ftype, count in stats["by_type"].items():
                lines.append(f"    - {ftype}: {count}处")
            lines.append(f"  历史累计: {stats['history_count']}处")
            return "\n".join(lines)
        return ""


# 全局单例
_fixer = None


def get_fixer() -> DataQualityFixer:
    """获取全局修复器实例。"""
    global _fixer
    if _fixer is None:
        _fixer = DataQualityFixer()
    return _fixer
