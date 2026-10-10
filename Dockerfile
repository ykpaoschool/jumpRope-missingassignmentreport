# syntax=docker/dockerfile:1

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first to leverage layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (no .env — credentials are passed at runtime)
COPY app/ ./app/
COPY static/ ./static/
# 管理员脚本：服务器上只有 compose.yaml 与 .env，脚本不随镜像下去就没法在服务器上执行
# （docker compose exec mailer python3 scripts/clear_send_log.py ...）
COPY scripts/ ./scripts/

# Run as an unprivileged user
RUN useradd --create-home --uid 1000 appuser
# 发送日志（SQLite）落在这里：/app 由 root 创建且是 755，uid 1000 无权在其中新建目录，
# 不预先建好并改属主的话，容器里日志会一写就失败
RUN mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
