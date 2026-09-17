#!/bin/bash
# ============================================================
# 本机手动运行脚本（Linux/macOS 版，Windows 用户请用 run_local.ps1）
# ⚠️ 仅限手动跑一次验证链路，不要写进 crontab 定时推送（AGENTS.md 铁律 1）。
#   旧的本机定时推送方案已废弃，原文归档于 archive/README_LOCAL_RUN_DEPRECATED.md。
# 用法：bash scripts/run_local.sh auto
# ============================================================
set -e
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="${1:-auto}"
cd "$REPO_DIR"

mkdir -p logs
LOG_FILE="logs/local_run_$(date +%Y%m%d).log"
echo "==== $(date '+%Y-%m-%d %H:%M:%S') 本机扫描启动 (source=$SOURCE) ====" | tee -a "$LOG_FILE"

# 1. 拉取最新代码（失败不阻断）
git pull origin main 2>&1 | tee -a "$LOG_FILE" || echo "git pull 失败，使用本地代码" | tee -a "$LOG_FILE"

# 2. 激活虚拟环境（若存在）
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 3. 运行策略扫描
python -m strategies.macd_resonance.scanner --push --source "$SOURCE" 2>&1 | tee -a "$LOG_FILE"
echo "==== $(date '+%Y-%m-%d %H:%M:%S') 扫描结束 ====" | tee -a "$LOG_FILE"
