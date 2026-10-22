#!/usr/bin/env python3
"""把 docs/ 下的三份文档生成为 GitHub Pages 站点源码。

产物在 docs_site/：
  index.md          使用文档（首页）
  development.md    开发文档
  configuration.md  配置文档

站点由 .github/workflows/pages.yml 里的 Jekyll 动作构建并发布。
本地想预览可以先跑本脚本，再用 Jekyll 或任意静态服务器看 docs_site/。

用法：
  python3 scripts/build_docs_site.py            # 生成到 docs_site/
  python3 scripts/build_docs_site.py --out DIR  # 生成到别处
"""
import argparse
import pathlib
import re
import shutil
import sys

REPO = "astralwaveorg/MagicPanel"
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

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

LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")

CONFIG = """title: MagicPanel 文档
description: 自托管的代理订阅配置管理服务
theme: jekyll-theme-cayman
markdown: kramdown
"""


def rewrite(target: str, src_dir: pathlib.Path) -> str:
    """站内互链换成站点文件名；仓库内其它文档跳到 GitHub 原文。"""
    name = target.rsplit("/", 1)[-1]
    if name in PAGE_MAP:
        return PAGE_MAP[name]
    # 仓库内相对路径：按源文档所在目录解析，指向仓库里的真实位置
    # （`../AGENTS.md` 在仓库根，不能拼成 docs/AGENTS.md）
    if target.startswith(("http://", "https://", "#")):
        return target
    resolved = (src_dir / target).resolve()
    try:
        rel = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return target
    return f"https://github.com/{REPO}/blob/main/{rel.as_posix()}"


def build(out_dir: pathlib.Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_config.yml").write_text(CONFIG, encoding="utf-8")
    (out_dir / "README.md").write_text(
        "# MagicPanel 文档站点\n\n"
        "本目录由 `scripts/build_docs_site.py` 从主分支的 `docs/` 生成，"
        "请勿直接编辑。\n\n"
        "- [使用文档](index.md)\n"
        "- [开发文档](development.md)\n"
        "- [配置文档](configuration.md)\n"
        f"- [项目仓库](https://github.com/{REPO})\n",
        encoding="utf-8",
    )
    count = 0
    for src, dst, title in PAGES:
        path = pathlib.Path(src)
        if not path.exists():
            print(f"缺少源文档：{src}", file=sys.stderr)
            return 1
        body = LINK_RE.sub(lambda m: f"]({rewrite(m.group(1), path.parent)})",
                           path.read_text(encoding="utf-8"))
        front = f"---\ntitle: {title}\nlayout: default\n---\n\n{NAV}\n\n"
        (out_dir / dst).write_text(front + body, encoding="utf-8")
        print(f"生成 {dst} ← {src}")
        count += 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 GitHub Pages 站点源码")
    parser.add_argument("--out", default="docs_site", help="输出目录，默认 docs_site")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    rc = build(out)
    if rc == 0:
        print(f"站点源码已生成：{out}/（由 .github/workflows/pages.yml 发布）")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
