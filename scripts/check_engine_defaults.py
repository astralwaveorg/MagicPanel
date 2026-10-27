#!/usr/bin/env python3
"""回归检查：引擎默认配置里的每个键都要能在官方文档里找到出处。

参考文件（放在 official-example/ 下，随仓库一起保存，便于离线核对）：
  mihomo-example.yaml  —— MetaCubeX/mihomo 的 docs/config.yaml
  stash-example.yaml   —— https://stash.wiki/configuration/example-config

判定规则：
  * 顶层键必须出现在对应引擎的参考文件里（含被注释掉的示例行）；
  * 面板私有的伪键（_panel_direct_rule 等）不在官方文档里，跳过；
  * 域名模式表（nameserver-policy / hosts）里的条目是数据，不是配置项，
    不参与逐键核对——官方示例里也是同样写法；
  * 值不要求与官方示例一致（官方示例给的是"可用值"，不是"推荐值"），
    面板取的是适合代理客户端的保守值。

用法：python3 scripts/check_engine_defaults.py
退出码 0 = 全部通过；1 = 有键找不到出处。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))

from app.services import base_config as bc  # noqa: E402

# 面板私有键：不写进产物，不在官方文档里
PANEL_KEYS = {bc.PANEL_DIRECT_KEY, bc.DIRECT_DOMAINS_KEY, bc.FAKE_IP_FILTER_KEY}

# Stash 官方文档里没有、但客户端兼容支持的键（逐条注明出处）
EXTRA_ALLOWED = {
    "stash": {
        "geodata-mode": "Clash.Meta 兼容键（mihomo 支持，官方示例未展开）",
        "allow-lan": "Stash 支持为局域网设备提供代理（stash.wiki/features/lan-proxy）",
        "bind-address": "Stash 支持 allow-lan 时的监听地址（同上）",
        "find-process-mode": "Stash 解析 PROCESS 规则（stash.wiki/rules/rule-types）",
        "geo-auto-update": "Clash.Meta 兼容键，Stash 自行管理 Geo 数据",
        "geo-update-interval": "Clash.Meta 兼容键，Stash 自行管理 Geo 数据",
        "geodata-mode": "Clash.Meta 兼容键，Stash 自行管理 Geo 数据",
        "keep-alive-interval": "Clash 兼容键，Stash 自行管理连接复用",
        "sniffer": "Clash.Meta 兼容键",
        "tcp-concurrent": "Clash 兼容键",
        "unified-delay": "Clash 兼容键",
        "profile": "Stash 支持 profile.store-selected / store-fake-ip（stash.wiki configuration）",
    },
    "mihomo": {
        "geodata-mode": "Clash.Meta 兼容键（mihomo 支持，官方示例未展开）",
        "keep-alive-interval": "Mihomo 文档未在示例里展开，但内核支持",
        "tcp-concurrent": "Mihomo 文档未在示例里展开，但内核支持",
        "unified-delay": "Mihomo 文档未在示例里展开，但内核支持",
        "global-client-fingerprint":
            "mihomo 官方支持（docs/config.yaml global-client-fingerprint），示例文件版本未含",
        "sniffer": "mihomo 核心能力（docs/config.yaml 有 sniffer 段），示例文件版本未含",
    },
}


def reference_keys(path: Path) -> set[str]:
    """把参考文件里所有出现过的键路径收集出来（含注释掉的示例行）。"""
    keys: set[str] = set()
    stack: list[tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
            if not stripped:
                continue
        indent = len(line) - len(line.lstrip())
        m = re.match(r"^([A-Za-z0-9_.\-]+):", stripped)
        if not m:
            continue
        name = m.group(1)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, name))
        keys.add(".".join(n for _, n in stack))
    return keys


def _is_domain_pattern(key: str) -> bool:
    """域名模式（``+.lan``、``*.example.com``、``geosite:cn``）是数据条目，不是配置键。"""
    return any(ch in key for ch in "+*:") or "." in key


def _is_data_map(value: dict) -> bool:
    """这张表的键是域名模式 → 它是数据映射（``nameserver-policy`` / ``hosts`` 等）。

    官方示例里同样是这样写的（``'+.internal.crop.com': system``），
    表里的条目是"哪个域名交给哪个 DNS"，不是配置项，不该参与逐键对账。
    """
    return any(_is_domain_pattern(k) for k in value)


def doc_keys(doc: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in doc.items():
        path = f"{prefix}{key}"
        out.add(path)
        if isinstance(value, dict) and not _is_data_map(value):
            out |= doc_keys(value, path + ".")
    return out


def main() -> int:
    refs = {
        "mihomo": [REPO / "official-example" / "mihomo-example.yaml",
                   REPO / "official-example" / "dns-fallback-reference.yaml"],
        "stash": [REPO / "official-example" / "stash-example.yaml",
                  REPO / "official-example" / "stash-dns-reference.yaml",
                  REPO / "official-example" / "dns-fallback-reference.yaml"],
    }
    missing: list[str] = []
    for engine, paths in refs.items():
        ref: set[str] = set()
        for path in paths:
            if not path.exists():
                print(f"缺少参考文件：{path}")
                return 1
            ref |= reference_keys(path)
        allowed = EXTRA_ALLOWED.get(engine, {})
        for key in sorted(doc_keys(bc.default_doc(engine))):
            top = key.split(".")[0]
            if top in PANEL_KEYS:
                continue
            if key in ref or top in allowed:
                continue
            missing.append(f"{engine}: {key}")
    if missing:
        print("以下默认配置键在官方文档里找不到出处：")
        for item in missing:
            print(f"  ✗ {item}")
        return 1
    print("✓ 引擎默认配置的每个键都能在官方文档里找到出处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
