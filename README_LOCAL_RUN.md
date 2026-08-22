# 本机定时运行配置（Windows 任务计划程序）

> 数据自驱层 V2.0 双模式部署：**本机为主**（盘中每 5 分钟），**GitHub Actions 为兜底**（仅 9:15 + 14:50）。
> 原因：GitHub Actions 海外 IP 访问东方财富不稳定（实测标的池 0/57/286/590 只波动、间歇被限流），
> 本机（大陆网络）直连东财稳定且无频率限制。

## 一、前置准备（一次性）

1. 安装 Python 3.10+，并安装依赖：

   ```powershell
   cd E:\AI\策略\dragon-strategy-v4.3
   pip install -r requirements.txt
   ```

2. 配置飞书 Webhook 环境变量（任务计划程序需要读取）：

   ```powershell
   setx FEISHU_WEBHOOK_URL "https://open.feishu.cn/open-apis/bot/v2/hook/你的新地址"
   ```

   > 注意：`setx` 只对新开进程生效，配置后需重启 PowerShell 再测试。

3. 测试脚本可运行：

   ```powershell
   powershell.exe -ExecutionPolicy Bypass -File "E:\AI\策略\dragon-strategy-v4.3\scripts\run_local.ps1" -SkipPull
   ```

   预期看到 `==== 本机扫描启动 ====` 与扫描日志，日志追加到 `logs/local_run_YYYYMMDD.log`。

## 二、创建计划任务（盘中每 5 分钟）

在管理员 PowerShell 执行（一次性创建，含全部触发时间）：

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-ExecutionPolicy Bypass -File "E:\AI\策略\dragon-strategy-v4.3\scripts\run_local.ps1"'
$trigger = @(
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:15),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:30),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:35),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:40),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:45),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:50),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:55),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:00),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:05),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:10),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:15),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:20),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:25),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:30),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:35),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:40),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:45),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:50),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 10:55),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 11:00),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 11:05),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 11:10),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 11:15),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 11:20),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 11:25),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 11:30),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:00),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:05),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:10),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:15),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:20),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:25),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:30),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:35),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:40),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:45),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:50),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 13:55),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:00),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:05),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:10),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:15),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:20),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:25),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:30),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:35),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:40),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:45),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:50)
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "MACD策略本机扫描" -Action $action -Trigger $trigger `
  -Settings $settings -Force -User "SYSTEM" -RunLevel Highest
```

> 说明：
> - 每 5 分钟一个触发器（9:30-11:30、13:00-14:50 + 盘前 9:15）。scanner 入口自带交易时段守卫（盘前 9:15-9:30 + 盘中 9:30-11:30/13:00-15:00），午休/收盘后触发会自动跳过；需强制运行时设置环境变量 TEST_MODE=true。
> - 若嫌触发器过多，可只保留关键时点：9:15 / 9:45 / 10:15 / 10:45 / 11:15 / 13:15 / 13:45 / 14:15 / 14:50。
> - 勾选"唤醒计算机运行此任务"：注册时默认开启（若机器睡眠需 `-Settings` 中确认）。

## 三、图形界面方式（备选）

1. 开始菜单搜索"任务计划程序" → 创建任务。
2. 常规：名称 `MACD策略本机扫描`，勾选"使用最高权限运行"。
3. 触发器：新建 → 每周 → 勾选周一至周五 → 设置各触发时间（可多建触发器）。
4. 操作：新建 → 程序 `powershell.exe` → 参数
   `-ExecutionPolicy Bypass -File "E:\AI\策略\dragon-strategy-v4.3\scripts\run_local.ps1"`。
5. 条件：勾选"唤醒计算机运行此任务"；取消"只有在计算机使用交流电源时才启动"。

## 四、验证

1. 手动运行一次：`powershell.exe -ExecutionPolicy Bypass -File "...\run_local.ps1" -SkipPull`
2. 检查飞书是否收到推送；检查 `logs/local_run_YYYYMMDD.log` 中的诊断行：
   `📡 数据源：东财(主)/AkShare(备) | 校验：✅正常 | 市场环境：xxx | 扫描X只→过滤Y只→通过Z只`
3. 排障参数：`-Source eastmoney` / `-Source akshare` / `-Source auto` 强制指定数据源。

## 五、与 GitHub Actions 的关系

| 项目 | 本机（主） | GH Actions（兜底） |
|---|---|---|
| 盘中推送 | 每 5 分钟（任务计划程序） | 仅 9:15 + 14:50 |
| 数据源 | 东财直连（稳定）+ AkShare 备源 | 东财（不稳定）+ AkShare（海外受限） |
| 本机未开机时 | — | 兜底推送盘前/尾盘 |
| 历史记录 | 本地持久（strategy_history.jsonl） | 每次全新 checkout，不持久 |
