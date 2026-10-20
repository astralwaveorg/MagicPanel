"""按目标渲染完整配置。

产物中的 `{FEED}` 占位符由分发层在响应时替换为设备专属地址，
`{FEED_HOST}` 替换为面板域名（用于置顶 DIRECT 规则）。
订阅来源仍以 provider 占位引用；本地单节点的凭据会直接写入产物，
因此构建产物与 builds 快照都包含本地节点凭据，不能公开分发。
"""
import urllib.parse

import yaml

from .. import config
from ..services import base_config as base_config_service
from ..services import local_nodes as local_node_service

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


def _guard_proxy(engine: str = "stash") -> dict:
    entry = {
        "name": config.GUARD_PROXY,
        "type": "http",
        "server": "127.0.0.1",
        "port": 1,
    }
    if engine == "stash":
        # Stash 的单节点延迟测试参数；Mihomo 没有对应字段（组级 url 生效）
        entry["benchmark-url"] = "https://www.gstatic.com/generate_204"
        entry["benchmark-timeout"] = 1
    return entry


def _provider_entry(src: dict, engine: str) -> dict:
    # Mihomo 鉴权字段为 header，Stash 为 headers，值相同、分别生成。
    entry = {
        "type": "http",
        "url": f"{{FEED}}/res/provider/{src['name']}",
        "path": f"./providers/{src['name']}.yaml",
        "interval": src.get("client_interval") or src["interval"],
    }
    if src.get("filter"):
        entry["filter"] = src["filter"]
    if engine == "stash":
        # Stash 官方：集合级延迟测试参数用 benchmark-url / benchmark-timeout
        entry["headers"] = {"User-Agent": src.get("ua") or config.DEFAULT_UA}
        entry["benchmark-url"] = HEALTH_CHECK["url"]
        entry["benchmark-timeout"] = 8
    else:
        # Mihomo 官方：健康检查用 health-check，鉴权头值是字符串列表
        entry["header"] = {"User-Agent": [src.get("ua") or config.DEFAULT_UA]}
        entry["health-check"] = dict(HEALTH_CHECK)
    return entry


def _group_entry(group: dict, engine: str, local_names: list[str] | None = None) -> dict:
    entry = {"name": group["name"], "type": group["type"]}
    proxies = list(group.get("proxies") or []) + list(local_names or [])
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
        entry["interval"] = group.get("interval", 600)
        if group.get("lazy"):
            entry["lazy"] = True
        if group["type"] == "url-test" and group.get("tolerance"):
            entry["tolerance"] = group["tolerance"]
        if group["type"] == "load-balance" and group.get("strategy"):
            # Stash 只支持 consistent-hashing / round-robin
            if engine == "stash":
                strategy = group["strategy"]
                if strategy not in ("consistent-hashing", "round-robin"):
                    strategy = "consistent-hashing"
                entry["strategy"] = strategy
            else:
                entry["strategy"] = group["strategy"]
        if engine != "stash":
            # Stash 策略组没有 url / timeout 字段，测速参数来自节点与集合
            entry["url"] = group.get("url") or HEALTH_CHECK["url"]
            entry["timeout"] = group.get("timeout", 8000)
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
    line = f"{rule['type']},{rule['value']},{rule['target']}"
    if rule.get("no_resolve") and rule["type"] in config.NO_RESOLVE_TYPES:
        line += ",no-resolve"
    return line


def _rule_provider_entry(rp: dict) -> dict:
    entry = {
        "type": "http",
        "url": f"{{FEED}}/res/rule/{rp['name']}",
        "path": f"./rules/{rp['name']}.yaml",
        "behavior": rp["behavior"],
        "interval": rp.get("client_interval") or rp["interval"],
    }
    if rp.get("format") and rp["format"] != "yaml":
        entry["format"] = rp["format"]
    return entry


def _merge_dns(base: dict, override: dict) -> dict:
    """DNS 段：字典递归覆盖，列表整体替换（用户填写的为准）。"""
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dns(result[key], value)
        else:
            result[key] = value
    return result


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
    # ① 基础配置（按引擎，来自构建快照，保证构建可复现）
    base = base_config_service.normalize(
        (snapshot.get("base") or {}).get(engine) or {})
    cfg: dict = base_config_service.ordered(base)

    local_enabled = {
        node["id"]: node for node in snapshot.get("local_nodes", [])
        if node.get("enabled")
    }
    cfg["proxies"] = [_guard_proxy(engine)]
    for node in local_enabled.values():
        cfg["proxies"].append(local_node_service.render_proxy(node, engine))

    sources = [s for s in snapshot["sources"] if s.get("enabled")]
    if sources:
        cfg["proxy-providers"] = {
            s["name"]: _provider_entry(s, engine) for s in sources
        }

    groups = snapshot["groups"]
    if groups:
        cfg["proxy-groups"] = []
        for group in groups:
            names = [
                local_node_service.marked_name(local_enabled[node_id]["name"])
                for node_id in (group.get("local_nodes") or [])
                if node_id in local_enabled
            ]
            cfg["proxy-groups"].append(_group_entry(group, engine, names))

    rps = [r for r in snapshot["rule_providers"] if r.get("enabled")]
    if rps:
        cfg["rule-providers"] = {r["name"]: _rule_provider_entry(r) for r in rps}

    rules = [r for r in snapshot["rules"] if r.get("enabled", True)]
    # 面板自身域名强制直连且置顶：VPN 运行中客户端更新配置不经过代理，
    # 避免节点失效导致配置无法更新（TLS 握手失败）。{FEED_HOST} 分发时替换。
    cfg["rules"] = ["DOMAIN-SUFFIX,{FEED_HOST},DIRECT"] + [_rule_line(r) for r in rules]

    # Stash 由客户端接管 DNS；Mihomo 需要显式 dns 段。
    # 用户在基础配置里写了 dns 则逐项覆盖默认值（列表以用户为准）。
    if engine == "mihomo":
        user_dns = base.get("dns") or {}
        cfg["dns"] = _merge_dns(DNS_MIHOOMO, user_dns)

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
    host = urllib.parse.urlsplit(feed_base).hostname or ""
    return text.replace("{FEED}", feed_base).replace("{FEED_HOST}", host)
