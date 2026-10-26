# alpha-pick — A股中线波段选股系统

从零搭建的选股体系，针对「信号不准」做专项优化。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置飞书 webhook（三选一）
#    方式A: 环境变量
export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx"
#    方式B: 编辑 config/settings.py 中的 FEISHU.webhook_url
#    方式C: 编辑 config/feishu.json

# 3. 运行
python cli.py status        # 查看系统状态
python cli.py scan          # 盘前选股（推荐先跑 --no-push 测试）
python cli.py backtest      # 回测验证
```

## 命令一览

| 命令 | 说明 | 推荐时间 |
|------|------|----------|
| `scan` | 盘前选股 + 飞书推送 | 09:00 |
| `alert` | 盘中持仓异动预警 | 每5分钟 |
| `review` | 盘后复盘 | 15:30 |
| `backtest` | 信号回测验证 | 任意 |
| `positions` | 查看当前持仓 | 任意 |
| `add <code>` | 添加持仓 | 买入时 |
| `remove <code>` | 移除持仓 | 卖出时 |
| `clear-cache` | 清空数据缓存 | 任意 |
| `status` | 系统状态检查 | 任意 |
| `performance` | 绩效追踪报告 | 任意 |
| `health` | 系统健康检查 | 任意 |

## 体系架构

```
数据层 (src/data/)          行情/财务/资金流 → 多源降级(AkShare→东财→新浪) + 前复权 + 本地缓存
选股池 (src/pool/)          全A ~5900 → 初筛 ~1500 → 精筛 ~150 → 候选 ~20-30
信号层 (src/signals/)      3种买点识别 + 打分排序 + 止损目标位
回测层 (backtest.py)       历史信号回放 + 5槽位组合模拟 + 绩效指标
风控层 (src/risk/)         仓位管理 + 大盘闸门 + 绩效追踪 + 相关性分析
监控层 (src/monitor/)      盘前选股 / 盘中预警 / 盘后复盘
推送层 (src/notify/)       飞书消息推送
```

## 核心设计：为什么信号更准

| 老系统常见坑 | 本系统的设计 |
|---|---|
| 追高买入 | 只做回踩企稳和突破确认，不追涨 |
| 下跌股抄底 | 硬性要求 60日线向上 + 中期趋势确认 |
| 垃圾股暴雷 | ROE/营收/现金流 + ST/次新/质押 多重过滤 |
| 无风控硬扛 | 每笔硬止损 -7%，跌破即走 |
| 参数过拟合 | 滚动回测验证，不用单参数最优 |
| 忽略大盘 | 大盘弱势自动降总仓位到 30% 以下 |

## 3种买点

1. **回踩企稳**：缩量回踩20日线 + MACD低位金叉（主信号）
2. **放量突破**：突破20日新高 + 量比>2 + MACD红柱放大
3. **板块启动**：创20日新高 + 涨幅2-8% + 量比>1.5

## 出场规则

- 止损：-7% 或跌破买入时支撑位
- 止盈1：+15% 减半
- 止盈2：+25% 清仓
- 移动止损：跌破10日线清仓
- 时间止损：10个交易日不涨则减半

## 大盘闸门

0-10分制，5维度评分：
- 基准趋势（30%）
- 成交量（25%）
- 市场宽度（20%）
- 北向资金（15%）
- 情绪面（10%）

| 分数 | 级别 | 仓位上限 |
|------|------|----------|
| ≥7 | 强势 | 80% |
| ≥5 | 正常 | 50% |
| ≥3 | 偏弱 | 30% |
| <3 | 极弱 | 空仓 |

## 项目结构

```
alpha-pick/
├── cli.py                 # 命令行入口
├── config/
│   ├── settings.py        # 全局配置（所有参数集中）
│   └── feishu.json        # 飞书配置
├── src/
│   ├── data/              # 数据层
│   │   ├── source.py      #   多源数据获取
│   │   └── cache.py       #   本地缓存
│   ├── pool/              # 选股池
│   │   └── universe.py    #   三层漏斗筛选
│   ├── signals/           # 信号层
│   │   └── entry.py       #   3种买点识别
│   ├── backtest/          # 回测
│   │   └── engine.py      #   向量化回测
│   ├── risk/              # 风控
│   │   ├── position.py    #   仓位管理
│   │   └── market_gate.py #   大盘闸门
│   ├── monitor/           # 监控
│   │   └── scanner.py     #   选股编排
│   └── notify/            # 推送
│       └── feishu.py      #   飞书推送
├── data/                  # 数据缓存（自动生成）
├── reports/               # 输出报告（自动生成）
└── tests/                 # 测试
```

## 定时任务配置

### Windows 任务计划程序

```powershell
# 盘前选股 09:00
schtasks /Create /TN "AlphaPick_PreMarket" /TR "python E:\AI\策略\alpha-pick\cli.py scan" /SC DAILY /ST 09:00

# 盘中预警（每5分钟，交易时段 9:30-15:00）
schtasks /Create /TN "AlphaPick_Alert" /TR "python E:\AI\策略\alpha-pick\cli.py alert" /SC MINUTE /MO 5 /ST 09:30 /ED 15:00

# 盘后复盘 15:30
schtasks /Create /TN "AlphaPick_Review" /TR "python E:\AI\策略\alpha-pick\cli.py review" /SC DAILY /ST 15:30
```

### 删除定时任务

```powershell
schtasks /Delete /TN "AlphaPick_PreMarket" /F
schtasks /Delete /TN "AlphaPick_Alert" /F
schtasks /Delete /TN "AlphaPick_Review" /F
```

## 免责声明

本系统仅为技术分析工具，不构成任何投资建议。股市有风险，投资需谨慎。
