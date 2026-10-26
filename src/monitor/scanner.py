"""
选股扫描器（编排层）

编排完整选股流程：
1. 刷新数据快照
2. 初筛 → 精筛
3. 信号检测 + 打分排序
4. 大盘闸门评估
5. 仓位计算
6. 生成报告 + 推送
"""

import logging
import json
from datetime import datetime
from typing import List, Dict, Optional

from config.settings import DATA_DIR, REPORT_DIR, USER_PROFILE
from src.data.source import data_source
from src.data.cache import cache
from src.pool.universe import universe
from src.signals.entry import signal_detector
from src.risk.market_gate import market_gate
from src.risk.position import position_manager
from src.risk.performance_tracker import get_tracker
from src.notify.feishu import feishu

logger = logging.getLogger(__name__)


class StockScanner:
    """选股扫描器"""

    def __init__(self, push_feishu: bool = True):
        self.push_feishu = push_feishu
        self.current_date = datetime.now().strftime("%Y-%m-%d")

    def run_premarket(self, push: bool = None) -> Dict:
        """
        盘前选股流程

        Returns:
            完整结果 dict
        """
        push = self.push_feishu if push is None else push

        logger.info("=" * 60)
        logger.info(f"盘前选股开始 - {self.current_date}")
        logger.info("=" * 60)

        result = {
            "date": self.current_date,
            "timestamp": datetime.now().isoformat(),
            "steps": {},
            "errors": [],
        }

        try:
            # Step 1: 大盘闸门
            logger.info("Step 1: 大盘闸门评估...")
            gate_result = market_gate.evaluate()
            result["market_gate"] = gate_result
            result["steps"]["market_gate"] = "ok"

            # 如果大盘极弱，直接空仓观望
            if gate_result["level"] == "closed":
                logger.info("大盘极弱，建议空仓观望，跳过选股")
                result["signals"] = []
                result["summary"] = "大盘极弱，建议空仓观望"
                if push:
                    feishu.send_simple(
                        f"📊 {self.current_date} 大盘评估：{gate_result['summary']}\n"
                        f"建议：空仓观望，今日不操作"
                    )
                return result

            # Step 2: 选股池
            logger.info("Step 2: 选股池筛选...")
            candidates = universe.run_pipeline()
            result["steps"]["universe"] = "ok"
            result["candidate_count"] = len(candidates)

            if candidates.empty:
                result["signals"] = []
                result["summary"] = "今日无符合条件的候选标的"
                if push:
                    feishu.send_simple(f"📊 {self.current_date} 今日无符合条件的候选标的")
                return result

            # Step 3: 信号检测
            logger.info("Step 3: 信号检测...")
            signals = signal_detector.detect_all(candidates)
            result["steps"]["signals"] = "ok"
            result["signals"] = signals

            # 按大盘环境过滤信号数量
            max_signals = self._max_signals_by_gate(gate_result["level"])
            signals = signals[:max_signals]
            result["signals"] = signals

            # Step 4: 仓位计算
            logger.info("Step 4: 仓位计算...")
            positions = []
            for sig in signals:
                pos_info = position_manager.calculate_position_size(
                    sig,
                    current_positions=len(position_manager.positions)
                )
                sig["position_plan"] = pos_info
                positions.append(pos_info)
            result["positions"] = positions
            result["steps"]["position"] = "ok"

            # Step 5: 生成摘要
            result["summary"] = self._build_summary(gate_result, signals)

            # Step 6: 推送
            if push and signals:
                feishu.send_premarket(self.current_date, gate_result, signals)

            # 保存结果
            self._save_result(result)

            # 记录绩效追踪
            self._record_performance(result, gate_result, signals)

            logger.info(f"盘前选股完成: {len(signals)} 只推荐")
            return result

        except Exception as e:
            logger.error(f"选股流程异常: {e}", exc_info=True)
            result["errors"].append(str(e))
            result["status"] = "error"
            return result

    def _max_signals_by_gate(self, level: str) -> int:
        """根据大盘环境限制推荐数量"""
        return {
            "strong": 10,
            "normal": 7,
            "weak": 4,
            "closed": 0,
        }.get(level, 5)

    def _build_summary(self, gate_result: Dict, signals: List[Dict]) -> str:
        """生成摘要"""
        parts = [
            f"🏛️ 大盘：{gate_result['summary']}",
            f"📊 推荐：{len(signals)} 只",
        ]
        if signals:
            top = signals[0]
            parts.append(f"🏆 首选：{top['name']} ({top['code']}) - {top['signal_desc']}，评分{top.get('score', 0):.0f}")
        return "\n".join(parts)

    def _save_result(self, result: Dict):
        """保存选股结果"""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = REPORT_DIR / f"premarket_{self.current_date}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"选股结果已保存: {output_path}")

    def _record_performance(self, result: Dict, gate_result: Dict, signals: List[Dict]):
        """记录绩效追踪"""
        try:
            tracker = get_tracker()
            portfolio = position_manager.get_positions_summary()
            total_equity = portfolio.get("total_value", 0) or USER_PROFILE["capital"]
            tracker.record_daily({
                "date": self.current_date,
                "total_equity": total_equity,
                "total_positions": portfolio.get("total_positions", 0),
                "total_cost": portfolio.get("total_cost", 0),
                "total_pnl": portfolio.get("total_pnl", 0),
                "total_pnl_pct": portfolio.get("total_pnl_pct", 0),
                "market_gate_level": gate_result.get("level", "unknown"),
                "market_gate_score": gate_result.get("score", 0),
                "new_signals": signals,
                "closed_trades": [],
                "holdings": position_manager.positions,
            })
        except Exception as e:
            logger.warning(f"绩效记录失败: {e}")

    # ────────────────────────────────────────────
    # 盘中预警
    # ────────────────────────────────────────────
    def run_intraday_alerts(self, push: bool = None) -> List[Dict]:
        """
        盘中持仓异动预警

        Returns:
            预警列表
        """
        push = self.push_feishu if push is None else push
        alerts = []

        # 获取当前持仓
        positions = position_manager.positions
        if not positions:
            logger.info("无持仓，跳过盘中预警")
            return []

        logger.info(f"盘中预警检查: {len(positions)} 只持仓")

        # 获取实时行情
        spot = cache.get("spot_all", ttl=1800)  # 缓存 30 分钟
        if spot is None:
            spot = data_source.get_spot_all()
            cache.set("spot_all", spot)

        for pos in positions:
            code = pos["code"]
            cost_price = pos.get("cost_price", 0)
            entry_price = pos.get("entry_price", 0)
            stop_loss = pos.get("stop_loss", 0)
            target_1 = pos.get("target_1", 0)

            # 获取实时价格
            row = spot[spot["code"] == code] if spot is not None else None
            if row is None or row.empty:
                continue

            current_price = row.iloc[0].get("price", 0)
            change_pct = row.iloc[0].get("change_pct", 0)

            if current_price <= 0:
                continue

            # 计算持仓盈亏
            if cost_price > 0:
                pnl_pct = (current_price - cost_price) / cost_price * 100
            else:
                pnl_pct = 0

            # 检查止损
            if stop_loss > 0 and current_price <= stop_loss:
                alerts.append({
                    "code": code,
                    "name": pos.get("name", code),
                    "alert_type": "⚠️ 止损触发",
                    "detail": f"当前价{current_price:.2f} ≤ 止损{stop_loss:.2f}",
                    "current_price": current_price,
                    "cost_price": cost_price,
                    "pnl_pct": pnl_pct,
                    "change_pct": change_pct,
                })
                continue

            # 检查止盈
            if target_1 > 0 and current_price >= target_1:
                alerts.append({
                    "code": code,
                    "name": pos.get("name", code),
                    "alert_type": "🎯 第一止盈",
                    "detail": f"当前价{current_price:.2f} ≥ 目标{target_1:.2f}，建议减半",
                    "current_price": current_price,
                    "cost_price": cost_price,
                    "pnl_pct": pnl_pct,
                    "change_pct": change_pct,
                })
                continue

            # 检查急跌（日内跌幅 > 5%）
            if change_pct < -5:
                alerts.append({
                    "code": code,
                    "name": pos.get("name", code),
                    "alert_type": "📉 急跌预警",
                    "detail": f"日内跌幅{change_pct:.1f}%，注意风险控制",
                    "current_price": current_price,
                    "cost_price": cost_price,
                    "pnl_pct": pnl_pct,
                    "change_pct": change_pct,
                })
                continue

            # 检查急拉（日内涨幅 > 5%）
            if change_pct > 5:
                alerts.append({
                    "code": code,
                    "name": pos.get("name", code),
                    "alert_type": "📈 急拉预警",
                    "detail": f"日内涨幅{change_pct:.1f}%，可考虑止盈",
                    "current_price": current_price,
                    "cost_price": cost_price,
                    "pnl_pct": pnl_pct,
                    "change_pct": change_pct,
                })

        # 推送
        if push and alerts:
            feishu.send_alert(alerts)

        logger.info(f"盘中预警完成: {len(alerts)} 条预警")
        return alerts

    # ────────────────────────────────────────────
    # 盘后复盘
    # ────────────────────────────────────────────
    def run_review(self, push: bool = None) -> Dict:
        """
        盘后复盘

        Returns:
            复盘结果
        """
        push = self.push_feishu if push is None else push

        logger.info("=" * 60)
        logger.info(f"盘后复盘 - {self.current_date}")
        logger.info("=" * 60)

        result = {
            "date": self.current_date,
            "timestamp": datetime.now().isoformat(),
        }

        # 1. 持仓表现
        portfolio = position_manager.get_positions_summary()
        result["portfolio"] = portfolio

        # 2. 大盘环境
        gate_result = market_gate.evaluate()
        result["market_gate"] = gate_result

        # 3. 明日关注（今天有信号但未买的 + 已持仓次日跟踪）
        tomorrow_watchlist = []

        # 已持仓的次日跟踪
        for pos in position_manager.positions:
            tomorrow_watchlist.append({
                "code": pos["code"],
                "name": pos.get("name", pos["code"]),
                "reason": f"已持仓，成本{pos.get('cost_price', 0):.2f}，目标{pos.get('target_1', 0):.2f}",
            })

        result["tomorrow_watchlist"] = tomorrow_watchlist

        # 推送
        if push:
            feishu.send_review(self.current_date, result)

        # 保存
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = REPORT_DIR / f"review_{self.current_date}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        logger.info("盘后复盘完成")
        return result


# 全局实例
scanner = StockScanner()
