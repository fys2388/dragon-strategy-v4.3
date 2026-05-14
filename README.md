# V4.3.1 量化交易系统

## 📋 系统概述

这是一个基于严格量化规则的A股沪深主板中短线量化选股与持仓监控系统。

## 🏗️ 系统架构

```
dragon-strategy-v3.8/
├── v4_quant_scanner.py       # 核心选股扫描器
├── v4_portfolio_manager.py    # 持仓管理器
├── portfolio_data.json        # 持仓数据文件
└── requirements.txt           # Python依赖
.github/workflows/
└── intraday.yml              # GitHub Actions盘中监控
```

## ⚙️ 核心模块

### 1. V4量化选股扫描器 (`v4_quant_scanner.py`)

**功能：**
- 大盘环境评分（7分制，≥4分才可开仓）
- 硬性准入条件过滤（价格、市值、成交额、ST过滤）
- 双路径独立筛选：
  - 路径A：超跌反弹左侧池（近12月跌幅≥30%）
  - 路径B：强势龙头右侧池（近3月跌幅10-25%）
- 周线五大形态识别
- MACD量化信号判定（底背离、金叉、红柱放大）

**数据源：** NeoData金融数据服务

### 2. 持仓管理器 (`v4_portfolio_manager.py`)

**功能：**
- 持仓记录（买入日期、价格、数量、目标价）
- 自动计算止盈止损位
- 交易历史记录
- 绩效统计

**CLI命令：**
```bash
# 查看持仓状态
python v4_portfolio_manager.py status

# 添加持仓
python v4_portfolio_manager.py add --code 600519 --name "贵州茅台" --path B --pattern "周线突破平台" --price 1680.50 --quantity 100

# 卖出持仓
python v4_portfolio_manager.py sell --code 600519 --price 1750.00 --reason "阶段止盈1"

# 监控所有持仓
python v4_portfolio_manager.py monitor

# 查看交易历史
python v4_portfolio_manager.py history

# 查看绩效统计
python v4_portfolio_manager.py stats
```

### 3. 盘中实时监控 (`intraday.yml`)

**GitHub Actions定时任务：**
- 工作日9:30-11:30 每5分钟执行
- 工作日13:00-14:30 每5分钟执行

**监控内容：**
1. **首板预警**：扫描符合条件的盘中首板标的
2. **持仓卖出信号**：
   - 硬性止损（周线破位/放量破60日线/连续破5日线）
   - 分阶段止盈（+15%/+30%/+50%）
   - 动态止盈（从最高回落8%）
   - 异常离场（板块大跌/连续缩量）

## 🚀 使用流程

### 第一步：配置GitHub Secrets

在GitHub仓库 Settings → Secrets → Actions 中添加：

| Secret名称 | 说明 |
|-----------|------|
| `WORKBUDDY_API_KEY` | WorkBuddy API密钥 |
| `WORKBUDDY_BOT_ID` | WorkBuddy机器人ID |
| `WORKBUDDY_SESSION_ID` | WorkBuddy会话ID（可选） |
| `FEISHU_WEBHOOK` | 飞书Webhook地址 |

### 第二步：推送到GitHub

```bash
git add .
git commit -m "Add V4.3.1 quantitative trading system"
git push
```

### 第三步：选股与推荐

1. 每日9:15 盘前，系统基于前日数据自动扫描选股
2. WorkBuddy AI根据量化结果给出推荐标的和低吸区间
3. 你决定是否买入

### 第四步：记录持仓

买入后，在WorkBuddy中告诉我：
```
买入600519贵州茅台，路径B，周线突破平台，100股，价格1680.50
```

我会：
1. 记录到 `portfolio_data.json`
2. 自动计算止损价和止盈目标
3. 开始监控

### 第五步：自动预警

- 盘中每5分钟自动检查持仓
- 触发卖出信号 → 飞书推送提醒
- 首板预警机会 → 飞书推送提醒

## 📊 绩效指标

系统自动追踪：
- 胜率
- 平均盈亏比
- 最大回撤
- 路径A/路径B单独绩效

## ⚠️ 执行铁律

1. 路径A只配超跌周线，路径B只配多头周线，不混配
2. 大盘评分<4分一律空仓
3. 只做沪深主板，不碰创业/科创/北交所/ST
4. 严格按量化低吸区间买入，不追高
5. 触发卖出信号立即执行，不侥幸

## 🔧 技术栈

- Python 3.10+
- NeoData金融数据API
- GitHub Actions（自动化调度）
- 飞书Webhook（实时推送）

## 📝 数据格式

### 持仓数据 (`portfolio_data.json`)

```json
{
  "positions": [{
    "code": "600519",
    "name": "贵州茅台",
    "path": "B",
    "pattern": "周线突破平台",
    "entry_date": "2026-05-10",
    "entry_price": 1680.50,
    "quantity": 100,
    "stop_loss": 1562.87,
    "phase1_target": 1932.58,
    "phase2_target": 2184.65,
    "phase3_target": 2520.75,
    "peak_price": 1680.50
  }],
  "history": []
}
```

## 📞 支持

如有问题，在WorkBuddy中随时咨询。
