#!/usr/bin/env bash
# 下载 Mihomo Geo 数据（geosite.dat / geoip.dat / country.mmdb）并安装到 NAS。
#
# 背景：产物里若使用 geosite:/geoip: 引用，核心校验需要对应的数据文件；
# 核心默认从 GitHub 自行下载，境内常挂起。手动装到 data/core-work/ 后即可复用。
#
# 用法：
#   scripts/fetch_geo_data.sh                # 默认版本（与已安装核心一致）+ 默认代理
#   PROXY=http://10.0.1.8:7890 scripts/fetch_geo_data.sh
# 默认代理是 Mac mini 上的 Stash 混合端口；下载跑在本机，写 127.0.0.1:7890 也一样。
set -euo pipefail

NAS_HOST="${NAS_HOST:-archon@10.0.1.2}"
NAS_DIR="${NAS_DIR:-/opt/magicpanel}"
PROXY="${PROXY:-http://10.0.1.8:7890}"
BASE="https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest"
FILES=(geosite.dat geoip.dat country.mmdb)
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== 下载 Geo 数据（代理 $PROXY）=="
for f in "${FILES[@]}"; do
  echo -n "  $f: "
  curl -sL -x "$PROXY" --max-time 300 -o "$TMP/$f" -w "%{http_code} %{size_download}\n" "$BASE/$f"
done

echo "== 上传到 $NAS_HOST:$NAS_DIR/data/core-work =="
ssh -o BatchMode=yes "$NAS_HOST" "mkdir -p '$NAS_DIR/data/core-work' '$NAS_DIR/data/bin'"
for f in "${FILES[@]}"; do
  scp -q -o BatchMode=yes "$TMP/$f" "$NAS_HOST:$NAS_DIR/data/core-work/$f"
  scp -q -o BatchMode=yes "$TMP/$f" "$NAS_HOST:$NAS_DIR/data/bin/$f"
  echo "  $f 已安装"
done

echo "== 校验 =="
ssh -o BatchMode=yes "$NAS_HOST" "ls -lh '$NAS_DIR/data/core-work'"
echo "完成：下次构建的 mihomo 核心校验即可使用 geosite:/geoip: 引用。"
