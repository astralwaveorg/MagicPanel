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
    # 私钥块与 Fernet 密文：整块或前缀命中就是硬事故（2026-11-18 补模式）。
    # tests/ 下的 fixture 假私钥豁免（真凭据不放测试文件是另一条纪律，
    # 由 review 把关；扫描误报会让真信号被淹没）
    (re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"), "私钥块"),
    (re.compile(r"\bgAAAA[A-Za-z0-9_\-]{40,}"), "Fernet 加密令牌"),
    # vless/trojan/vmess/hy2 的分享链接必有 userinfo@host（ss:// 旧格式可能无 @，
    # 但裸协议名只出现在文档里，要求 @ 避免把格式说明当凭据）
    (re.compile(r"\b(?:vless|trojan|vmess|hysteria2?|hy2)://[^\s'\"<>/]{4,}@"), "带凭据的代理分享链接"),
    (re.compile(r"\bss://[A-Za-z0-9+/=_\-]{12,}@[A-Za-z0-9.\-]+"), "带凭据的代理分享链接"),
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
    is_test_fixture = "/tests/" in path or path.startswith("tests/")
    # 扫描器自测文件里必须有完整凭据样例（它就是测这个的），整文件豁免
    is_scanner_self_test = path.endswith("test_secrets_scanner.py")

    for pattern, label in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            # 块级模式（私钥等）无捕获组：命中即整个匹配
            value = m.group(1) if m.groups() else m.group(0)
            if PLACEHOLDER.match(value) or PLACEHOLDER_HINT.search(value):
                continue
            # 测试文件里的 fixture（假私钥 / example.com 假链接）不算事故：
            # 解析测试必须放 URI 素材，域名一律用 example.com 惯例
            if is_scanner_self_test or (
                    is_test_fixture
                    and (("PRIVATE KEY" in value and not re.search(r"[A-Za-z0-9+/]{200,}", value))
                         or "example.com" in value)):
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
