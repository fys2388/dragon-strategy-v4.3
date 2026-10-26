"""
飞书推送模块

支持：
- 文本消息
- 富文本消息（post）
- 卡片消息（interactive）

消息格式统一封装，避免重复代码。
"""

import logging
import json
import requests
from datetime import datetime
from typing import Optional, List, Dict

from config.settings import FEISHU

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """飞书机器人推送"""

    def __init__(self, webhook_url: str = None):
        self.enabled = FEISHU["enabled"]
        self.webhook_url = webhook_url or FEISHU["webhook_url"]

        if not self.webhook_url:
            logger.warning("飞书 webhook 未配置，推送将禁用")
            self.enabled = False

    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        if not self.enabled:
            logger.info(f"[飞书禁用] {text[:50]}...")
            return False

        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }
        return self._send(payload)

    def send_post(self, title: str, content_blocks: List[Dict]) -> bool:
        """
        发送富文本消息

        Args:
            title: 消息标题
            content_blocks: 内容块列表，每项包含 tag/text 等
        """
        if not self.enabled:
            logger.info(f"[飞书禁用] 富文本: {title}")
            return False

        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": content_blocks,
                    }
                }
            },
        }
        return self._send(payload)

    def send_card(self, card_data: Dict) -> bool:
        """发送卡片消息"""
        if not self.enabled:
            logger.info(f"[飞书禁用] 卡片消息")
            return False

        payload = {
            "msg_type": "interactive",
            "card": card_data,
        }
        return self._send(payload)

    def _send(self, payload: Dict) -> bool:
        """发送消息到飞书"""
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info(f"飞书推送成功")
                return True
            else:
                logger.warning(f"飞书推送失败: {result}")
                return False

        except Exception as e:
            logger.warning(f"飞书推送异常: {e}")
            return False

    # ────────────────────────────────────────────
    # 业务封装
    # ────────────────────────────────────────────
    def send_premarket(self, date: str, market_gate_result: Dict, signals: List[Dict]) -> bool:
        """
        发送盘前选股报告

        Args:
            date: 日期
            market_gate_result: 大盘闸门结果
            signals: 信号列表
        """
        title = f"📊 【{date} 中线波段选股推荐】"

        # 大盘环境
        blocks = []
        blocks.append([
            {"tag": "text", "text": f"🏛️ 大盘环境：{market_gate_result['summary']}"}
        ])
        blocks.append([
            {"tag": "text", "text": f"📊 推荐标的：{len(signals)} 只"}
        ])
        blocks.append([
            {"tag": "text", "text": "────────────────"}
        ])

        # 个股推荐
        for i, sig in enumerate(signals[:10]):  # 最多 10 只
            strength = sig.get("signal_strength", "strong")
            strength_label = {"strong": "✅", "weak": "⚡", "watch": "👀"}.get(strength, "")
            batch = [
                {"tag": "text", "text": f"📌 {i+1}. {sig['name']} ({sig['code']}) {strength_label}"},
                {"tag": "text", "text": f"   买点：{sig['signal_desc']} | 入场：{sig['entry_price']:.2f}元"},
                {"tag": "text", "text": f"   止损：{sig.get('stop_loss', 0):.2f}元 ({sig.get('stop_loss_pct', -7):.1f}%)"},
                {"tag": "text", "text": f"   目标：{sig.get('target_1', 0):.2f} (+{sig.get('target_1_pct', 15):.0f}%) / {sig.get('target_2', 0):.2f} (+{sig.get('target_2_pct', 25):.0f}%)"},
                {"tag": "text", "text": f"   评分：{sig.get('score', 0):.0f} | {sig['reason']}"},
            ]
            blocks.append(batch)
            if i < min(len(signals), 10) - 1:
                blocks.append([
                    {"tag": "text", "text": "────────────────"}
                ])

        # 风险提示
        blocks.append([
            {"tag": "text", "text": "⚠️ 风险提示：以上仅为技术面分析，不构成投资建议。请结合大盘环境和自身风险承受能力操作。"}
        ])

        return self.send_post(title, blocks)

    def send_alert(self, alerts: List[Dict]) -> bool:
        """发送盘中异动预警"""
        if not alerts:
            return False

        date = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"🚨 【{date} 盘中异动预警】"

        blocks = []
        for alert in alerts:
            blocks.append([
                {"tag": "text", "text": f"🔔 {alert['name']} ({alert['code']})"},
                {"tag": "text", "text": f"   {alert['alert_type']}: {alert['detail']}"},
                {"tag": "text", "text": f"   当前价：{alert.get('current_price', 'N/A')} | 持仓成本：{alert.get('cost_price', 'N/A')}"},
            ])
            blocks.append([{"tag": "text", "text": "────────────────"}])

        return self.send_post(title, blocks)

    def send_review(self, date: str, review_data: Dict) -> bool:
        """发送盘后复盘报告"""
        title = f"📋 【{date} 盘后复盘】"

        blocks = []
        # 组合表现
        portfolio = review_data.get("portfolio", {})
        blocks.append([
            {"tag": "text", "text": f"💼 持仓：{portfolio.get('total_positions', 0)} 只"},
            {"tag": "text", "text": f"💰 总成本：{portfolio.get('total_cost', 0):,.0f}元"},
            {"tag": "text", "text": f"📈 总市值：{portfolio.get('total_value', 0):,.0f}元"},
            {"tag": "text", "text": f"📊 总盈亏：{portfolio.get('total_pnl', 0):,.0f}元 ({portfolio.get('total_pnl_pct', 0):+.2f}%)"},
        ])
        blocks.append([{"tag": "text", "text": "────────────────"}])

        # 大盘环境
        gate = review_data.get("market_gate", {})
        if gate:
            blocks.append([
                {"tag": "text", "text": f"🏛️ 大盘：{gate.get('summary', 'N/A')}"}
            ])
            blocks.append([{"tag": "text", "text": "────────────────"}])

        # 明日关注
        tomorrow = review_data.get("tomorrow_watchlist", [])
        if tomorrow:
            blocks.append([
                {"tag": "text", "text": f"👀 明日关注：{len(tomorrow)} 只"}
            ])
            for stock in tomorrow[:5]:
                blocks.append([
                    {"tag": "text", "text": f"   • {stock['name']} ({stock['code']}): {stock.get('reason', '')}"}
                ])
            blocks.append([{"tag": "text", "text": "────────────────"}])

        # 风险提示
        blocks.append([
            {"tag": "text", "text": "⚠️ 复盘仅供参考，不构成投资建议。"}
        ])

        return self.send_post(title, blocks)

    def send_simple(self, text: str) -> bool:
        """发送简单文本（调试用）"""
        return self.send_text(text)


# 全局实例
feishu = FeishuNotifier()
