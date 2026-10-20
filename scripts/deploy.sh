#!/usr/bin/env bash
# 一键发布到 NAS：测试 → 同步工作区 → 重建容器 → 健康检查 → 域名验证
# 用法：scripts/deploy.sh [--fast]
#   --fast  跳过后端测试，适合只改了前端的快速验证
# 可用环境变量覆盖：NAS_HOST NAS_DIR DOMAIN
set -euo pipefail
cd "$(dirname "$0")/.."

NAS_HOST="${NAS_HOST:-archon@10.0.1.2}"
NAS_DIR="${NAS_DIR:-/opt/magicpanel}"
DOMAIN="${DOMAIN:-https://magichub.top:8443}"
SKIP_TESTS=0
[ "${1:-}" = "--fast" ] && SKIP_TESTS=1

DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$DIRTY" != "0" ]; then
  echo "提示：工作区有 $DIRTY 处未提交改动，将按当前工作区内容发布"
fi

if [ "$SKIP_TESTS" = "0" ]; then
  echo "== 后端测试 =="
  (cd server && ../.venv/bin/python -m pytest tests -q)
fi

echo "== 权限自检 =="
# 容器以非 root 运行，镜像内文件必须对其他用户可读，否则启动即 PermissionError
BAD=$(find server/app scripts -type f ! -perm -004 | grep -v __pycache__ || true)
if [ -n "$BAD" ]; then
  echo "以下文件缺少其他用户可读权限，会导致容器启动失败：" >&2
  echo "$BAD" >&2
  echo "修复：chmod 644 $BAD" >&2
  exit 1
fi

echo "== 数据目录预检 =="
# 容器以 1000:1001 运行，data 目录必须对该身份可写，
# 否则容器启动即 PermissionError（并被 restart 策略反复拉起）。
DATA_CHECK=$(ssh -o BatchMode=yes "$NAS_HOST" \
  "cd '$NAS_DIR' && (mkdir -p data && test -w data && echo writable || echo 'not-writable')" || true)
if [ "$DATA_CHECK" != "writable" ]; then
  echo "data 目录对运行身份不可写：$DATA_CHECK" >&2
  echo "修复：ssh $NAS_HOST 'chown -R 1000:1001 $NAS_DIR/data'" >&2
  exit 1
fi

echo "== 同步代码到 $NAS_HOST:$NAS_DIR =="
# data 目录是线上持久化数据，排除且 --delete 不会触及
# --delete 会删掉 NAS 侧独有的文件（1Panel 生成的 override、.env 里的代理配置等），
# 这些文件不在仓库里，一旦被删下次构建就会拉包失败——必须排除。
rsync -az --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude 'data' \
  --exclude 'dist' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'Stash 真实配置文件示例' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude 'docker-compose.override.yml' \
  --exclude 'docker-compose.override.yaml' \
  --exclude '*.bak' \
  ./ "$NAS_HOST:$NAS_DIR/"

echo "== 重建并重启容器 =="
# 记录当前镜像，失败时回滚到它
PREV_IMAGE=$(ssh -o BatchMode=yes "$NAS_HOST" \
  "docker inspect --format '{{.Image}}' magicpanel 2>/dev/null || echo ''" || true)
# 刚重启时 NAS 的外网可能还没恢复，npm/pip 拉包会失败；
# 需要时用 DEPLOY_PROXY=http://host:port 走局域网代理。
if [ -n "${DEPLOY_PROXY:-}" ]; then
  echo "使用构建代理：$DEPLOY_PROXY"
  ssh -o BatchMode=yes "$NAS_HOST" \
    "cd '$NAS_DIR' && HTTP_PROXY='$DEPLOY_PROXY' HTTPS_PROXY='$DEPLOY_PROXY' \
     NO_PROXY='localhost,127.0.0.1,10.0.0.0/8' docker compose up -d --build"
else
  ssh -o BatchMode=yes "$NAS_HOST" "cd '$NAS_DIR' && docker compose up -d --build"
fi

echo "== 等待健康检查 =="
STATUS=""
for _ in $(seq 1 40); do
  STATUS=$(ssh -o BatchMode=yes "$NAS_HOST" \
    "docker inspect --format '{{.State.Health.Status}}' magicpanel 2>/dev/null || echo missing")
  [ "$STATUS" = "healthy" ] && break
  sleep 3
done
echo "容器状态：$STATUS"
if [ "$STATUS" != "healthy" ]; then
  echo "健康检查未通过，查看日志：ssh $NAS_HOST 'docker logs magicpanel --tail 50'" >&2
  # 回滚到上一个镜像，避免一次坏发布把面板长时间打挂
  if [ -n "$PREV_IMAGE" ]; then
    echo "尝试回滚到上一镜像 $PREV_IMAGE" >&2
    ssh -o BatchMode=yes "$NAS_HOST" \
      "cd '$NAS_DIR' && docker compose down && \
       IMAGE_TAG=\"$PREV_IMAGE\" docker compose up -d" || true
    echo "已尝试回滚，请检查 docker ps 与日志" >&2
  fi
  exit 1
fi

echo "== 域名验证 =="
FAIL=0
# 走 /api/v1/setup/status 而不是 SPA 页面：SPA 兜底对任何路径都返回 200，
# 反代没把 /api 转发过去时也看不出问题。
for path in /api/v1/setup/status / /admin/login; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 10 "$DOMAIN$path" || echo 000)
  echo "$CODE $DOMAIN$path"
  [ "$CODE" = "200" ] || FAIL=1
done
[ "$FAIL" = "0" ] && echo "发布完成：$DOMAIN" || { echo "域名验证未通过，请检查反代与证书" >&2; exit 1; }
