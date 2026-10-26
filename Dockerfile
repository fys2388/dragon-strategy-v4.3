# alpha-pick Dockerfile
# 用于云端部署（阿里云/腾讯云/任何Docker环境）

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV TZ=Asia/Shanghai

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data/cache /app/data/logs /app/reports

# 设置时区
ENV TZ=Asia/Shanghai

# 默认命令
CMD ["python", "cli.py", "status"]
