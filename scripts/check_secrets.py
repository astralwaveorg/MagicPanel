#!/usr/bin/env python3
"""提交前扫描：阻止把运行数据或凭据带进仓库。

面板的用户数据（本地节点密码、订阅地址、备份导出、secret.key）都在
`data/` 与 `tmp/` 里，已被 .gitignore 排除；这个脚本是第二道防线——
有人把抓下来的配置顺手放进仓库时，在提交/发布前就报错停下。

规则：
  1. 扫描 git 跟踪的文件（不在仓库里时扫描工作区，跳过忽略项）；
  2. 命中疑似凭据（长密码、uuid、订阅 token）即失败；
  3. 命中运行数据文件（*.db / *.key / 备份导出）即失败。

用法：python3 scripts/check_secrets.py [--all]
  --all  连未跟踪文件一起扫（本地排查用）
退出码：0 = 通过；1 = 发现疑似泄露。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 疑似凭据：键名 + 足够长的值（排除占位符与常见示例）
SECRET_PATTERNS = [
    (re.compile(r"""(?i)\b(?:password|passwd|pwd|uuid|auth_str|auth-string)\s*[:=]\s*["']?([A-Za-z0-9_\-]{12,})"""), "节点/账号密码"),
    (re.compile(r"""(?i)\bws[-_]?path\s*[:=]\s*["']?([A-Za-z0-9_\-/]{12,})"""), "WS 路径（等同密码）"),
    (re.compile(r"""(?i)\?[a-z_]*key=([A-Za-z0-9_\-]{8,})"""), "订阅链接里的令牌"),
    (re.compile(r"""(?i)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|bearer)\s*[:=]\s*["']?([A-Za-z0-9_\-\.]{16,})"""), "接口密钥"),
]

# 运行数据文件：内容不进仓库
DATA_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".key"}
DATA_NAMES = {"secret.key"}
DATA_PATTERNS = [re.compile(r"^data/"), re.compile(r"^tmp/")]

# 明显不是凭据的示例值：整词命中，或含有测试口味的词（admin-pass-1、super-secret）
PLACEHOLDER = re.compile(
    r"(?i)^(your|example|placeholder|change[-_]?me|xxx+|test|dummy|password|secret|"
    r"admin|user|localhost|127\.0\.0\.1|redacted|\*+)$"
)
PLACEHOLDER_HINT = re.compile(
    r"(?i)(secret|pass[-_]?word|pass[-_]|test|dummy|fake|example|placeholder|admin[-_]?pass|your)"
)

# 扫描时跳过的路径（工具与文档里的示例不算）
SKIP_PATHS = [
    re.compile(r"^scripts/check_secrets\.py$"),
    re.compile(r"^docs/"),
    re.compile(r"^\.ref/"),
    re.compile(r"^node_modules/"),
    # 官方文档原文（Stash / Mihomo 的配置样例）：里面的账号密码是官方示例值，
    # 不是本项目的凭据；它们是核对引擎默认配置出处的依据，必须留在仓库里。
    re.compile(r"^official-example/"),
]


def run(args: list[str]) -> str:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True).stdout


def tracked_files(include_untracked: bool) -> list[str]:
    files = [line for line in run(["git", "ls-files"]).splitlines() if line.strip()]
    if include_untracked:
        extra = run(["git", "ls-files", "--others", "--exclude-standard"]).splitlines()
        files += [f for f in extra if f.strip()]
    return files


def is_data_file(path: str) -> bool:
    p = Path(path)
    if p.name in DATA_NAMES or p.suffix.lower() in DATA_SUFFIXES:
        return True
    return any(pat.match(path) for pat in DATA_PATTERNS)


def scan(path: str, text: str) -> list[str]:
    hits: list[str] = []
    for pattern, label in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(1)
            if PLACEHOLDER.match(value) or PLACEHOLDER_HINT.search(value):
                continue
            line = text[: m.start()].count("\n") + 1
            hits.append(f"{path}:{line}  {label}（值以 {value[:4]}… 开头，共 {len(value)} 位）")
            break   # 每个文件每类只报一次，避免刷屏
    return hits


def main() -> int:
    include_untracked = "--all" in sys.argv
    files = tracked_files(include_untracked)
    if not files:
        print("没有可扫描的文件")
        return 0
    problems: list[str] = []
    for path in files:
        if any(pat.match(path) for pat in SKIP_PATHS):
            continue
        if is_data_file(path):
            problems.append(f"{path}  运行数据文件不应进仓库")
            continue
        full = REPO / path
        if not full.is_file() or full.stat().st_size > 2_000_000:
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        problems += scan(path, text)
    if problems:
        print("发现疑似凭据或运行数据，已阻止：")
        for item in problems:
            print("  -", item)
        print("\n处理方式：把这些文件移出仓库（放到 data/、tmp/ 或 docs/archive/ 并加进 .gitignore），"
              "\n凭据已经提交过还要用 git filter-repo 清历史。")
        return 1
    print(f"凭据扫描通过（{len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
