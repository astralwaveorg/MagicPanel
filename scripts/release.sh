#!/usr/bin/env bash
# 一键打包并发布 GitHub Release：测试 → 打包 → 打标签 → 推送 → 创建 Release
# 用法：scripts/release.sh [版本号]
#   版本号省略时在上一个标签基础上递增补丁位（首个标签为 v1.0.0）
# 配置 GITHUB_TOKEN 后自动创建 Release 并上传产物；否则推送标签后给出创建链接。
# GitHub API 访问不通时自动尝试 GH_PROXY（默认 http://10.0.1.8:6152）。
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="astralwaveorg/MagicPanel"
GH_PROXY="${GH_PROXY:-http://10.0.1.8:6152}"

if [ -n "$(git status --porcelain)" ]; then
  echo "工作区有未提交改动，请先提交再发布。" >&2
  exit 1
fi

LAST=$(git tag -l 'v*' --sort=-v:refname | head -1 || true)
VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  if [ -z "$LAST" ]; then
    VERSION="v1.0.0"
  else
    VERSION=$(echo "$LAST" | awk -F. '{printf "v%d.%d.%d", substr($1,2), $2, $3+1}')
  fi
fi
if git rev-parse "$VERSION" >/dev/null 2>&1; then
  echo "标签 $VERSION 已存在，请显式指定版本号。" >&2
  exit 1
fi
echo "发布版本：$VERSION（上一个标签：${LAST:-无}）"

echo "== 后端测试 =="
(cd server && ../.venv/bin/python -m pytest tests -q)

echo "== 打包 =="
bash scripts/package.sh
PKG=$(ls -t dist/magicpanel-*.tar.gz | head -1)
echo "产物：$PKG"

if [ -n "$LAST" ]; then
  NOTES=$(git log --pretty='- %s' "$LAST..HEAD")
else
  NOTES=$(git log --pretty='- %s' -20)
fi

echo "== 推送代码与标签 =="
git tag -a "$VERSION" -m "$VERSION"
env -u http_proxy -u https_proxy -u all_proxy git push origin main
env -u http_proxy -u https_proxy -u all_proxy git push origin "$VERSION"

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  echo
  echo "未配置 GITHUB_TOKEN，标签已推送。打开下面的链接创建 Release 并上传产物："
  echo "  https://github.com/$REPO/releases/new?tag=$VERSION"
  echo "  产物文件：$PKG"
  exit 0
fi

# GitHub API 请求：先试直连，失败再走代理（本机到 github.com 通常需要代理）
api() {
  shift_method="$1"; shift
  env -u http_proxy -u https_proxy -u all_proxy \
    curl -fsS --max-time 30 -X "$shift_method" -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" "$@" \
  || curl -fsS --max-time 60 -x "$GH_PROXY" -X "$shift_method" \
    -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" "$@"
}

echo "== 创建 GitHub Release =="
BODY=$(python3 -c 'import json,sys; print(json.dumps({"tag_name":sys.argv[1],"name":sys.argv[1],"body":sys.argv[2]}))' "$VERSION" "$NOTES")
RESP=$(echo "$BODY" | api POST "https://api.github.com/repos/$REPO/releases" -H "Content-Type: application/json" --data-binary @-)
UPLOAD_URL=$(echo "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["upload_url"].split("{")[0])')

echo "== 上传产物 =="
api POST "$UPLOAD_URL?name=$(basename "$PKG")" \
  -H "Content-Type: application/gzip" --data-binary @"$PKG" >/dev/null

echo "发布完成：https://github.com/$REPO/releases/tag/$VERSION"
