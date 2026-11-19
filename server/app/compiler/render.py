"""按目标渲染完整配置。

产物中的 `{FEED}` 占位符由分发层在响应时替换为设备专属地址，
`{FEED_HOST}` 替换为面板域名（用于置顶 DIRECT 规则）。
订阅来源仍以 provider 占位引用；本地单节点的凭据会直接写入产物，
因此构建产物与 builds 快照都包含本地节点凭据，不能公开分发。

差异化维度（自下而上叠加）：
① 基础配置：引擎默认配置 → 引擎平台配置 → 设备独立配置
② 结构内容：策略组与分流规则按「适用目标」过滤，并按平台能力剔除必然无效的规则
③ 拓展模块：按引擎过滤
④ 平台扩展：引擎平台 extra_yaml
（⑤ 设备级覆盖在分发层叠加，见 routers/feed.py）
"""
import urllib.parse

import yaml

from .. import config
from ..services import base_config as base_config_service
from ..services import config_resolution, runtime_profiles
from ..services import local_nodes as local_node_service
from ..services import node_rename, routing_planner
from ..services import source_nodes as source_node_service

HEALTH_CHECK = {
    "enable": True,
    "url": config.HEALTH_CHECK_URL,
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
        entry["benchmark-url"] = config.HEALTH_CHECK_URL
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
    if src.get("suffix"):
        # 同名节点在不同来源里会互相覆盖（客户端按名字去重），
        # 给这个来源的节点名加后缀区分开。Stash 与 Mihomo 都支持这个键。
        entry["override"] = {"additional-suffix": src["suffix"]}
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


def _group_entry(group: dict, engine: str, local_names: list[str] | None = None,
                 all_sources: list[str] | None = None,
                 inline_names: dict[str, list[str]] | None = None,
                 filter_names: dict[str, str] | None = None) -> dict:
    entry = {"name": group["name"], "type": group["type"]}
    # 本地单节点可以排在最前（"优先美国"这类组用得上：机房节点先试，
    # 机场节点兜底）。local_nodes 本身是有序的 id 列表，顺序即优先级。
    # 成员也可以直接把本地节点的产物标识写进 proxies，用来把节点插在组中间；
    # 同一节点两处都写了就只留一份，取先出现的位置。
    if group.get("local_first"):
        merged = list(local_names or []) + list(group.get("proxies") or [])
    else:
        merged = list(group.get("proxies") or []) + list(local_names or [])
    proxies = list(dict.fromkeys(merged))
    use = list(group.get("use_sources") or [])
    all_scope = config.ALL_SCOPE in use
    if all_scope:
        # 「包含所有」：用全部启用的来源，以后新增的来源自动进来
        use = [name for name in (all_sources or []) if name not in use]
    # 内联来源的节点必须展开成显式成员：provider 里的节点客户端自己才知道，
    # 内联后没有 provider 可用，只写 use 会让组变成空的。
    inline_members: list[str] = []
    provider_use: list[str] = []
    filter_name = filter_names or {}
    for name in use:
        if inline_names and name in inline_names:
            names = inline_names[name]
            inline_members.extend(names if all_scope else sorted(names, key=lambda n: filter_name.get(n, n)))
        else:
            provider_use.append(name)
    use = provider_use
    if inline_members:
        # 组的过滤正则只作用在来源节点上（客户端的组过滤也只筛 provider 节点），
        # 显式成员不受影响。组内没有 provider 时不再下发这个正则：
        # 已经在这里筛过一遍，再让客户端筛一次没有意义。
        pattern = group.get("filter")
        if pattern:
            inline_members = [n for n in inline_members
                              if source_node_service.match(pattern, filter_name.get(n, n))]
        # 只有「包含所有」沿用跨来源的名称排序；逐项选择则以来源顺序为先。
        if all_scope:
            inline_members.sort(key=lambda n: filter_name.get(n, n))
        # 位置与 provider 模式一致：客户端把 provider 节点排在 proxies 之后
        proxies = list(dict.fromkeys(proxies + inline_members))
    if group["type"] in ("url-test", "fallback", "load-balance") \
            and config.GUARD_PROXY not in proxies and not proxies:
        # 只有组最终一个已知成员都没有时才追加占位节点（空组保护，
        # 127.0.0.1:1 的死节点，作用是让组非空，防止客户端把空组隐式改写成
        # DIRECT）。显式成员在构建期已校验存在、内联成员在此处已展开，
        # 二者只要有一个就永远非空，不塞占位——非空组放占位只会让客户端
        # 多一个永远超时的死项。仍需要占位的只有 provider + 过滤的组：
        # 客户端侧能否匹配到节点构建期无法确认。provider 节点由客户端追加在
        # proxies 之后，因此这类组的占位会出现在已知成员之前；url-test /
        # fallback 会健康检查跳过死节点，不影响选路。
        proxies.append(config.GUARD_PROXY)
    if proxies:
        entry["proxies"] = proxies
    if use:
        entry["use"] = use
    if group.get("filter") and use:
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


def _rule_line(rule: dict, engine: str = "stash") -> str:
    if rule["type"] in ("MATCH", "FINAL"):
        return f"MATCH,{rule['target']}"
    line = f"{rule['type']},{rule['value']},{rule['target']}"
    if rule.get("no_resolve") and rule["type"] in config.NO_RESOLVE_TYPES:
        line += ",no-resolve"
    # no-track / pre-matching 是 Stash 专属能力：Mihomo 的规则参数只有
    # no-resolve 与 src，不带这两个参数。实测 Mihomo 遇到未知参数会忽略
    # （连乱写的参数名都能通过 -t 校验），但产物里干脆不写，语义更清楚。
    if engine == "stash":
        if rule.get("no_track"):
            line += ",no-track"
        if rule.get("pre_matching"):
            line += ",pre-matching"
    return line


def _rule_provider_entry(rp: dict) -> dict:
    fmt = rp.get("format") or "yaml"
    entry = {
        "type": "http",
        "url": f"{{FEED}}/res/rule/{urllib.parse.quote(rp['name'])}",
        # 路径后缀跟内容格式对齐：MRS 是二进制内容，存成 .yaml 会让客户端
        # 按文本规则集去解析（部分核心按扩展名推断格式）
        "path": f"./rules/{rp['name']}.{fmt}",
        "behavior": rp["behavior"],
        "interval": rp.get("client_interval") or rp["interval"],
    }
    if fmt != "yaml":
        entry["format"] = fmt
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


def applies_to(item: dict, target_name: str, device_name: str | None = None) -> bool:
    """策略组 / 规则是否适用于该目标（以及该设备）。

    两个维度都是"收窄"关系，取交集：
    * targets —— 适用引擎平台：["*"] 表示全部平台，空列表表示不适用任何平台；
    * devices —— 适用设备：["*"] 表示全部设备，空列表表示不适用任何设备；
      指定了设备时，只在这些设备自己的产物里出现（共享产物里剔除）。
    """
    scope = item.get("targets") or []
    if config.ALL_SCOPE not in scope and target_name not in scope:
        # 没写 "*" 也没列这个平台（含空列表 = 不适用任何平台）
        return False
    devices = item.get("devices") or []
    if config.ALL_SCOPE in devices:
        return True
    if not devices:
        return False        # 空列表 = 不适用任何设备
    return bool(device_name) and device_name in devices


def _select_structure(snapshot: dict, target: dict, warnings: list | None,
                      device_name: str | None = None,
                      local_display: set | None = None,
                      variant_id: int = 0) -> tuple[list, list]:
    """按目标过滤策略组与规则，并剔除当前平台必然无效的规则。

    方案维度：只取 `variant_id` 匹配的组与规则（0 = 默认方案）；
    方案是完整副本，组与规则的引用都在方案内解析。

    安全约束：
    1. 兜底规则（MATCH/FINAL）永远保留，其指向的策略组强制保留；
    2. 指向不存在策略组的规则自动丢弃（客户端加载即失败，必须杜绝）；
    3. 策略组成员里引用了不存在策略组的成员一并剔除；
    4. 本地节点可以作为成员（用产物标识引用），此时保留——它会跟着这个组
       一起进产物，判定只认 local_display 这个权威索引。
    """
    local_display = local_display or set()
    target_name = target.get("name") or ""
    engine = target.get("engine") or ""
    platform = (target.get("platform") or "").lower()
    unsupported = PLATFORM_UNSUPPORTED_RULES.get((engine, platform), set())

    # 复制一份再改，避免污染快照（同一快照会渲染多个目标）
    groups = [dict(g, proxies=list(g.get("proxies") or []))
              for g in snapshot.get("groups", [])
              if g.get("variant_id", 0) == variant_id
              and applies_to(g, target_name, device_name)]
    rules = [r for r in snapshot.get("rules", []) if r.get("enabled", True)
             and r.get("variant_id", 0) == variant_id
             and applies_to(r, target_name, device_name)]

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
                         if g["name"] == name and g.get("variant_id", 0) == variant_id),
                        None)
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
        # 原本排在兜底之后的规则：客户端永远匹配不到，挪到兜底前才生效
        first_fb = next((i for i, r in enumerate(rules)
                         if r["type"] in ("MATCH", "FINAL")), len(rules))
        moved = sum(1 for r in rules[first_fb:]
                    if r["type"] not in ("MATCH", "FINAL"))
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
        # 设备专属组（如日本移动）被其它组引用时，非该设备的产物里剔除
        # 该成员是作用域机制的预期行为，不作告警；指向不存在组的引用
        # 在构建校验里已经报错，走不到这里。
        proxies = [p for p in (g.get("proxies") or [])
                   if p in config.BUILTIN_TARGETS or p in group_names
                   or p in local_display or p == config.GUARD_PROXY]
        g["proxies"] = proxies
    return groups, rules


def _apply_service_groups(cfg, rules, evidence, quality, final_name, *, local_ai_nodes=(), engine="mihomo"):
    """只引用有权分发的节点，并在通用规则前应用已验证的 AI 专项规则。"""
    materials = {p["name"]: p for p in cfg["proxies"] if p["name"] != config.GUARD_PROXY}
    groups = cfg.setdefault("proxy-groups", [])
    by_name = {g["name"]: g for g in groups}
    used = set(materials) | set(by_name) | set(config.BUILTIN_TARGETS) | {config.GUARD_PROXY}
    eligible = {name: item for name, item in evidence.items()
                if name in final_name and quality.get(name, {}).get("revision") == item["revision"]
                and final_name[name] in materials}
    aliases = {}
    for pid, service in routing_planner.SERVICE_ALIAS_NAMES.items():
        members = {}
        for original, proof in sorted(eligible.items()):
            if pid not in proof["services"]:
                continue
            base = final_name[original]
            label = f"{base} - {service}"
            if label in used:
                continue
            cfg["proxies"].append({**materials[base], "name": label})
            used.add(label)
            members[original] = label
        if members:
            aliases[pid] = members

    def ordered_nodes(pid):
        region = routing_planner.MEDIA_ROUTE_REGIONS.get(pid)
        names = [name for name in aliases.get(pid, {})
                 if not region or eligible[name].get("regions", {}).get(pid) == region]
        names.sort(key=lambda name: (
            pid in routing_planner.AI_SERVICES and not eligible[name].get("preferred_ai"),
            eligible[name].get("latencies", {}).get(pid, 10**9), final_name[name]))
        return [aliases[pid][name] for name in names]

    def add_service_group(label, nodes, fallback=()):
        group = {"name": label, "type": "select", "proxies": nodes or list(fallback)}
        if len(nodes) > 1:
            group.update(type="fallback", url=config.HEALTH_CHECK_URL, interval=600)
        groups.append(group)
        used.add(label)

    generic_ai = "🧠 人工智能"
    ai_manual = list(dict.fromkeys(
        [generic_ai, *[name for name in local_ai_nodes if name in materials],
         *[ref for ref in by_name.get(generic_ai, {}).get("proxies", [])
           if ref in used and ref not in config.BUILTIN_TARGETS and ref != config.GUARD_PROXY]]))

    routed = set()
    updated = []
    for rule in rules:
        domain_set = str(rule.get("value", "")).lower()
        service = routing_planner.SERVICE_RULES.get(domain_set) if rule["type"] == "RULE-SET" else None
        if not service or rule["target"] != service[1] or rule["target"] not in by_name:
            updated.append(rule)
            continue
        pid, previous = service
        nodes = ordered_nodes(pid)
        # 已有独立分流只有确认通过才调整。通用影音可以先拆开，仍沿用原线路。
        if not nodes and pid not in routing_planner.MEDIA_NAMES and previous != generic_ai:
            updated.append(rule)
            continue
        # 已有 Claude/TikTok 专组，保留客户端的原组名和规则目标。
        if previous in {"🤖 Claude", "🎵 TikTok"}:
            entry = by_name[previous]
            # 保留用户设置的组类型、来源与手选项。已验证节点在手选组内排在前面。
            if nodes and entry.get("type") == "select":
                choices = [ref for ref in entry.get("proxies", []) if ref != config.GUARD_PROXY]
                ranked = nodes
                if len(nodes) > 1:
                    ranked_label = f"{routing_planner.SERVICE_ALIAS_NAMES[pid]} 自动"
                    if ranked_label not in used:
                        automatic = {"name": ranked_label, "type": "fallback", "hidden": True,
                                     "proxies": nodes, "interval": 600}
                        if engine != "stash":
                            automatic["url"] = config.HEALTH_CHECK_URL
                        groups.append(automatic)
                        used.add(ranked_label)
                        ranked = [ranked_label, *nodes]
                entry["proxies"] = list(dict.fromkeys([*ranked, *choices]))
                routed.add(pid)
            updated.append(rule)
            continue
        label = routing_planner.SERVICE_ALIAS_NAMES[pid]
        if label in used:
            updated.append(rule)
            continue
        fallbacks = [ref for ref in by_name[previous].get("proxies", [])
                     if ref in used and ref not in config.BUILTIN_TARGETS and ref != config.GUARD_PROXY]
        if pid == "netflix" and nodes and "Netflix 日本" not in used:
            # 保留已下发的 Netflix 组名和旧线路供手选；日本组只收已确认的节点。
            add_service_group("Netflix 日本", nodes)
            add_service_group(label, [], ["Netflix 日本", previous, *fallbacks])
        elif pid in {"hulu", "hbo"}:
            # 保留原美国组为手动选项。只把确认美国地区的节点排到它前面。
            add_service_group(label, [], [*nodes, previous, *fallbacks])
        elif pid in routing_planner.AI_SERVICES and previous == generic_ai:
            add_service_group(label, [], [*nodes, *ai_manual])
        else:
            add_service_group(label, nodes if pid != "netflix" else [], [previous, *fallbacks])
        routed.add(pid)
        updated.append({**rule, "target": label})

    # Amazon 通用集合会抢先匹配 Prime Video 的入口和播放请求。
    # 只提前视频专用域，保留商城、国内直连及用户显式域名规则。
    prime = routing_planner.MEDIA_NAMES["primevideo"]
    if "primevideo" in routed:
        retail = next((i for i, row in enumerate(updated)
                       if row["type"] == "RULE-SET" and str(row.get("value")).lower() == "amazon"
                       and row["target"] == "🛒 跨境电商"), None)
        if retail is not None and any(
            row["type"] == "RULE-SET" and str(row.get("value")).lower() == "primevideo" and row["target"] == prime
            for row in updated[retail + 1:]
        ):
            explicit = {str(row.get("value") or "").lower().rstrip(".") for row in updated
                        if row["type"] in {"DOMAIN", "DOMAIN-SUFFIX"}}
            updated[retail:retail] = [
                {"type": "DOMAIN-SUFFIX", "value": domain, "target": prime}
                for domain in ("primevideo.com", "amazonvideo.com", "aiv-cdn.net", "aiv-delivery.net", "pv-cdn.net")
                if not any(host == domain or host.endswith("." + domain) or domain.endswith("." + host)
                           for host in explicit if host)
            ]

    # 只在现有通用 AI 集合前细分。保留所有在它之前的直连、Google 与用户自定义规则。
    anchor = next((i for i, rule in enumerate(updated)
                   if rule["type"] == "RULE-SET" and rule.get("value", "").lower() in
                   {"global-ai", "category-ai-chat-!cn"} and rule["target"] == "🧠 人工智能"), None)
    if anchor is not None:
        narrow = []
        for pid, source in (("chatgpt", "openai"), ("perplexity", "perplexity")):
            if pid not in routed:
                continue
            for i in range(anchor + 1, len(updated)):
                rule = updated[i]
                if (rule["type"] == "RULE-SET" and rule.get("value", "").lower() == source
                        and rule["target"] == routing_planner.SERVICE_ALIAS_NAMES[pid]):
                    if all(row["target"] == "🧠 人工智能" for row in updated[anchor:i]):
                        narrow.append(updated.pop(i))
                    break
        explicit_domains = {rule.get("value", "").lower() for rule in updated
                            if rule["type"] in {"DOMAIN", "DOMAIN-SUFFIX"}}
        explicit_sets = {rule.get("value", "").lower() for rule in updated if rule["type"] == "RULE-SET"}
        for pid, domain in routing_planner.AI_DOMAIN_RULES.items():
            if (pid in routed or pid in explicit_sets
                    or any(host == domain or host.endswith("." + domain) or domain.endswith("." + host)
                           for host in explicit_domains if host)):
                continue
            label = routing_planner.SERVICE_ALIAS_NAMES[pid]
            if label in used:
                continue
            nodes = ordered_nodes(pid)
            add_service_group(label, [], [*nodes, *ai_manual])
            routed.add(pid)
            narrow.append({"type": "DOMAIN-SUFFIX", "value": domain, "target": label})
        updated[anchor:anchor] = narrow
    # 没有独立规则的服务仍可以手选，菜单中不重复创建已经参与分流的服务。
    for pid, members in aliases.items():
        label = f"已验证 · {routing_planner.SERVICE_ALIAS_NAMES[pid]}"
        if pid not in routed and label not in used:
            groups.append({"name": label, "type": "select", "proxies": sorted(members.values())})
            used.add(label)
    if not groups:
        cfg.pop("proxy-groups", None)
    return updated


def render_target(snapshot: dict, target: dict, warnings: list | None = None,
                  device: dict | None = None,
                  variant: dict | None = None,
                  normalize_nodes: bool = True,
                  resolved: dict | None = None,
                  badge_lookup=None, perf_lookup=None, quality_reader=None,
                  quality_badges=False, regional_plan=None, google_review=None) -> str:
    """渲染单个目标的完整配置文本。

    device 为空 = 该引擎平台的共享产物（设备专属条目不进入）；
    传入设备 = 渲染这台设备自己的产物（含只属于它的策略组与规则）。
    variant 为空 = 默认方案；传入 {"id", "name"} = 渲染该方案的产物。
    resolved 传入预解析好的快照：同一方案下 T×D 个产物不再各自全量
    resolve 一次（2026-11-18 构建性能，按 variant 缓存在调用方）。
    """
    if resolved is None:
        from ..services.node_refs import resolve_snapshot
        snapshot = resolve_snapshot(snapshot, variant_id=(variant or {}).get('id', 0))
    else:
        snapshot = resolved
    engine = target["engine"]
    # ① 基础配置：引擎默认配置 → 引擎平台配置（引擎+平台）；设备独立配置在分发时叠加
    #
    # 复用界面那套 scope_layers()：引擎默认配置 = 源码内置默认值 + 用户在
    # 「引擎默认配置」层的覆盖（(engine, "", 0)）。此前渲染只取源码常量，
    # 界面上的「引擎默认配置」改了不生效，显示与产物对不上。
    platform = target.get("platform") or ""
    docs: dict = {}
    default_override = (snapshot.get("base") or {}).get(f"{engine}|")
    if default_override:
        docs[(engine, "", 0)] = base_config_service.normalize(default_override)
    general_base = (snapshot.get("base") or {}).get(f"{engine}|{platform}")
    if general_base:
        docs[(engine, platform, 0)] = base_config_service.normalize(general_base)
    profile = runtime_profiles.effective_profile(target, device)
    resolved = config_resolution.resolve_layers(
        engine=engine, platform=platform, docs=docs, runtime_profile=profile['id'])
    base = resolved['effective']
    # 应用级伪键：不写入产物，只控制面板内置行为
    panel_direct = bool(base.pop(base_config_service.PANEL_DIRECT_KEY, True))
    direct_domains = base_config_service.normalize_domains(
        base.pop(base_config_service.DIRECT_DOMAINS_KEY, None))
    fake_ip_filter = base_config_service.normalize_filter(
        base.pop(base_config_service.FAKE_IP_FILTER_KEY, None))
    # 「指到家里」的域名用 system 解析：路由器分流 DNS 内网直达 NAS，
    # 避开家宽 NAT 回环（默认清单固化在源码基线的 nameserver-policy 里，
    # 这里把用户在伪键里追加的域合成进去）
    system_dns_domains = base_config_service.normalize_domains(
        base.pop(base_config_service.SYSTEM_DNS_KEY, None))
    cfg: dict = base_config_service.ordered(base)

    # 本地节点跟随本目标实际生效的策略组，避免把其他设备的私有隧道及密钥
    # 分发给本目标。不能按全局策略组筛选：其中可能包含目标专属的策略组。
    # 节点也可以直接作为组成员被引用（用产物标识），这时它同样跟着这个组走。
    local_index = local_node_service.display_index(
        [n for n in snapshot.get("local_nodes", []) if n.get("enabled")])
    variant_id = int((variant or {}).get("id", 0))
    groups, rules = _select_structure(
        snapshot, target, warnings, (device or {}).get("name"),
        set(local_index) | {n['emit_name'] for n in snapshot.get('node_catalog',[]) if n.get('origin_kind') == 'source'}, variant_id)
    used_local = {
        node_id for group in groups for node_id in (group.get("local_nodes") or [])
    }
    for group in groups:
        for member in group.get("proxies") or []:
            node = local_index.get(member)
            if node:
                used_local.add(node["id"])
    local_enabled = {
        node["id"]: node for node in snapshot.get("local_nodes", [])
        if node.get("enabled") and node["id"] in used_local
    }
    # 本方案实际引用的来源：展开每组的 use（含「包含所有」）取并集。
    # 默认方案所有组 use=["*"] → 全部来源，行为不变；不引用任何来源的方案
    # （如「自建美日」）产物不含机场节点，也没有 proxy-providers 段。
    enabled_sources = [s for s in snapshot["sources"] if s.get("enabled")]
    source_names = [s["name"] for s in enabled_sources]
    used_sources: set[str] = set()
    for group in groups:
        use = list(group.get("use_sources") or [])
        if config.ALL_SCOPE in use:
            used_sources.update(source_names)
        else:
            used_sources.update(use)
    sources = [s for s in enabled_sources if s["name"] in used_sources]
    selected_uids = {ref['ref'] for group in groups if group.get('members_format') == 'typed-v2'
                     for ref in group.get('members_v2',[]) if ref.get('kind') == 'node'}
    selected_source_nodes = [n for n in snapshot.get('node_catalog',[])
                             if n['node_uid'] in selected_uids and n.get('origin_kind') == 'source']
    materials = {n['node_uid']:n for n in snapshot.get('node_materials',[])}
    fixed_nodes = []
    node_sources: dict[int, dict] = {}
    original_names: dict[tuple[int, str], str] = {}
    for node in selected_source_nodes:
        source = next((s for s in snapshot['sources'] if s.get('source_id') == node['source_id']),None)
        if not source or not source.get('enabled') or node['raw_name'] in (source.get('excluded_nodes') or []):
            raise ValueError('node_unavailable')
        material = materials.get(node['node_uid'])
        if not material or material['revision'] != node['revision']:
            raise ValueError('catalog_material_invalid')
        if regional_plan is None and any(s.get('source_id') == node['source_id']
                                         and s.get('mode') != config.SOURCE_MODE_INLINE for s in sources):
            raise ValueError('typed_provider_dynamic_conflict')
        entry = dict(material['proxy'], name=node['emit_name'])
        fixed_nodes.append(entry)
        node_sources[id(entry)] = source
        original_names[(source['source_id'], node['raw_name'])] = node['emit_name']
    inline_sources = [s for s in sources
                      if regional_plan is not None or s.get("mode") == config.SOURCE_MODE_INLINE]
    provider_sources = ([] if regional_plan is not None else
                        [s for s in sources if s.get("mode") != config.SOURCE_MODE_INLINE])

    # 内联来源的节点写进顶层 proxies：Clash/Stash 的 GLOBAL 组只收顶层 proxies
    # 与策略组，provider 里的节点永远进不去，内联后才能被直接选中。
    inline_nodes: list[dict] = []
    inline_names: dict[str, list[str]] = {}
    for src in inline_sources:
        names: list[str] = []
        excluded = set(src.get("excluded_nodes") or [])
        for node in src.get("nodes") or []:
            raw = str(node.get("name") or "")
            # 「只分发可用节点」：测速失败的节点不进产物（provider 模式在
            # feed 端过滤，内联模式没有 provider 可过滤）
            if raw in excluded:
                continue
            # 来源自身的过滤作用在原始节点名上（客户端的 provider filter 同理）
            if not source_node_service.match(src.get("filter") or "", raw):
                continue
            entry = dict(node)
            # 节点名后缀：与 provider 的 additional-suffix 语义一致，
            # 不同来源的同名节点靠它区分开（客户端按名字去重）
            if 'source_id' in src and snapshot.get('node_catalog') is not None:
                entry = source_node_service.map_emit_names([entry],source_id=src['source_id'],
                    catalog=snapshot['node_catalog'],suffix=src.get('suffix') or '')[0]
            else:
                entry["name"] = raw + (src.get("suffix") or "")
            inline_nodes.append(entry)
            node_sources[id(entry)] = src
            original_names[(src.get('source_id'), raw)] = entry["name"]
            names.append(entry["name"])
        inline_names[src["name"]] = names
        if not names and warnings is not None:
            warnings.append(
                f"节点来源“{src['name']}”设为内联下发，但没有可用节点"
                "（尚未抓取，或全部被来源过滤正则/测速结果排除）")

    local_proxies = [local_node_service.render_proxy(n, engine) for n in local_enabled.values()]
    quality_materials = local_proxies
    if quality_reader and engine == "stash":
        # 自建 Hysteria2 的 auth/up-speed/down-speed 是 Stash 的输出字段。
        # 测速用同一本地节点的 Mihomo 连接参数取证；保留发给 Stash 的原始字段。
        quality_materials = [
            local_node_service.render_proxy(node, "mihomo") if node["protocol"] == "hysteria2" else emitted
            for node, emitted in zip(local_enabled.values(), local_proxies)
        ]
    quality = (quality_reader(inline_nodes + fixed_nodes + quality_materials)
               if quality_reader else {})
    if quality_reader:
        perf_lookup = quality.get
        badge_lookup = (lambda name: quality.get(name, {}).get("badges", "")) if quality_badges else None
    final_name = {}
    filter_names = {}

    # 节点名称规范化（Sub-Store 风格）：机场来源的节点统一成
    # 「旗帜 地区 序号 [标签·来源]」的确定性格式。只作用于来源节点——
    # 本地节点是用户亲自维护的，命名保持权威不动（约束 17）。
    # 节点本体与组成员引用共用同一张映射表，客户端看到的组员名与节点名
    # 永远一致；地区关键词（旗帜 + 中文地区名）被保留，策略组过滤正则不失配。
    local_final = {}
    if regional_plan is not None:
        by_source = {}
        dropped = set()
        for node in local_proxies:
            old = node["name"]
            label = regional_plan.get((None, old))
            if not label:
                raise ValueError("本地节点缺少目录记录，请重新保存该节点后再构建。")
            local_final[old] = label
        # 用固定的兼容名称筛选；新测速结果不能改动现有策略组成员。
        old_labels = {}
        for src in inline_sources:
            for old, label in node_rename.rename_batch(
                    inline_names[src["name"]], source=src["name"]).items():
                old_labels[(src.get("source_id"), old)] = label or old
        raw_by_key = {(sid, emit): raw for (sid, raw), emit in original_names.items()}
        for node in inline_nodes + fixed_nodes:
            source_id = node_sources[id(node)].get("source_id")
            old = node["name"]
            raw = raw_by_key.get((source_id, old), old)
            if node_rename.is_info_node(raw) or node_rename.is_prompt_node(raw):
                dropped.add((source_id, old))
                continue
            label = regional_plan.get((source_id, old))
            if not label:
                raise ValueError("节点名称未能对应目录。请刷新节点来源后重新构建。")
            by_source[(source_id, old)] = label
            filter_names[label] = old_labels.get((source_id, old), old)
        bare_refs: dict[str, set[str]] = {}
        for (_, old), new in by_source.items():
            bare_refs.setdefault(old, set()).add(new)
        final_name = {old: next(iter(values)) for old, values in bare_refs.items() if len(values) == 1}
        def retained(node):
            return (node_sources[id(node)].get("source_id"), node["name"]) not in dropped

        inline_nodes = [n for n in inline_nodes if retained(n)]
        fixed_nodes = [n for n in fixed_nodes if retained(n)]
        final_name.update(local_final)
        for node in local_proxies:
            node["name"] = local_final[node["name"]]
            if isinstance(node.get("dialer-proxy"), str):
                node["dialer-proxy"] = final_name.get(node["dialer-proxy"], node["dialer-proxy"])
        for node in inline_nodes + fixed_nodes:
            source_id = node_sources[id(node)].get("source_id")
            dialer = node.get("dialer-proxy")
            if isinstance(dialer, str):
                old = original_names.get((source_id, dialer), dialer)
                mapped = by_source.get((source_id, old), final_name.get(dialer))
                if mapped is not None:
                    node["dialer-proxy"] = mapped
                elif dialer in bare_refs:
                    raise ValueError("跨来源的前置代理名称重复，无法确认引用。")
            node["name"] = by_source[(source_id, node["name"])]
        for src in inline_sources:
            names = inline_names[src["name"]]
            inline_names[src["name"]] = [
                by_source[(src.get("source_id"), old)] for old in names
                if (src.get("source_id"), old) not in dropped]
        dropped_refs = {old for _, old in dropped if old not in final_name}
        catalog_by_uid = {n["node_uid"]: n for n in selected_source_nodes}
        for group in groups:
            if group.get("members_format") == "typed-v2":
                overrides = {}
                for ref in group.get("members_v2", []):
                    row = catalog_by_uid.get(ref["ref"]) if ref["kind"] == "node" else None
                    if row:
                        old = row["emit_name"]
                        overrides[old] = by_source.get((row["source_id"], old))
            else:
                overrides = {}
                if any(len(bare_refs.get(p, ())) > 1 for p in group.get("proxies", [])):
                    raise ValueError("策略组引用了多个来源的同名节点，请重新选择节点。")
            group["proxies"] = [
                overrides.get(p, final_name.get(p, p)) for p in group.get("proxies", [])
                if p not in dropped_refs and overrides.get(p, p) is not None]
    elif normalize_nodes:
        rename_map: dict[str, str | None] = {}
        for src in inline_sources:
            rename_map.update(node_rename.rename_batch(
                inline_names[src["name"]], source=src["name"],
                badge_lookup=badge_lookup, perf_lookup=perf_lookup))
        fixed_by_source: dict[str, list[str]] = {}
        sources_by_id = {s.get('source_id'): s for s in snapshot['sources']}
        for node in fixed_nodes:
            src = sources_by_id.get(node.get('source_id'))
            fixed_by_source.setdefault(src["name"] if src else "", []).append(node["name"])
        for sname, names in fixed_by_source.items():
            rename_map.update(node_rename.rename_batch(names, source=sname,
                                                       badge_lookup=badge_lookup,
                                                       perf_lookup=perf_lookup))
        dropped = {old for old, new in rename_map.items() if new is None}
        keep = {old: new for old, new in rename_map.items() if new is not None}
        final_name = keep
        inline_nodes = [n for n in inline_nodes if n["name"] not in dropped]
        fixed_nodes = [n for n in fixed_nodes if n["name"] not in dropped]
        for n in inline_nodes + fixed_nodes:
            n["name"] = keep.get(n["name"], n["name"])
        for sname, names in inline_names.items():
            inline_names[sname] = [keep.get(n, n) for n in names if n not in dropped]
        for group in groups:
            group["proxies"] = [keep.get(p, p) for p in (group.get("proxies") or [])
                                if p not in dropped]

    cfg["proxies"] = [_guard_proxy(engine)]
    cfg["proxies"].extend(local_proxies)
    all_fixed = {}
    for node in inline_nodes + fixed_nodes:
        previous = all_fixed.get(node['name'])
        if previous is not None and previous != node:
            raise ValueError('reference_ambiguous')
        all_fixed[node['name']] = node
    cfg["proxies"].extend(all_fixed.values())

    if provider_sources:
        cfg["proxy-providers"] = {
            s["name"]: _provider_entry(s, engine) for s in provider_sources
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
            names = [local_final.get(name, name) for name in names]
            cfg["proxy-groups"].append(
                _group_entry(group, engine, names,
                             [s["name"] for s in sources], inline_names, filter_names))

    if regional_plan is not None:
        local_ai_nodes = [label for raw, label in local_final.items()
                          if node_rename.regional_region(raw)[0] in ("🇺🇸", "🇯🇵")]
        rules = _apply_service_groups(cfg, rules, snapshot.get("service_aliases") or {},
                                      quality, final_name, local_ai_nodes=local_ai_nodes, engine=engine)
        if google_review is not None and any(r["target"] == "🔍 谷歌服务" for r in rules):
            google_review(cfg)

    # 本方案引用的规则来源：规则里的 RULE-SET ∪ DNS nameserver-policy 的
    # rule-set: 引用（约束 31 的三个 DNS 集合因此永不悬空）。
    # 未被引用的启用集合不再写进产物，客户端不白下载用不到的集合。
    used_rule_sets = {r["value"] for r in rules if r["type"] == "RULE-SET"}
    dns_cfg = cfg.get("dns")
    if isinstance(dns_cfg, dict):
        ns_policy = dns_cfg.get("nameserver-policy")
        if isinstance(ns_policy, dict):
            for key in ns_policy:
                text = str(key)
                if text.startswith("rule-set:"):
                    used_rule_sets.update(
                        p.strip() for p in text.split(":", 1)[1].split(",")
                        if p.strip())
    rps = [r for r in snapshot["rule_providers"]
           if r.get("enabled") and r["name"] in used_rule_sets]
    if rps:
        cfg["rule-providers"] = {r["name"]: _rule_provider_entry(r) for r in rps}

    # 面板自身域名强制直连且置顶：VPN 运行中客户端更新配置不经过代理，
    # 避免节点失效导致配置无法更新（TLS 握手失败）。{FEED_HOST} 分发时替换。
    pinned = ["DOMAIN-SUFFIX,{FEED_HOST},DIRECT"] if panel_direct else []
    # 个人直连域名：置顶在用户规则之前，保证一定先生效
    personal = [f"DOMAIN-SUFFIX,{domain},DIRECT" for domain in direct_domains]
    cfg["rules"] = pinned + personal + [_rule_line(r, engine) for r in rules]

    # Stash 常驻 Fake-IP；Mihomo 的 DNS 段（enable / enhanced-mode 等）由引擎
    # 默认配置给出，用户在平台层改的 dns 已在层叠里合并过——这里不再另存
    # 一份默认值，避免同一套 DNS 写两处、改一处不生效。
    if fake_ip_filter:
        # 个人维护的过滤列表整体替换内置列表
        cfg.setdefault("dns", {})["fake-ip-filter"] = fake_ip_filter

    # 「指到家里」的域名 → system：与基线 nameserver-policy 的清单合并
    # （追加不覆盖：默认域已在基线里，这里只合成用户新增的）。放在 policy
    # 最前——system 答案优先于任何通用解析器。
    if system_dns_domains:
        dns_cfg = cfg.setdefault("dns", {})
        policy = dns_cfg.get("nameserver-policy")
        policy = dict(policy) if isinstance(policy, dict) else {}
        merged: dict = {}
        for domain in system_dns_domains:
            merged[f"+.{domain}"] = "system"
        for key, value in policy.items():
            if key not in merged:
                merged[key] = value
        dns_cfg["nameserver-policy"] = merged

    # 拓展模块按引擎合并，平台扩展最后应用、优先级最高
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
    # 面板自己的域名一律留在 Fake-IP 之外：客户端拿到真实 IP，
    # 订阅更新走的是面板域名而不是 Fake-IP 映射，客户端本地 DNS 缓存
    # 过期也不影响更新（增强模式下这条路径是订阅能不能更新的关键）。
    # 追加而不是替换：用户自己维护的排除清单原样保留。
    dns = data.get("dns")
    if isinstance(dns, dict) and host:
        flt = dns.get("fake-ip-filter")
        if isinstance(flt, list):
            pattern = f"+.{host}"
            if pattern not in flt:
                dns["fake-ip-filter"] = flt + [pattern]
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
    return config_resolution.apply_device_overlay(text, overlay_yaml)
