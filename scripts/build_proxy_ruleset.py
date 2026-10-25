#!/usr/bin/env python3
"""生成 blackmatrix7 Proxy 规则集的"去重版"内联内容。

背景
----
《Proxy》《Proxy_Domain》把多个上游规则源合并成一份"必须走代理"的清单，
直接用会跟面板里已有的分流规则抢流量：Proxy 规则排在业务规则之前，
凡是能被现有集合匹配的域名都会被它先命中、抢走——OpenAI/Claude 会从
「🧠 人工智能」掉到「🚀 默认代理」，Google 会从「🔍 谷歌服务」掉到默认
代理，v2ex 这类国内站会被从直连拽到代理。

做法
----
只保留"现有配置完全没有覆盖、且确实需要强制代理"的部分：把面板现有
每个规则集合的域名/后缀/关键词/IP 段取出来，按语义覆盖关系剔除 Proxy
里与之重叠的条目。判据按匹配语义算，不写死任何分类名或域名清单，
所以面板规则一改，重跑一次就跟上。

用法
----
    MAGICPANEL_COOKIE='mp_session=...' MAGICPANEL_CSRF='...' \
        python3 scripts/build_proxy_ruleset.py            # 只看统计
    ... python3 scripts/build_proxy_ruleset.py --apply    # 生成到 /tmp

产物：
    /tmp/mp_inline_proxy.yaml          classical 版的 payload
    /tmp/mp_inline_proxy-domain.yaml   domain 版的 payload
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import urllib.error

import yaml

PANEL = os.environ.get("MAGICPANEL_URL", "https://magichub.top:8443")
COOKIE = os.environ.get("MAGICPANEL_COOKIE", "")
CSRF = os.environ.get("MAGICPANEL_CSRF", "")
CDN = ("https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/"
       "rule/Clash/")
# 这两个集合本身是产物，不参与"现有覆盖"的计算
SELF = set(filter(None, os.environ.get(
    "PROXY_SET_NAMES", "proxy,proxy-domain").split(",")))


def http_json(path: str) -> dict:
    req = urllib.request.Request(PANEL + path)
    req.add_header("Cookie", COOKIE)
    req.add_header("X-CSRF-Token", CSRF)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def cdn_payload(path: str) -> list[str]:
    req = urllib.request.Request(CDN + path, headers={"User-Agent": "Clash/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        doc = yaml.safe_load(r.read().decode()) or {}
    return [str(x) for x in (doc.get("payload") or [])]


def parents(domain: str) -> list[str]:
    parts = domain.split(".")
    return [".".join(parts[i:]) for i in range(1, len(parts))]


def split_domains(items: list[str]) -> tuple[set, set, set]:
    """把集合内容拆成 (精确域名, 后缀域名, 关键词)。"""
    exact: set = set()
    suffix: set = set()
    keywords: set = set()
    for item in items:
        text = item.strip()
        if "," in text:
            parts = text.split(",")
            kind = parts[0].strip().upper()
            value = parts[1].strip() if len(parts) > 1 else ""
            if kind == "DOMAIN" and value:
                exact.add(value.lower())
            elif kind == "DOMAIN-SUFFIX" and value:
                suffix.add(value.lower())
            elif kind == "DOMAIN-KEYWORD" and value:
                keywords.add(value.lower())
        elif text.startswith("+."):
            suffix.add(text[2:].lower())
        elif text:
            exact.add(text.lower())
    return exact, suffix, keywords


def cidr_of(items: list[str]) -> set:
    out = set()
    for item in items:
        text = item.strip().lstrip("- ").strip()
        if not text:
            continue
        value = text.split(",")[0].strip()
        if "/" in value:
            out.add(value)
    return out


def collect_existing() -> tuple[set, set, set, set]:
    """面板现有（启用中）规则集合覆盖的域名、后缀、关键词、IP 段。"""
    exact: set = set()
    suffix: set = set()
    keywords: set = set()
    cidrs: set = set()
    providers = http_json("/api/v1/rule-providers")
    providers = providers.get("items", providers) if isinstance(providers, dict) else providers
    for rp in providers:
        if not rp.get("enabled") or rp.get("name") in SELF:
            continue
        content = http_json("/api/v1/rule-providers/%d/content" % rp["id"]).get("content", "")
        items = [ln.strip()[2:].strip() for ln in content.splitlines() if ln.strip().startswith("- ")]
        ex, su, kw = split_domains(items)
        exact |= ex
        suffix |= su
        keywords |= kw
        cidrs |= cidr_of(items)
    return exact, suffix, keywords, cidrs


def main() -> int:
    if not COOKIE or not CSRF:
        print("需要 MAGICPANEL_COOKIE 与 MAGICPANEL_CSRF 环境变量", file=sys.stderr)
        return 2
    apply = "--apply" in sys.argv

    proxy_items = cdn_payload("Proxy/Proxy.yaml")
    domain_items = cdn_payload("Proxy/Proxy_Domain.yaml")
    e_exact, e_suffix, e_kw, e_cidr = collect_existing()
    print("现有集合覆盖：精确域名 %d | 后缀域名 %d | 关键词 %d | IP 段 %d"
          % (len(e_exact), len(e_suffix), len(e_kw), len(e_cidr)))

    def covered_exact(name: str) -> bool:
        """精确域名：被同名的精确条目，或被某个后缀条目覆盖 → 冗余。"""
        return name in e_exact or any(p in e_suffix for p in parents(name))

    def covered_suffix(name: str) -> bool:
        """后缀域名：被同范围、更宽范围（完全覆盖），或更窄范围（部分覆盖）命中 → 冗余。"""
        if name in e_suffix:
            return True
        # 更宽的后缀 E 覆盖了 name 的全部（E 是 name 的祖先后缀）→ 完全冗余
        if any(p in e_suffix for p in parents(name)):
            return True
        # 更窄的后缀只覆盖一部分：保守起见也剔除，避免抢现有分流
        return any(e.endswith("." + name) for e in e_suffix)

    kept_domain, dropped_domain = [], []
    for item in domain_items:
        text = item.strip()
        if text.startswith("+."):
            hit = covered_suffix(text[2:].lower())
        else:
            hit = covered_exact(text.lower())
        (dropped_domain if hit else kept_domain).append(item)

    kept_proxy, dropped_kw, dropped_cidr = [], [], []
    for item in proxy_items:
        if "," in item:
            parts = item.split(",")
            kind = parts[0].strip().upper()
            value = parts[1].strip() if len(parts) > 1 else ""
            if kind == "DOMAIN-KEYWORD":
                key = value.lower()
                if any(key in e for e in e_exact) or any(key in e for e in e_suffix):
                    dropped_kw.append(value)
                    continue
            elif kind in ("IP-CIDR", "IP-CIDR6") and value in e_cidr:
                dropped_cidr.append(value)
                continue
        kept_proxy.append(item)

    print("Proxy_Domain: %d → %d（剔除 %d）" % (len(domain_items), len(kept_domain), len(dropped_domain)))
    print("Proxy:        %d → %d（剔除关键词 %d、重复 IP 段 %d）"
          % (len(proxy_items), len(kept_proxy), len(dropped_kw), len(dropped_cidr)))
    if dropped_kw:
        print("  剔除的关键词:", "、".join(dropped_kw))

    if not apply:
        print("（加 --apply 生成文件）")
        return 0
    out = {
        "proxy": "payload:\n" + "".join("- %s\n" % x for x in kept_proxy),
        "proxy-domain": "payload:\n" + "".join("- %s\n" % x for x in kept_domain),
    }
    for name, text in out.items():
        path = "/tmp/mp_inline_%s.yaml" % name
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("已写 %s（%d 字节）" % (path, len(text)))
    with open("/tmp/mp_inline_cut.json", "w", encoding="utf-8") as f:
        json.dump({"dropped_domain": dropped_domain, "dropped_kw": dropped_kw,
                   "dropped_cidr": dropped_cidr}, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
