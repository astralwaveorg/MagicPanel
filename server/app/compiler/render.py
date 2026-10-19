"""按目标渲染完整配置。

产物中的 `{FEED}` 占位符由分发层在响应时替换为设备专属地址，
构建产物本身不含任何令牌或节点凭据。
"""
import yaml

from .. import config

DNS_MIHOOMO = {
    "enable": True,
    "ipv6": False,
    "enhanced-mode": "fake-ip",
    "fake-ip-range": "198.18.0.1/16",
    "default-nameserver": ["223.5.5.5", "119.29.29.29"],
    "nameserver": [
        "https://dns.alidns.com/dns-query",
        "https://doh.pub/dns-query",
    ],
    "proxy-server-nameserver": ["223.5.5.5", "119.29.29.29"],
    "nameserver-policy": {
        "+.lan": "system",
        "+.local": "system",
        "+.home.arpa": "system",
    },
    "fake-ip-filter": [
        "+.lan", "+.local", "+.home.arpa", "localhost",
        "localhost.ptlogin2.qq.com", "+.msftconnecttest.com", "+.msftncsi.com",
        "time.*.com", "+.ntp.org", "+.ntp.org.cn",
    ],
}

HEALTH_CHECK = {
    "enable": True,
    "url": "https://www.gstatic.com/generate_204",
    "interval": 600,
    "timeout": 8000,
    "lazy": True,
    "expected-status": 204,
}


def _guard_proxy() -> dict:
    return {
        "name": config.GUARD_PROXY,
        "type": "http",
        "server": "127.0.0.1",
        "port": 1,
        "benchmark-url": "https://www.gstatic.com/generate_204",
        "benchmark-timeout": 1,
    }


def _provider_entry(src: dict, engine: str) -> dict:
    # Mihomo 鉴权字段为 header，Stash 为 headers，值相同、分别生成。
    entry = {
        "type": "http",
        "url": f"{{FEED}}/res/provider/{src['name']}",
        "path": f"./providers/{src['name']}.yaml",
        "interval": src["interval"],
        "health-check": dict(HEALTH_CHECK),
        "benchmark-url": "https://www.gstatic.com/generate_204",
        "benchmark-timeout": 8,
    }
    if src.get("filter"):
        entry["filter"] = src["filter"]
    # Mihomo 的 header 值是字符串列表；Stash 的 headers 值是字符串
    if engine == "stash":
        entry["headers"] = {"User-Agent": src.get("ua") or config.DEFAULT_UA}
    else:
        entry["header"] = {"User-Agent": [src.get("ua") or config.DEFAULT_UA]}
    return entry


def _group_entry(group: dict, engine: str) -> dict:
    entry = {"name": group["name"], "type": group["type"]}
    proxies = list(group.get("proxies") or [])
    use = list(group.get("use_sources") or [])
    if group["type"] in ("url-test", "fallback", "load-balance") \
            and config.GUARD_PROXY not in proxies:
        proxies.insert(0, config.GUARD_PROXY)
    if proxies:
        entry["proxies"] = proxies
    if use:
        entry["use"] = use
    if group.get("filter"):
        entry["filter"] = group["filter"]
    if group.get("hidden"):
        entry["hidden"] = True
    if group["type"] in ("url-test", "fallback", "load-balance"):
        entry["url"] = group.get("url") or HEALTH_CHECK["url"]
        entry["interval"] = group.get("interval", 600)
        entry["timeout"] = group.get("timeout", 8000)
        if group.get("lazy"):
            entry["lazy"] = True
        if group["type"] == "url-test" and group.get("tolerance"):
            entry["tolerance"] = group["tolerance"]
        # strategy 为 Mihomo 扩展字段，Stash 不识别，仅 Mihomo 目标输出
        if group["type"] == "load-balance" and group.get("strategy") \
                and engine == "mihomo":
            entry["strategy"] = group["strategy"]
    if group["type"] == "relay":
        # Stash 链式转发用 benchmark-* 字段测速；Mihomo 沿用 url/interval
        if engine == "stash":
            entry["benchmark-url"] = group.get("url") or HEALTH_CHECK["url"]
            entry["benchmark-timeout"] = max(1, group.get("timeout", 8000) // 1000)
        else:
            entry["url"] = group.get("url") or HEALTH_CHECK["url"]
            entry["interval"] = group.get("interval", 600)
    return entry


def _rule_line(rule: dict) -> str:
    if rule["type"] in ("MATCH", "FINAL"):
        return f"MATCH,{rule['target']}"
    return f"{rule['type']},{rule['value']},{rule['target']}"


def _rule_provider_entry(rp: dict) -> dict:
    entry = {
        "type": "http",
        "url": f"{{FEED}}/res/rule/{rp['name']}",
        "path": f"./rules/{rp['name']}.yaml",
        "behavior": rp["behavior"],
        "interval": rp["interval"],
    }
    if rp.get("format") and rp["format"] != "yaml":
        entry["format"] = rp["format"]
    return entry


def _merge(dst: dict, src: dict) -> None:
    """深度合并：字典递归、列表追加、标量覆盖。"""
    for key, value in src.items():
        if key in dst and isinstance(dst[key], dict) and isinstance(value, dict):
            _merge(dst[key], value)
        elif key in dst and isinstance(dst[key], list) and isinstance(value, list):
            dst[key] = dst[key] + value
        else:
            dst[key] = value


def render_target(snapshot: dict, target: dict) -> str:
    """渲染单个目标的完整配置文本。"""
    engine = target["engine"]
    cfg: dict = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "profile": {"store-selected": True, "store-fake-ip": True},
        "proxies": [_guard_proxy()],
    }

    sources = [s for s in snapshot["sources"] if s.get("enabled")]
    if sources:
        cfg["proxy-providers"] = {
            s["name"]: _provider_entry(s, engine) for s in sources
        }

    groups = snapshot["groups"]
    if groups:
        cfg["proxy-groups"] = [_group_entry(g, engine) for g in groups]

    rps = [r for r in snapshot["rule_providers"] if r.get("enabled")]
    if rps:
        cfg["rule-providers"] = {r["name"]: _rule_provider_entry(r) for r in rps}

    rules = [r for r in snapshot["rules"] if r.get("enabled", True)]
    cfg["rules"] = [_rule_line(r) for r in rules]

    # Stash 由客户端接管 DNS；Mihomo 需要显式 dns 段。
    if engine == "mihomo":
        cfg["dns"] = dict(DNS_MIHOOMO)

    # 功能模块按引擎合并，目标扩展最后应用、优先级最高
    for snip in snapshot.get("snippets", []):
        if snip["engine"] in (engine, "all"):
            _merge(cfg, yaml.safe_load(snip["content"]) or {})

    extra = (target.get("extra_yaml") or "").strip()
    if extra:
        overlay = yaml.safe_load(extra) or {}
        if isinstance(overlay, dict):
            _merge(cfg, overlay)

    return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=4096)


def substitute_feed(text: str, feed_base: str) -> str:
    return text.replace("{FEED}", feed_base)
