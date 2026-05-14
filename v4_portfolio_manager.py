"""
V4.3.1 持仓管理器
记录持仓标的，追踪买卖记录，实时监控卖出信号
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

# ============================================================
# 数据结构
# ============================================================
@dataclass
class Position:
    """持仓标的"""
    code: str          # 股票代码
    name: str          # 股票名称
    path: str          # 路径A或B
    pattern: str       # 周线形态
    entry_date: str    # 买入日期
    entry_price: float # 买入价格
    quantity: int      # 买入数量
    stop_loss: float   # 止损价
    phase1_target: float = 0.0  # 第一止盈目标价（+15%）
    phase2_target: float = 0.0  # 第二止盈目标价（+30%）
    phase3_target: float = 0.0  # 第三止盈目标价（+50%）
    peak_price: float = 0.0     # 阶段最高价
    notes: str = ""             # 备注
    
    def current_profit_pct(self, current_price: float) -> float:
        """计算当前盈利百分比"""
        return (current_price - self.entry_price) / self.entry_price * 100
    
    def update_peak(self, current_price: float):
        """更新阶段最高价"""
        if current_price > self.peak_price:
            self.peak_price = current_price
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TradeRecord:
    """交易记录"""
    date: str
    code: str
    name: str
    action: str  # BUY / SELL
    price: float
    quantity: int
    reason: str
    profit_pct: float = 0.0


# ============================================================
# 持仓管理器
# ============================================================
class PortfolioManager:
    """持仓管理器"""
    
    DATA_FILE = "dragon-strategy-v3.8/portfolio_data.json"
    
    def __init__(self, data_dir: str = "."):
        self.data_file = os.path.join(data_dir, self.DATA_FILE)
        self.positions: List[Position] = []
        self.trade_history: List[TradeRecord] = []
        self.load()
    
    def load(self):
        """从文件加载持仓数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.positions = [Position(**p) for p in data.get('positions', [])]
                    self.trade_history = [TradeRecord(**t) for t in data.get('history', [])]
            except Exception as e:
                print(f"⚠️ 加载持仓数据失败: {e}")
                self.positions = []
                self.trade_history = []
    
    def save(self):
        """保存持仓数据到文件"""
        try:
            data = {
                'positions': [p.to_dict() for p in self.positions],
                'history': [asdict(t) for t in self.trade_history]
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存持仓数据失败: {e}")
    
    def add_position(self, position: Position):
        """
        添加新持仓
        自动计算止盈目标价和止损价
        """
        # 计算止盈目标
        position.phase1_target = round(position.entry_price * 1.15, 2)   # +15%
        position.phase2_target = round(position.entry_price * 1.30, 2)   # +30%
        position.phase3_target = round(position.entry_price * 1.50, 2)   # +50%
        
        # 计算止损价（买入价的-7%）
        position.stop_loss = round(position.entry_price * 0.93, 2)
        
        # 初始化阶段最高价
        position.peak_price = position.entry_price
        
        self.positions.append(position)
        
        # 记录买入
        self.trade_history.append(TradeRecord(
            date=datetime.now().strftime('%Y-%m-%d'),
            code=position.code,
            name=position.name,
            action='BUY',
            price=position.entry_price,
            quantity=position.quantity,
            reason=f"路径{position.path} {position.pattern}"
        ))
        
        self.save()
        print(f"✅ 已添加持仓: {position.code} {position.name}")
        print(f"   买入价: {position.entry_price} | 数量: {position.quantity}股")
        print(f"   止损价: {position.stop_loss} | 目标价: {position.phase1_target}/{position.phase2_target}/{position.phase3_target}")
    
    def remove_position(self, code: str, reason: str, sell_price: float = 0):
        """
        移除持仓（卖出）
        """
        position = self.get_position(code)
        if not position:
            print(f"⚠️ 未找到持仓: {code}")
            return
        
        # 计算盈利
        profit_pct = (sell_price - position.entry_price) / position.entry_price * 100
        
        # 记录卖出
        self.trade_history.append(TradeRecord(
            date=datetime.now().strftime('%Y-%m-%d'),
            code=position.code,
            name=position.name,
            action='SELL',
            price=sell_price,
            quantity=position.quantity,
            reason=reason,
            profit_pct=profit_pct
        ))
        
        # 从持仓列表移除
        self.positions = [p for p in self.positions if p.code != code]
        
        self.save()
        print(f"✅ 已卖出持仓: {position.code} {position.name}")
        print(f"   卖出价: {sell_price} | 盈亏: {profit_pct:+.2f}%")
        print(f"   原因: {reason}")
    
    def get_position(self, code: str) -> Optional[Position]:
        """获取指定持仓"""
        for p in self.positions:
            if p.code == code:
                return p
        return None
    
    def get_all_positions(self) -> List[Position]:
        """获取所有持仓"""
        return self.positions.copy()
    
    def update_peak_prices(self, prices: Dict[str, float]):
        """
        更新所有持仓的阶段最高价
        prices: {code: current_price}
        """
        for position in self.positions:
            if position.code in prices:
                position.update_peak(prices[position.code])
        self.save()
    
    def get_trade_history(self) -> List[TradeRecord]:
        """获取交易历史"""
        return self.trade_history.copy()
    
    def get_performance_stats(self) -> Dict:
        """获取绩效统计"""
        if not self.trade_history:
            return {'total_trades': 0, 'win_rate': 0, 'avg_profit': 0}
        
        sells = [t for t in self.trade_history if t.action == 'SELL']
        if not sells:
            return {'total_trades': 0, 'win_rate': 0, 'avg_profit': 0}
        
        wins = [t for t in sells if t.profit_pct > 0]
        return {
            'total_trades': len(sells),
            'win_count': len(wins),
            'win_rate': len(wins) / len(sells) * 100,
            'avg_profit': sum(t.profit_pct for t in sells) / len(sells),
            'max_profit': max(t.profit_pct for t in sells) if sells else 0,
            'min_profit': min(t.profit_pct for t in sells) if sells else 0
        }
    
    def format_status(self) -> str:
        """格式化持仓状态报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("📊 V4.3.1 持仓状态报告")
        lines.append(f"⏰ 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 60)
        
        if not self.positions:
            lines.append("\n📭 当前无持仓")
        else:
            lines.append(f"\n📦 持仓数量: {len(self.positions)}只")
            lines.append("-" * 60)
            
            for p in self.positions:
                lines.append(f"\n【{p.code} {p.name}】")
                lines.append(f"  路径: {p.path} | 形态: {p.pattern}")
                lines.append(f"  买入: {p.entry_date} @ {p.entry_price}")
                lines.append(f"  止损: {p.stop_loss} | 阶段最高: {p.peak_price}")
                lines.append(f"  止盈: +15%→{p.phase1_target} | +30%→{p.phase2_target} | +50%→{p.phase3_target}")
        
        # 绩效统计
        stats = self.get_performance_stats()
        if stats['total_trades'] > 0:
            lines.append("\n" + "-" * 60)
            lines.append("📈 历史绩效:")
            lines.append(f"  总交易次数: {stats['total_trades']}")
            lines.append(f"  胜率: {stats['win_rate']:.1f}%")
            lines.append(f"  平均盈亏: {stats['avg_profit']:+.2f}%")
            lines.append(f"  最大盈利: {stats['max_profit']:+.2f}%")
            lines.append(f"  最大亏损: {stats['min_profit']:+.2f}%")
        
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ============================================================
# 卖出信号检查器
# ============================================================
class ExitSignalChecker:
    """卖出信号检查器"""
    
    @staticmethod
    def check_exit_signals(position: Position, current_price: float, 
                          weekly_data: List[Dict], sector_limit_down: bool = False) -> List[Dict]:
        """
        检查持仓是否触发卖出信号
        返回: [{'type': signal_type, 'severity': 'hard'/'soft', 'message': str, 'action': str}]
        """
        signals = []
        
        # ========== 硬性止损信号 ==========
        
        # 1. 周线收盘价跌破5周均线，且本周最低价低于上周最低价
        if len(weekly_data) >= 2:
            current_week = weekly_data[-1]
            prev_week = weekly_data[-2]
            
            if (current_week['close'] < current_week.get('ma5', current_week['close']) and
                current_week['low'] < prev_week['low']):
                signals.append({
                    'type': '周线破位',
                    'severity': 'hard',
                    'message': f"周线收盘{current_week['close']}跌破5周线，且低于上周最低{prev_week['low']}",
                    'action': '立即清仓'
                })
        
        # 2. 单日跌幅≥7%，且收盘价跌破60日均线
        daily_data = [d for d in weekly_data if d.get('is_daily')]  # 需要日线数据
        if daily_data:
            latest_daily = daily_data[-1]
            ma60 = sum(d['close'] for d in daily_data[-60:]) / 60
            
            if (latest_daily['close'] < position.entry_price * 0.93 and  # 跌幅≥7%
                latest_daily['close'] < ma60):
                signals.append({
                    'type': '放量破60日线',
                    'severity': 'hard',
                    'message': f"单日跌幅超7%，且收盘{latest_daily['close']}跌破60日线{ma60:.2f}",
                    'action': '立即清仓'
                })
        
        # 3. 连续3日收盘价低于5日均线，且累计跌幅≥10%
        if daily_data and len(daily_data) >= 3:
            closes_5d = [d['close'] for d in daily_data[-5:]]
            ma5 = sum(closes_5d) / 5
            
            below_ma5_days = 0
            total_drop = 0
            for d in daily_data[-3:]:
                if d['close'] < ma5:
                    below_ma5_days += 1
                    total_drop = (d['close'] - position.entry_price) / position.entry_price * 100
            
            if below_ma5_days >= 3 and total_drop <= -10:
                signals.append({
                    'type': '连续破5日线',
                    'severity': 'hard',
                    'message': f"连续3日收盘低于5日均线，累计跌幅{total_drop:.1f}%",
                    'action': '立即清仓'
                })
        
        # ========== 分阶段止盈信号 ==========
        
        profit_pct = position.current_profit_pct(current_price)
        
        # +15%：卖出50%仓位
        if profit_pct >= 15 and position.phase1_target > 0:
            signals.append({
                'type': '阶段止盈1',
                'severity': 'soft',
                'message': f"涨幅{profit_pct:.1f}%达到+15%目标价{position.phase1_target}",
                'action': '卖出50%仓位'
            })
        
        # +30%：再卖出30%仓位
        if profit_pct >= 30 and position.phase2_target > 0:
            signals.append({
                'type': '阶段止盈2',
                'severity': 'soft',
                'message': f"涨幅{profit_pct:.1f}%达到+30%目标价{position.phase2_target}",
                'action': '再卖出30%仓位'
            })
        
        # +50%：清仓剩余20%
        if profit_pct >= 50 and position.phase3_target > 0:
            signals.append({
                'type': '阶段止盈3',
                'severity': 'soft',
                'message': f"涨幅{profit_pct:.1f}%达到+50%目标价{position.phase3_target}",
                'action': '清仓剩余20%'
            })
        
        # ========== 动态止盈信号 ==========
        
        # 从阶段最高点回落≥8%
        if position.peak_price > 0:
            drawdown = (current_price - position.peak_price) / position.peak_price * 100
            if drawdown <= -8:
                signals.append({
                    'type': '动态止盈',
                    'severity': 'soft',
                    'message': f"从阶段最高{position.peak_price}回落{drawdown:.1f}%，触发动态止盈",
                    'action': '清仓全部仓位'
                })
        
        # ========== 异常离场信号 ==========
        
        # 板块大跌
        if sector_limit_down:
            signals.append({
                'type': '板块异常',
                'severity': 'hard',
                'message': f"所属板块单日跌幅≥5%，且个股下跌",
                'action': '立即清仓'
            })
        
        # 连续缩量
        if daily_data and len(daily_data) >= 3:
            recent_volumes = [d['volume'] for d in daily_data[-20:]]
            avg_volume = sum(recent_volumes) / 20
            low_volume_days = sum(1 for v in daily_data[-3:] if v['volume'] < avg_volume * 0.5)
            
            if low_volume_days >= 3:
                signals.append({
                    'type': '连续缩量',
                    'severity': 'hard',
                    'message': f"连续3日成交量低于20日均量的50%",
                    'action': '立即清仓'
                })
        
        return signals


# ============================================================
# 主监控模块
# ============================================================
class PositionMonitor:
    """持仓实时监控"""
    
    def __init__(self, data_dir: str = "."):
        self.portfolio = PortfolioManager(data_dir)
        # 需要注入NeoDataClient进行实际价格查询
        self.price_client = None
    
    def set_price_client(self, client):
        """设置价格数据客户端"""
        self.price_client = client
    
    def monitor_all(self) -> List[Dict]:
        """
        监控所有持仓
        返回触发信号的持仓列表
        """
        if not self.positions:
            return []
        
        alerts = []
        
        # 获取当前价格
        prices = {}
        for pos in self.portfolio.get_all_positions():
            if self.price_client:
                data = self.price_client.get_daily_kline(pos.code, days=1)
                if data:
                    prices[pos.code] = data[-1]['close']
            else:
                # 模拟价格（实际使用时需要替换为真实数据）
                prices[pos.code] = pos.peak_price
        
        # 更新阶段最高价
        self.portfolio.update_peak_prices(prices)
        
        # 检查每个持仓
        for pos in self.portfolio.get_all_positions():
            current_price = prices.get(pos.code, pos.entry_price)
            
            # 获取必要的K线数据
            weekly_data = []
            daily_data = []
            if self.price_client:
                weekly_data = self.price_client.get_weekly_kline(pos.code, weeks=10)
                daily_data = self.price_client.get_daily_kline(pos.code, days=60)
                for d in daily_data:
                    d['is_daily'] = True
                weekly_data.extend(daily_data)
            
            # 检查卖出信号
            signals = ExitSignalChecker.check_exit_signals(pos, current_price, weekly_data)
            
            if signals:
                alerts.append({
                    'position': pos,
                    'current_price': current_price,
                    'profit_pct': pos.current_profit_pct(current_price),
                    'signals': signals
                })
        
        return alerts
    
    @property
    def positions(self) -> List[Position]:
        return self.portfolio.get_all_positions()
    
    def format_alerts(self, alerts: List[Dict]) -> str:
        """格式化预警信息"""
        if not alerts:
            return "✅ 持仓标的无卖出信号"
        
        lines = []
        lines.append("⚠️ 持仓预警汇总")
        lines.append("=" * 60)
        
        for alert in alerts:
            pos = alert['position']
            lines.append(f"\n【{pos.code} {pos.name}】")
            lines.append(f"  当前价: {alert['current_price']} | 盈亏: {alert['profit_pct']:+.2f}%")
            lines.append(f"  买入价: {pos.entry_price} | 止损价: {pos.stop_loss}")
            lines.append(f"  阶段最高: {pos.peak_price}")
            lines.append("  触发信号:")
            
            for signal in alert['signals']:
                severity_icon = "🔴" if signal['severity'] == 'hard' else "🟡"
                lines.append(f"    {severity_icon} {signal['type']}: {signal['message']}")
                lines.append(f"       → 建议: {signal['action']}")
        
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ============================================================
# CLI命令行接口
# ============================================================
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='V4.3.1 持仓管理')
    parser.add_argument('action', choices=['status', 'add', 'sell', 'monitor', 'history', 'stats'],
                       help='操作命令')
    parser.add_argument('--code', help='股票代码')
    parser.add_argument('--name', help='股票名称')
    parser.add_argument('--path', help='路径A或B')
    parser.add_argument('--pattern', help='周线形态')
    parser.add_argument('--price', type=float, help='买入/卖出价格')
    parser.add_argument('--quantity', type=int, help='数量')
    parser.add_argument('--date', help='日期')
    parser.add_argument('--reason', help='原因')
    
    args = parser.parse_args()
    
    pm = PortfolioManager()
    
    if args.action == 'status':
        print(pm.format_status())
    
    elif args.action == 'add':
        if not all([args.code, args.name, args.price, args.quantity]):
            print("⚠️ 添加持仓需要: --code --name --price --quantity")
            return
        
        pos = Position(
            code=args.code,
            name=args.name,
            path=args.path or '',
            pattern=args.pattern or '',
            entry_date=args.date or datetime.now().strftime('%Y-%m-%d'),
            entry_price=args.price,
            quantity=args.quantity,
            stop_loss=0,
            notes=''
        )
        pm.add_position(pos)
    
    elif args.action == 'sell':
        if not args.code:
            print("⚠️ 卖出需要: --code")
            return
        pm.remove_position(args.code, args.reason or '', args.price or 0)
    
    elif args.action == 'monitor':
        monitor = PositionMonitor()
        alerts = monitor.monitor_all()
        print(monitor.format_alerts(alerts))
    
    elif args.action == 'history':
        for trade in pm.get_trade_history():
            print(f"{trade.date} | {trade.action} | {trade.code} {trade.name} | "
                  f"@{trade.price} x {trade.quantity} | {trade.reason}")
    
    elif args.action == 'stats':
        stats = pm.get_performance_stats()
        print(f"总交易: {stats['total_trades']}")
        print(f"胜率: {stats['win_rate']:.1f}%")
        print(f"平均盈亏: {stats['avg_profit']:+.2f}%")


if __name__ == "__main__":
    main()
