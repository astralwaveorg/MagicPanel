#!/usr/bin/env bash
# 构建前端并打包可部署产物：dist/magicpanel-<时间戳>.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."

npm run build

STAMP=$(date +%Y%m%d-%H%M%S)
STAGE="dist/magicpanel"
rm -rf "$STAGE"
mkdir -p "$STAGE"

cp -R server/app "$STAGE/app"
rm -rf "$STAGE"/app/__pycache__ "$STAGE"/app/*/__pycache__
cp server/requirements.txt "$STAGE/"
cp README.md "$STAGE/"

cat > "$STAGE/run.sh" <<'EOF'
#!/usr/bin/env bash
# 启动 MagicPanel；首次运行创建虚拟环境并安装依赖。
set -euo pipefail
cd "$(dirname "$0")"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --proxy-headers
EOF
chmod +x "$STAGE/run.sh"

mkdir -p dist
tar czf "dist/magicpanel-${STAMP}.tar.gz" -C dist magicpanel
echo "已生成 dist/magicpanel-${STAMP}.tar.gz"
