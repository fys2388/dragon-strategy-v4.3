# -*- coding: utf-8 -*-
# ============================================================
# 本机手动运行脚本（Windows PowerShell 版）
# ⚠️ 仅限手动跑一次验证链路，不要注册为「任务计划程序」定时推送（AGENTS.md 铁律 1）。
#   旧的本机定时推送方案已废弃，原文归档于 archive/README_LOCAL_RUN_DEPRECATED.md。
# 用法：powershell.exe -ExecutionPolicy Bypass -File "E:\AI\策略\dragon-strategy-v4.3\scripts\run_local.ps1"
# ============================================================
param(
    [string]$RepoDir = "E:\AI\策略\dragon-strategy-v4.3",
    [string]$Python = "python",
    [string]$Source = "auto",
    [switch]$SkipPull
)

$ErrorActionPreference = "Continue"
$LogDir = Join-Path $RepoDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("local_run_{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f $stamp, $msg
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "==== 本机扫描启动 (source=$Source) ===="

# 1. 拉取最新代码（可选）
if (-not $SkipPull) {
    Push-Location $RepoDir
    try {
        git pull origin main 2>&1 | ForEach-Object { Write-Log "git: $_" }
    } catch {
        Write-Log "git pull 失败（继续使用本地代码）: $_"
    }
    Pop-Location
}

# 2. 运行策略扫描（含飞书推送）
Push-Location $RepoDir
try {
    $env:PYTHONIOENCODING = "utf-8"
    $out = & $Python -m strategies.macd_resonance.scanner --push --source $Source 2>&1
    $out | ForEach-Object { Write-Log "scanner: $_" }
    Write-Log "==== 扫描结束，退出码 $LASTEXITCODE ===="
} catch {
    Write-Log "扫描异常: $_"
    Write-Log "==== 扫描异常退出 ===="
} finally {
    Pop-Location
}
