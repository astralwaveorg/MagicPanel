#!/usr/bin/env python3
"""从参考配置生成种子数据 payload（JSON 写 stdout）。

用法：scripts/build_seed.py "Stash 真实配置文件示例/Clash Config.yaml" > /tmp/seed.json
清洗规则：去除空组保护占位（渲染层自动插入）、修正坏行、
raw.githubusercontent.com 改写为 jsDelivr（NAS 到 GitHub 裸域不可达）、
节点来源用 SRC:<关键字> 符号，由 apply_seed.py 按实际来源名解析。
"""
import json
import re
import sys

import yaml

SRC_KEYWORDS = {"神龙机场": "SRC:神龙", "白月光": "SRC:白月光", "牛逼机场": "SRC:牛逼"}

# 参考配置中的坏行与替换
RULE_REPLACEMENTS = {
    # 原行带端口与尾部空格，且 no-track 不是有效修饰符
    ("DOMAIN-SUFFIX", "homehub.stream:8443"): ("DOMAIN-SUFFIX", "homehub.stream", "DIRECT", False),
}

# 用户已手工添加的 classical 规则来源，挂到对应策略组
EXTRA_RULES_AFTER = {
    "google": ("RULE-SET", "Google", "谷歌服务"),
    "github": ("RULE-SET", "GitHub", "开发服务"),
}


def cdn_url(url: str) -> str:
    m = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)", url)
    if m:
        owner, repo, branch, path = m.groups()
        return f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}"
    return url


def clean_filter(expr: str | None) -> str:
    if not expr:
        return ""
    # 空组保护是渲染层占位节点，不属于任何 provider，过滤表达式里无意义
    return re.sub(r"^\(\?i\)空组保护\|", "(?i)", expr)


def main(path: str) -> None:
    doc = yaml.safe_load(open(path, encoding="utf-8"))

    providers = []
    for name, rp in (doc.get("rule-providers") or {}).items():
        providers.append({
            "name": name,
            "behavior": rp.get("behavior", "domain"),
            "format": rp.get("format", "yaml"),
            "url": cdn_url(rp["url"]),
            "interval": int(rp.get("interval", 86400)),
        })

    groups = []
    for g in doc.get("proxy-groups") or []:
        use = [SRC_KEYWORDS.get(u, u) for u in (g.get("use") or [])]
        proxies = [p for p in (g.get("proxies") or []) if p != "空组保护"]
        groups.append({
            "name": g["name"],
            "type": g["type"],
            "hidden": bool(g.get("hidden")),
            "filter": clean_filter(g.get("filter")),
            "use_sources": use,
            "proxies": proxies,
            "url": g.get("url") or "https://www.gstatic.com/generate_204",
            "interval": int(g.get("interval", 600)),
            "timeout": int(g.get("timeout", 8000)),
            "tolerance": int(g.get("tolerance", 150)),
            "lazy": bool(g.get("lazy", True)),
        })

    rules = []
    for raw in doc.get("rules") or []:
        parts = [p.strip() for p in str(raw).split(",")]
        rtype = parts[0].upper()
        if rtype in ("MATCH", "FINAL"):
            rules.append({"type": "MATCH", "value": "", "target": parts[-1],
                          "no_resolve": False, "note": "兜底"})
            continue
        value, target = parts[1], parts[2]
        no_resolve = "no-resolve" in [p.lower() for p in parts[3:]]
        key = (rtype, value)
        if key in RULE_REPLACEMENTS:
            rtype, value, target, no_resolve = RULE_REPLACEMENTS[key]
            note = "家庭域名直连（修正原配置的端口与尾部空格）"
        else:
            note = ""
        rules.append({"type": rtype, "value": value, "target": target,
                      "no_resolve": no_resolve, "note": note})
        extra = EXTRA_RULES_AFTER.get(value if rtype == "RULE-SET" else None)
        if rtype == "RULE-SET" and extra:
            rules.append({"type": extra[0], "value": extra[1], "target": extra[2],
                          "no_resolve": False, "note": "classical 版补充"})

    targets = [
        {"name": "stash-ios", "engine": "stash", "platform": "ios", "description": "iPhone / iPad"},
        {"name": "stash-macos", "engine": "stash", "platform": "macos", "description": "Mac"},
        {"name": "mihomo-android", "engine": "mihomo", "platform": "android",
         "description": "Android（FlClash）"},
        {"name": "mihomo-windows", "engine": "mihomo", "platform": "windows",
         "description": "Windows（Clash Verge Rev）"},
    ]

    json.dump({"rule_providers": providers, "groups": groups,
               "rules": rules, "targets": targets},
              sys.stdout, ensure_ascii=False, indent=1)
    print(f"payload: {len(providers)} 规则来源 / {len(groups)} 策略组 / "
          f"{len(rules)} 规则 / {len(targets)} 目标", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("用法：build_seed.py <参考配置.yaml>")
    main(sys.argv[1])
