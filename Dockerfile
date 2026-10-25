# ---- 前端构建 ----
FROM node:22-alpine AS web
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY public ./public
COPY src ./src
RUN npm run build

# ---- 运行时 ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    MAGICPANEL_DATA_DIR=/app/data
WORKDIR /app

COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 自主维护要真的做 Git 操作（克隆、拉取、提交、推送、三方合并），
# 需要真 git 与 ssh；openssh-client 同时提供 ssh-keygen（生成部署密钥对）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY server/app ./app
COPY --from=web /build/server/app/static ./app/static

# 运行身份由 docker-compose.yml 的 user 指定（NAS 上是 1000:1001，
# 与 data 目录的属主一致）。这里只为这个 uid 补一条 passwd/group 记录，
# 不改变 uid 本身，也不新建目录属主：没有这条记录，ssh 会因为
# "No user exists for uid 1000" 直接拒绝连接，自主维护的 Git 操作就做不了。
RUN groupadd --gid 1001 app 2>/dev/null || true \
 && useradd --uid 1000 --gid 1001 --no-create-home \
        --home-dir /app/data --shell /usr/sbin/nologin app 2>/dev/null || true
RUN mkdir -p /app/data

EXPOSE 8000
VOLUME ["/app/data"]

# 健康检查要覆盖真实依赖：接口可用、数据目录可写、磁盘还有余量。
# 只探一个接口的话，磁盘写满时面板依然"健康"，但构建与订阅会先后失败。
HEALTHCHECK --interval=30s --timeout=8s --start-period=20s --retries=3 \
  CMD python -c "import os,shutil,urllib.request; \
urllib.request.urlopen('http://127.0.0.1:8000/api/v1/setup/status', timeout=4).read(); \
p='/app/data'; open(p+'/.healthcheck','w').close(); os.remove(p+'/.healthcheck'); \
free=shutil.disk_usage(p).free; \
assert free > 200*1024*1024, 'disk low: %d' % free" || exit 1

# --proxy-headers：信任 1Panel 反向代理的 X-Forwarded-*，使订阅地址按域名生成
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
