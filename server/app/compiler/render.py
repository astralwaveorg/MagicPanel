"""按目标渲染完整配置。

产物中的 `{FEED}` 占位符由分发层在响应时替换为设备专属地址，
`{FEED_HOST}` 替换为面板域名（用于置顶 DIRECT 规则）。
订阅来源仍以 provider 占位引用；本地单节点的凭据会直接写入产物，
因此构建产物与 builds 快照都包含本地节点凭据，不能公开分发。

差异化维度（自下而上叠加）：
① 基础配置：引擎默认 → 目标级覆盖
② 结构内容：策略组与分流规则按「适用目标」过滤，并按平台能力剔除必然无效的规则
③ 功能模块：按引擎过滤
④ 目标扩展：目标 extra_yaml
（⑤ 设备级覆盖在分发层叠加，见 routers/feed.py）
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

# 平台能力（依据官方文档）：
# - Stash 官方原文：「由于 Network Extension 的限制，Stash iOS/tvOS 不支持
#   PROCESS-NAME / PROCESS-PATH 规则，配置中的进程相关规则将被忽略」
#   https://stash.wiki/rules/rule-types
# - Mihomo 在 Android 上 PROCESS-NAME 可匹配包名（官方明确可用），故不裁剪
# 说明：Stash 的 Windows / Android 属于早期版本，官方文档尚未收录，
# 因此不做裁剪（保持与 Clash 兼容的行为），只对官方明确说明的平台裁剪。
PLATFORM_UNSUPPORTED_RULES = {
    ("stash", "ios"): {"PROCESS-NAME", "PROCESS-PATH"},
    ("stash", "tvos"): {"PROCESS-NAME", "PROCESS-PATH"},
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
        "url": f"{{FEED}}/res/provider/{urllib.parse.quote(src['name'])}",
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
    # 本地单节点可以排在最前（"优先美国"这类组用得上：机房节点先试，
    # 机场节点兜底）。local_nodes 本身是有序的 id 列表，顺序即优先级。
    if group.get("local_first"):
        proxies = list(local_names or []) + list(group.get("proxies") or [])
    else:
        proxies = list(group.get("proxies") or []) + list(local_names or [])
    use = list(group.get("use_sources") or [])
    if group["type"] in ("url-test", "fallback", "load-balance") \
            and config.GUARD_PROXY not in proxies:
        # 放在末尾而不是开头：占位节点永远连不通（127.0.0.1:1），
        # 它的作用只是让组非空，防止客户端把空组隐式改写成 DIRECT。
        # 放末尾可保证任何客户端（哪怕不做健康检查直接取第一个成员）
        # 拿到的都是真实节点，而不是这个占位。
        proxies.append(config.GUARD_PROXY)
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
        "url": f"{{FEED}}/res/rule/{urllib.parse.quote(rp['name'])}",
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


def applies_to(item: dict, target_name: str) -> bool:
    """策略组 / 规则是否适用于该目标：未指定则适用于全部目标。"""
    scope = item.get("targets") or []
    if not scope:
        return True
    return target_name in scope


def _select_structure(snapshot: dict, target: dict, warnings: list | None) -> tuple[list, list]:
    """按目标过滤策略组与规则，并剔除当前平台必然无效的规则。

    安全约束：
    1. 兜底规则（MATCH/FINAL）永远保留，其指向的策略组强制保留；
    2. 指向不存在策略组的规则自动丢弃（客户端加载即失败，必须杜绝）；
    3. 策略组成员里引用了不存在策略组的成员一并剔除。
    """
    target_name = target.get("name") or ""
    engine = target.get("engine") or ""
    platform = (target.get("platform") or "").lower()
    unsupported = PLATFORM_UNSUPPORTED_RULES.get((engine, platform), set())

    # 复制一份再改，避免污染快照（同一快照会渲染多个目标）
    groups = [dict(g, proxies=list(g.get("proxies") or []))
              for g in snapshot.get("groups", []) if applies_to(g, target_name)]
    rules = [r for r in snapshot.get("rules", []) if r.get("enabled", True)
             and applies_to(r, target_name)]

    trimmed = [r for r in rules if r["type"] in unsupported]
    if trimmed and warnings is not None:
        warnings.append(
            f"已按 {engine}/{platform} 剔除 {len(trimmed)} 条进程类规则"
            f"（该平台不提供进程信息）："
            + "、".join(sorted({r["type"] for r in trimmed})))
    rules = [r for r in rules if r["type"] not in unsupported]

    # 兜底规则永远保留，其目标组必须存在，否则产物没有兜底、客户端无法加载
    final_rules = [r for r in rules if r["type"] in ("MATCH", "FINAL")]
    keep_groups = {r["target"] for r in final_rules}
    group_names = {g["name"] for g in groups}
    for name in keep_groups:
        if name in group_names or name in config.BUILTIN_TARGETS:
            continue
        original = next((g for g in snapshot.get("groups", [])
                         if g["name"] == name), None)
        if original:
            groups.append(dict(original, proxies=list(original.get("proxies") or [])))
            group_names.add(name)
            if warnings is not None:
                warnings.append(f"兜底规则目标组“{name}”已强制保留到本目标")

    # 剔除指向不存在策略组的规则（客户端加载时会直接报错）；兜底规则始终保留
    kept_rules = []
    for r in rules:
        ref = r.get("target")
        if r["type"] in ("MATCH", "FINAL") \
                or ref in config.BUILTIN_TARGETS or ref in group_names:
            kept_rules.append(r)
        else:
            if warnings is not None:
                warnings.append(
                    f"规则 {r['type']},{r.get('value', '')} 指向的策略组"
                    f"“{ref}”不适用于本目标，已剔除")
    rules = kept_rules

    # 兜底规则（MATCH/FINAL）必须排在最后：客户端是"从上往下第一条命中即生效"，
    # 兜底之后的规则永远匹配不到。管理界面上规则的排列顺序可以随意，
    # 产物里统一把兜底规则提到末尾，避免用户新增的规则被兜底吃掉。
    finals = [r for r in rules if r["type"] in ("MATCH", "FINAL")]
    if finals:
        rest = [r for r in rules if r["type"] not in ("MATCH", "FINAL")]
        moved = len(rules) - len(rest) - len(finals)
        rules = rest + finals
        if warnings is not None:
            if moved:
                warnings.append(
                    f"兜底规则（MATCH/FINAL）已自动移到产物末尾，"
                    f"其后 {moved} 条规则原本永远匹配不到，现已生效")
            if len(finals) > 1:
                warnings.append(
                    f"存在 {len(finals)} 条兜底规则（MATCH/FINAL），"
                    "客户端只认第一条，其余不会生效")

    # 剔除策略组成员里指向不存在策略组的引用
    for g in groups:
        proxies = [p for p in (g.get("proxies") or [])
                   if p in config.BUILTIN_TARGETS or p in group_names
                   or p == config.GUARD_PROXY]
        if len(proxies) != len(g.get("proxies") or []):
            if warnings is not None:
                warnings.append(
                    f"策略组“{g['name']}”剔除了不适用于本目标的成员引用")
        g["proxies"] = proxies
    return groups, rules


def render_target(snapshot: dict, target: dict, warnings: list | None = None) -> str:
    """渲染单个目标的完整配置文本。"""
    engine = target["engine"]
    # ① 基础配置：系统默认 → 通用配置（引擎+平台）；设备配置在分发时叠加
    layers = [("系统默认", base_config_service.default_doc(engine))]
    platform = target.get("platform") or ""
    general_base = (snapshot.get("base") or {}).get(f"{engine}|{platform}")
    if general_base:
        layers.append(("通用配置", base_config_service.normalize(general_base)))
    base, _sources = base_config_service.cascade(layers)
    # 应用级伪键：不写入产物，只控制面板内置行为
    panel_direct = bool(base.pop(base_config_service.PANEL_DIRECT_KEY, True))
    direct_domains = base_config_service.normalize_domains(
        base.pop(base_config_service.DIRECT_DOMAINS_KEY, None))
    fake_ip_filter = base_config_service.normalize_filter(
        base.pop(base_config_service.FAKE_IP_FILTER_KEY, None))
    cfg: dict = base_config_service.ordered(base)

    groups, rules = _select_structure(snapshot, target, warnings)
    # 本地节点跟随本目标实际生效的策略组，避免把其他设备的私有隧道及密钥
    # 分发给本目标。不能按全局策略组筛选：其中可能包含目标专属的策略组。
    used_local = {
        node_id for group in groups for node_id in (group.get("local_nodes") or [])
    }
    local_enabled = {
        node["id"]: node for node in snapshot.get("local_nodes", [])
        if node.get("enabled") and node["id"] in used_local
    }
    cfg["proxies"] = [_guard_proxy(engine)]
    for node in local_enabled.values():
        cfg["proxies"].append(local_node_service.render_proxy(node, engine))

    sources = [s for s in snapshot["sources"] if s.get("enabled")]
    if sources:
        cfg["proxy-providers"] = {
            s["name"]: _provider_entry(s, engine) for s in sources
        }

    if groups:
        cfg["proxy-groups"] = []
        for group in groups:
            names = [
                local_node_service.display_name(
                    local_enabled[node_id]["name"],
                    local_enabled[node_id].get("node_type") or "")
                for node_id in (group.get("local_nodes") or [])
                if node_id in local_enabled
            ]
            cfg["proxy-groups"].append(_group_entry(group, engine, names))

    rps = [r for r in snapshot["rule_providers"] if r.get("enabled")]
    if rps:
        cfg["rule-providers"] = {r["name"]: _rule_provider_entry(r) for r in rps}

    # 面板自身域名强制直连且置顶：VPN 运行中客户端更新配置不经过代理，
    # 避免节点失效导致配置无法更新（TLS 握手失败）。{FEED_HOST} 分发时替换。
    pinned = ["DOMAIN-SUFFIX,{FEED_HOST},DIRECT"] if panel_direct else []
    # 个人直连域名：置顶在用户规则之前，保证一定先生效
    personal = [f"DOMAIN-SUFFIX,{domain},DIRECT" for domain in direct_domains]
    cfg["rules"] = pinned + personal + [_rule_line(r) for r in rules]

    # Stash 由客户端接管 DNS；Mihomo 需要显式 dns 段。
    # 用户在基础配置里写了 dns 则逐项覆盖默认值（列表以用户为准）。
    user_dns = base.get("dns") or {}
    if engine == "mihomo":
        cfg["dns"] = _merge_dns(DNS_MIHOOMO, user_dns)
        if fake_ip_filter:
            # 个人维护的过滤列表整体替换内置列表
            cfg["dns"]["fake-ip-filter"] = fake_ip_filter
    elif fake_ip_filter:
        # Stash 默认由客户端接管 DNS；只有显式配置了过滤列表才下发 dns 段
        dns = dict(cfg.get("dns") or {})
        dns["fake-ip-filter"] = fake_ip_filter
        cfg["dns"] = dns

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
    """把 {FEED} / {FEED_HOST} 占位符替换成真实地址。

    走结构化替换（解析 YAML → 改字段 → 重新序列化），
    不用裸字符串替换：裸替换遇到带引号或特殊字符的地址会把 YAML 写坏，
    客户端直接加载失败。
    """
    host = urllib.parse.urlsplit(feed_base).hostname or ""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        # 产物不是合法 YAML 时退回文本替换，至少不丢失占位符
        return dedupe_rules(text.replace("{FEED}", feed_base)
                            .replace("{FEED_HOST}", host))
    if not isinstance(data, dict):
        return dedupe_rules(text.replace("{FEED}", feed_base)
                            .replace("{FEED_HOST}", host))
    for section in ("proxy-providers", "rule-providers"):
        entries = data.get(section)
        if isinstance(entries, dict):
            for entry in entries.values():
                if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                    entry["url"] = entry["url"].replace("{FEED}", feed_base)
    rules = data.get("rules")
    if isinstance(rules, list):
        fixed = []
        for line in rules:
            if isinstance(line, str) and "{FEED_HOST}" in line:
                line = line.replace("{FEED_HOST}", host)
            fixed.append(line)
        data["rules"] = fixed
    out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                         default_flow_style=False, width=4096)
    return dedupe_rules(out)


def dedupe_rules(text: str) -> str:
    """去掉 rules 段里完全重复的条目（保留首次出现）。

    面板置顶规则（DOMAIN-SUFFIX,<面板域名>,DIRECT）与个人直连域名清单
    可能指向同一个域名，替换占位符后就会出现两条一模一样的规则。
    """
    lines = text.splitlines()
    out: list[str] = []
    seen: set[str] = set()
    in_rules = False
    for line in lines:
        stripped = line.strip()
        if not in_rules and stripped == "rules:" and not line.startswith((" ", "\t")):
            in_rules = True
            out.append(line)
            continue
        if in_rules:
            if stripped.startswith("- "):
                key = stripped[2:].strip()
                if key in seen:
                    continue
                seen.add(key)
                out.append(line)
                continue
            if stripped and not line.startswith((" ", "\t", "-")):
                in_rules = False  # 下一个顶层键
        out.append(line)
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result


def apply_device_overlay(text: str, overlay_yaml: str) -> str:
    """设备级个性化：在目标产物之上叠加该设备自己的扩展 YAML。

    结构键（节点 / 策略组 / 规则等）不允许被设备覆盖：
    列表是追加语义，写在兜底规则之后永不生效，还会让客户端加载失败。
    """
    overlay_yaml = (overlay_yaml or "").strip()
    if not overlay_yaml:
        return text
    overlay = yaml.safe_load(overlay_yaml) or {}
    if not isinstance(overlay, dict):
        return text
    for key in base_config_service.PROTECTED_KEYS:
        if key in overlay:
            raise ValueError(f"设备扩展不允许覆盖结构键：{key}")
    cfg = yaml.safe_load(text) or {}
    if not isinstance(cfg, dict):
        return text
    _merge(cfg, overlay)
    return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=4096)
