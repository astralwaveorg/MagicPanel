# syntax=docker/dockerfile:1

# ---- 前端构建 ----
FROM node:20-alpine AS web
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

# ---- 运行时 ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    MAGICPANEL_DATA_DIR=/app/data
WORKDIR /app

COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app
COPY --from=web /build/server/app/static ./app/static

RUN groupadd -r magicpanel && useradd -r -g magicpanel -u 10001 magicpanel \
    && mkdir -p /app/data && chown -R magicpanel:magicpanel /app/data
USER magicpanel

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/setup/status', timeout=4)" || exit 1

# --proxy-headers：信任 1Panel 反向代理的 X-Forwarded-*，使订阅地址按域名生成
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
