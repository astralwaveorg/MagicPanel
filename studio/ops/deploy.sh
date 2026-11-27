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
test -s "$base/bootstrap/data/master.key"
test -s "$base/bootstrap/data/studio.sqlite3"
# Keep host-only secrets and state outside every source archive.
if ! test -x "$base/core/mihomo"; then
  mkdir -p "$base/core"
  for file in mihomo geoip.dat geosite.dat country.mmdb; do cp -p "/opt/magicpanel/data/bin/$file" "$base/core/$file"; done
fi
touch "$base/minimax.key"
chmod 600 "$base/minimax.key"
printf 'REVISION=%s\nSTUDIO_STATE_DIR=%s\nSTUDIO_AI_KEY=%s\n' "$rev" "$base/bootstrap/data" "$base/minimax.key" > .env
docker compose config --quiet
docker compose build studio
docker compose up -d --no-build --wait --wait-timeout 80
curl -fsS --max-time 5 http://127.0.0.1:47102/healthz
ln -sfn "$base/releases/$rev" "$base/current"
NAS
