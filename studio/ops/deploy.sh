#!/usr/bin/env bash
# Deploy only Studio. Never call the v1 deploy script from this directory.
set -euo pipefail
cd "$(dirname "$0")/../.."
host=${STUDIO_NAS:-archon@10.0.1.2}
rev=$(git rev-parse HEAD)
test "$(git branch --show-current)" = v2
test -z "$(git status --porcelain -- studio)"
test "$(git ls-remote origin refs/heads/v2 | cut -f1)" = "$rev"
ssh -o BatchMode=yes "$host" "set -eu; sudo -n install -d -m 700 -o archon -g users /opt/magicpanel-v2; mkdir -p '/opt/magicpanel-v2/releases/$rev'"
git archive "$rev:studio" | ssh -o BatchMode=yes "$host" "tar xf - -C '/opt/magicpanel-v2/releases/$rev'"
ssh -o BatchMode=yes "$host" "bash -s -- '$rev'" <<'NAS'
set -euo pipefail
umask 077
base=/opt/magicpanel-v2
rev=$1
cd "$base/releases/$rev"
exec 9>"$base/deploy.lock"
flock -n 9 || { echo '已有 v2 部署任务'; exit 1; }
state="$base/state"
previous=$(readlink -f "$base/current" 2>/dev/null || :)
promote=false
if ! test -s "$state/studio.sqlite3" && test -s "$base/bootstrap/data/studio.sqlite3"; then
  promote=true
  state=$(mktemp -d "$base/state-candidate.XXXXXX")
else
  mkdir -p "$state"
fi
# Keep host-only secrets and state outside every source archive.
if ! test -x "$base/core/mihomo"; then
  echo "缺少 /opt/magicpanel-v2/core/mihomo 和地理数据，请放入已验证的核心包" >&2
  exit 1
fi
touch "$base/minimax.key"
chmod 600 "$base/minimax.key"
printf 'REVISION=%s\nSTUDIO_STATE_DIR=%s\nSTUDIO_AI_KEY=%s\n' "$rev" "$state" "$base/minimax.key" > .env
docker compose config --quiet
docker compose build studio
resume_old() {
  if test -n "$previous" && test -f "$previous/.env"; then
    (cd "$previous" && docker compose up -d --no-build --wait --wait-timeout 80 studio) >&2 || echo '旧 v2 镜像恢复失败' >&2
  fi
}
if "$promote"; then
  test -f "$previous/.env"
  trap resume_old ERR
  (cd "$previous" && docker compose stop studio)
  cp -p "$base/bootstrap/data/master.key" "$state/master.key"
  python3 - "$base/bootstrap/data/studio.sqlite3" "$state/studio.sqlite3" <<'PYBACKUP'
import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+"?mode=ro",uri=True) as src,sqlite3.connect(sys.argv[2]) as dst:
    src.backup(dst)
    if dst.execute("pragma quick_check").fetchone()[0]!="ok": raise SystemExit(1)
PYBACKUP
fi
if ! test -s "$state/studio.sqlite3"; then
  bootstrap_pass="$base/initial-admin-password"
  if ! test -s "$bootstrap_pass"; then python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$bootstrap_pass"; fi
  docker compose run --rm -T --no-deps studio python -m studio.init --admin admin < "$bootstrap_pass"
else
  docker compose run --rm -T --no-deps studio python -m studio.platform_upgrade </dev/null
fi
docker compose up -d --no-build --wait --wait-timeout 80 </dev/null
curl -fsS --max-time 5 http://127.0.0.1:47102/healthz
if "$promote"; then ln -sT "$state" "$base/state"; fi
ln -sfnT "$base/releases/$rev" "$base/current"
trap - ERR
NAS
# Check from a separate SSH session: a helper consuming stdin must never report a partial deploy as success.
ssh -o BatchMode=yes "$host" "bash -s -- '$rev'" <<'VERIFY'
set -eu
cd /opt/magicpanel-v2/current
test "$(basename "$(pwd -P)")" = "$1"
cid=$(docker compose ps -q studio)
test -n "$cid"
test "$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$cid")" = "$1"
test "$(docker inspect --format '{{.State.Health.Status}}' "$cid")" = healthy
VERIFY
