#!/usr/bin/env bash
# On NAS, from the verified release. v1's site file is not edited.
set -euo pipefail
cd "$(dirname "$0")"
site=/usr/local/openresty/nginx/conf/conf.d/v2.magichub.top.conf
curl -fsS --max-time 5 http://127.0.0.1:47102/healthz >/dev/null
docker exec openresty openssl x509 -noout -checkhost v2.magichub.top -in /www/sites/www.magichub.top/ssl/fullchain.pem | grep -q 'does match'
if docker exec openresty test -f "$site"; then
  cmp <(docker exec openresty cat "$site") v2.magichub.top.conf || { echo '已有不同的 v2 站点，保留现场'; exit 1; }
else
  docker exec -i openresty sh -c 'umask 022; cat > "$1"' sh "$site" < v2.magichub.top.conf
  if ! docker exec openresty nginx -t; then docker exec openresty rm "$site"; exit 1; fi
fi
docker exec openresty nginx -t && docker exec openresty nginx -s reload
