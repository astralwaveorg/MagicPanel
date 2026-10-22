#!/usr/bin/env bash
# 生成 GitHub Pages 站点并推送到 gh-pages 分支。
#
# 用法：
#   bash scripts/build_docs_site.sh            # 生成并推送
#   bash scripts/build_docs_site.sh --dry-run  # 只生成到临时目录，不推送
#
# 站点内容来自 docs/ 下的三份文档（使用 / 开发 / 配置），
# 链接改写规则写在下面的 PY 片段里。
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="astralwaveorg/MagicPanel"
BRANCH="gh-pages"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

BUILD_DIR="${TMPDIR:-/tmp}/magicpanel-gh-pages"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

cat > "$BUILD_DIR/_config.yml" <<'EOF'
title: MagicPanel 文档
description: 自托管的代理订阅配置管理服务
theme: jekyll-theme-cayman
markdown: kramdown
EOF

cat > "$BUILD_DIR/README.md" <<'EOF'
# MagicPanel 文档站点

本分支由 `scripts/build_docs_site.sh` 从主分支的 `docs/` 生成，请勿直接编辑。

- [使用文档](index.md)
- [开发文档](development.md)
- [配置文档](configuration.md)
- [项目仓库](https://github.com/astralwaveorg/MagicPanel)
EOF

python3 - "$BUILD_DIR" "$REPO" <<'PYEOF'
import pathlib
import re
import sys

build_dir = pathlib.Path(sys.argv[1])
repo = sys.argv[2]

# 源文档 → (站点文件名, 页面标题)
PAGES = [
    ("docs/使用文档.md", "index.md", "MagicPanel 使用文档"),
    ("docs/开发文档.md", "development.md", "MagicPanel 开发文档"),
    ("docs/配置文档.md", "configuration.md", "MagicPanel 配置文档"),
]
# 站点内部互链：源文件名 → 站点文件名
PAGE_MAP = {
    "使用文档.md": "index.md",
    "开发文档.md": "development.md",
    "配置文档.md": "configuration.md",
}
NAV = "[使用文档](index.md) · [开发文档](development.md) · [配置文档](configuration.md)"

link_re = re.compile(r"\]\(([^)]+\.md)\)")


def rewrite(target: str) -> str:
    """站点内互链换成站点文件名；仓库内其它文档跳到 GitHub 原文。"""
    name = target.rsplit("/", 1)[-1]
    if name in PAGE_MAP:
        return PAGE_MAP[name]
    path = target[3:] if target.startswith("../") else target
    return f"https://github.com/{repo}/blob/main/docs/{path}"


for src, dst, title in PAGES:
    path = pathlib.Path(src)
    if not path.exists():
        raise SystemExit(f"缺少源文档：{src}")
    body = link_re.sub(lambda m: f"]({rewrite(m.group(1))})", path.read_text(encoding="utf-8"))
    front = f"---\ntitle: {title}\nlayout: default\n---\n\n{NAV}\n\n"
    (build_dir / dst).write_text(front + body, encoding="utf-8")
    print(f"生成 {dst} ← {src}")
PYEOF

if [ "$DRY_RUN" = "1" ]; then
  echo "dry-run：站点已生成在 $BUILD_DIR"
  exit 0
fi

# 推到 gh-pages：用独立仓库做孤儿分支，不碰主工作区
cd "$BUILD_DIR"
git init -q .
git checkout -q --orphan "$BRANCH"
git add -A
git -c user.name="astral" -c user.email="astral@local" commit -q -m "docs: 更新 GitHub Pages 站点"
git push -q --force "git@github.com:${REPO}.git" "$BRANCH:$BRANCH"
echo "已推送到 ${REPO} 的 ${BRANCH} 分支"
echo "站点地址：https://${REPO}.github.io/MagicPanel/"
