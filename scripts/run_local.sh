#!/bin/bash
# ============================================================
# 本机定时运行脚本（Linux/macOS 版，Windows 用户请用 run_local.ps1）
# 用法（crontab 示例，周一至周五盘中）：
#   15 9 * * 1-5  cd /path/to/repo && bash scripts/run_local.sh auto >> logs/local_cron.log 2>&1
#   0,30 10-11 * * 1-5 cd /path/to/repo && bash scripts/run_local.sh auto >> logs/local_cron.log 2>&1
#   0,30 13-14 * * 1-5 cd /path/to/repo && bash scripts/run_local.sh auto >> logs/local_cron.log 2>&1
#   50 14 * * 1-5 cd /path/to/repo && bash scripts/run_local.sh auto >> logs/local_cron.log 2>&1
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
