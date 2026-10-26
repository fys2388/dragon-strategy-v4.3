#!/bin/bash
# alpha-pick 云端部署脚本
# 适用于：阿里云/腾讯云/华为云/任何Linux服务器
#
# 用法：
#   sudo bash deploy_cloud.sh          # 部署
#   sudo bash deploy_cloud.sh status   # 查看状态
#   sudo bash deploy_cloud.sh logs     # 查看日志
#   sudo bash deploy_cloud.sh uninstall # 卸载

set -e

# 配置
APP_NAME="alpha-pick"
APP_DIR="/opt/alpha-pick"
SERVICE_USER="alpha-pick"
PYTHON_VERSION="3.11"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  alpha-pick 云端部署脚本${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查root权限
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}错误：请使用 sudo 运行此脚本${NC}"
    exit 1
fi

# 检查Docker
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}未检测到Docker，正在安装...${NC}"
    curl -fsSL https://get.docker.com | sh
    systemctl start docker
    systemctl enable docker
fi

# 检查docker-compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${YELLOW}未检测到docker-compose，正在安装...${NC}"
    curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# 创建用户
if ! id "$SERVICE_USER" &> /dev/null; then
    echo -e "${YELLOW}创建服务用户: $SERVICE_USER${NC}"
    useradd -m -s /bin/bash "$SERVICE_USER"
fi

# 创建应用目录
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# 复制代码
echo -e "${YELLOW}复制项目代码...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$SCRIPT_DIR" != "$APP_DIR" ]; then
    rsync -av --exclude='.git' --exclude='__pycache__' --exclude='data/cache' "$SCRIPT_DIR/" "$APP_DIR/"
fi

cd "$APP_DIR"

# 创建数据目录
mkdir -p data/cache data/logs reports config

# 设置权限
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# 设置环境变量
cat > "$APP_DIR/.env" << 'EOF'
PYTHONUNBUFFERED=1
TZ=Asia/Shanghai
# FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
EOF

# 配置crontab
echo -e "${YELLOW}配置定时任务...${NC}"

# 清除旧任务
crontab -u "$SERVICE_USER" -l 2>/dev/null | grep -v "alpha-pick" > /tmp/crontab_backup || true

# 添加新任务
cat >> /tmp/crontab_backup << 'EOF'
# alpha-pick 定时任务
# 盘前选股：周一至周五 09:00
0 9 * * 1-5 cd /opt/alpha-pick && python cli.py scan >> /opt/alpha-pick/data/logs/cron.log 2>&1
# 盘中预警：周一至周五 09:30-15:00 每5分钟
*/5 9-14 * * 1-5 cd /opt/alpha-pick && python cli.py alert >> /opt/alpha-pick/data/logs/cron.log 2>&1
# 盘后复盘：周一至周五 15:30
30 15 * * 1-5 cd /opt/alpha-pick && python cli.py review >> /opt/alpha-pick/data/logs/cron.log 2>&1
# 健康检查：每6小时
0 */6 * * * cd /opt/alpha-pick && python cli.py health >> /opt/alpha-pick/data/logs/healthcheck.log 2>&1
# 绩效报告：每周日 20:00
0 20 * * 0 cd /opt/alpha-pick && python cli.py performance >> /opt/alpha-pick/data/logs/performance.log 2>&1
EOF

crontab -u "$SERVICE_USER" /tmp/crontab_backup
rm -f /tmp/crontab_backup

# 构建Docker镜像（如果需要）
if [ "$1" = "docker" ]; then
    echo -e "${YELLOW}构建Docker镜像...${NC}"
    docker build -t alpha-pick:latest .
    echo -e "${GREEN}Docker镜像构建完成${NC}"
fi

# 启动服务
echo -e "${YELLOW}启动服务...${NC}"
cd "$APP_DIR"

# 检查是否使用docker-compose
if [ -f docker-compose.yml ]; then
    echo -e "${GREEN}使用Docker Compose部署...${NC}"
    docker compose down 2>/dev/null || true
    docker compose up -d
else
    echo -e "${GREEN}使用直接运行模式...${NC}"
    # 创建systemd服务
    cat > /etc/systemd/system/alpha-pick.service << EOF
[Unit]
Description=alpha-pick Stock Selection System
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 cli.py status
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable alpha-pick
    systemctl start alpha-pick
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  部署完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}部署信息：${NC}"
echo -e "  应用目录：$APP_DIR"
echo -e "  服务用户：$SERVICE_USER"
echo ""
echo -e "${YELLOW}定时任务：${NC}"
echo -e "  盘前选股：09:00 (周一至周五)"
echo -e "  盘中预警：09:30-15:00 每5分钟 (周一至周五)"
echo -e "  盘后复盘：15:30 (周一至周五)"
echo -e "  健康检查：每6小时"
echo -e "  绩效报告：20:00 (周日)"
echo ""
echo -e "${YELLOW}常用命令：${NC}"
echo -e "  查看状态：sudo systemctl status alpha-pick"
echo -e "  查看日志：tail -f /opt/alpha-pick/data/logs/cron.log"
echo -e "  查看健康：cd /opt/alpha-pick && python cli.py health"
echo -e "  手动选股：cd /opt/alpha-pick && python cli.py scan"
echo ""
echo -e "${YELLOW}重要提示：${NC}"
echo -e "  1. 请编辑 /opt/alpha-pick/.env 配置飞书Webhook"
echo -e "  2. 如需Docker部署：sudo bash deploy_cloud.sh docker"
echo -e "  3. 定时任务已配置，交易日历需手动维护"
echo ""

# 如果是status命令
if [ "$1" = "status" ]; then
    echo -e "${YELLOW}服务状态：${NC}"
    systemctl status alpha-pick --no-pager 2>/dev/null || true
    echo ""
    echo -e "${YELLOW}定时任务：${NC}"
    crontab -u "$SERVICE_USER" -l 2>/dev/null | grep "alpha-pick" || true
    echo ""
    echo -e "${YELLOW}系统健康：${NC}"
    cd "$APP_DIR" && python cli.py health 2>&1 || true
fi

# 如果是logs命令
if [ "$1" = "logs" ]; then
    echo -e "${YELLOW}最近100行日志：${NC}"
    tail -100 /opt/alpha-pick/data/logs/cron.log 2>/dev/null || echo "无日志文件"
fi

# 如果是uninstall命令
if [ "$1" = "uninstall" ]; then
    echo -e "${YELLOW}卸载alpha-pick...${NC}"
    systemctl stop alpha-pick 2>/dev/null || true
    systemctl disable alpha-pick 2>/dev/null || true
    rm -f /etc/systemd/system/alpha-pick.service
    systemctl daemon-reload
    crontab -u "$SERVICE_USER" -l 2>/dev/null | grep -v "alpha-pick" > /tmp/crontab_clean || true
    crontab -u "$SERVICE_USER" /tmp/crontab_clean
    rm -f /tmp/crontab_clean
    rm -rf "$APP_DIR"
    echo -e "${GREEN}卸载完成${NC}"
    exit 0
fi
