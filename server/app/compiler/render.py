"""按目标渲染完整配置。

产物中的 `{FEED}` 占位符由分发层在响应时替换为设备专属地址，
`{FEED_HOST}` 替换为面板域名（用于置顶 DIRECT 规则）。
订阅来源仍以 provider 占位引用；本地单节点的凭据会直接写入产物，
因此构建产物与 builds 快照都包含本地节点凭据，不能公开分发。

差异化维度（自下而上叠加）：
① 产物配置：引擎默认配置 → 引擎平台配置 → 设备独立配置
② 结构内容：策略组与分流规则按「适用目标」过滤，并按平台能力剔除必然无效的规则
③ 功能模块：按引擎过滤
④ 平台扩展：引擎平台 extra_yaml
（⑤ 设备级覆盖在分发层叠加，见 routers/feed.py）
"""
import urllib.parse

import yaml

from .. import config
from ..services import base_config as base_config_service
from ..services import local_nodes as local_node_service
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
                 inline_names: dict[str, list[str]] | None = None) -> dict:
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
    if config.ALL_SCOPE in use:
        # 「包含所有」：用全部启用的来源，以后新增的来源自动进来
        use = [name for name in (all_sources or []) if name not in use]
    # 内联来源的节点必须展开成显式成员：provider 里的节点客户端自己才知道，
    # 内联后没有 provider 可用，只写 use 会让组变成空的。
    inline_members: list[str] = []
    provider_use: list[str] = []
    for name in use:
        if inline_names and name in inline_names:
            inline_members.extend(inline_names[name])
        else:
            provider_use.append(name)
    use = provider_use
    if group["type"] in ("url-test", "fallback", "load-balance") \
            and config.GUARD_PROXY not in proxies:
        # 放在末尾而不是开头：占位节点永远连不通（127.0.0.1:1），
        # 它的作用只是让组非空，防止客户端把空组隐式改写成 DIRECT。
        # 放末尾可保证任何客户端（哪怕不做健康检查直接取第一个成员）
        # 拿到的都是真实节点，而不是这个占位。
        proxies.append(config.GUARD_PROXY)
    if inline_members:
        # 组的过滤正则只作用在来源节点上（客户端的组过滤也只筛 provider 节点），
        # 显式成员不受影响。组内没有 provider 时不再下发这个正则：
        # 已经在这里筛过一遍，再让客户端筛一次没有意义。
        pattern = group.get("filter")
        if pattern:
            inline_members = [n for n in inline_members
                              if source_node_service.match(pattern, n)]
        # 按名称排序：来源内是机场给的顺序，多个来源拼起来不好找，
        # 组里挑节点时按名字翻更顺手
        inline_members.sort()
        # 位置与 provider 模式一致：客户端把 provider 节点排在 proxies 之后
        proxies = list(dict.fromkeys(proxies + inline_members))
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
                      local_display: set | None = None) -> tuple[list, list]:
    """按目标过滤策略组与规则，并剔除当前平台必然无效的规则。

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
              if applies_to(g, target_name, device_name)]
    rules = [r for r in snapshot.get("rules", []) if r.get("enabled", True)
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
        proxies = [p for p in (g.get("proxies") or [])
                   if p in config.BUILTIN_TARGETS or p in group_names
                   or p in local_display or p == config.GUARD_PROXY]
        if len(proxies) != len(g.get("proxies") or []):
            if warnings is not None:
                warnings.append(
                    f"策略组“{g['name']}”剔除了不适用于本目标的成员引用")
        g["proxies"] = proxies
    return groups, rules


def render_target(snapshot: dict, target: dict, warnings: list | None = None,
                  device: dict | None = None) -> str:
    """渲染单个目标的完整配置文本。

    device 为空 = 该引擎平台的共享产物（设备专属条目不进入）；
    传入设备 = 渲染这台设备自己的产物（含只属于它的策略组与规则）。
    """
    engine = target["engine"]
    # ① 产物配置：引擎默认配置 → 引擎平台配置（引擎+平台）；设备独立配置在分发时叠加
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
    layers = base_config_service.scope_layers(engine, platform, 0, docs)
    base, _sources = base_config_service.cascade(layers)
    # 应用级伪键：不写入产物，只控制面板内置行为
    panel_direct = bool(base.pop(base_config_service.PANEL_DIRECT_KEY, True))
    direct_domains = base_config_service.normalize_domains(
        base.pop(base_config_service.DIRECT_DOMAINS_KEY, None))
    fake_ip_filter = base_config_service.normalize_filter(
        base.pop(base_config_service.FAKE_IP_FILTER_KEY, None))
    cfg: dict = base_config_service.ordered(base)

    # 本地节点跟随本目标实际生效的策略组，避免把其他设备的私有隧道及密钥
    # 分发给本目标。不能按全局策略组筛选：其中可能包含目标专属的策略组。
    # 节点也可以直接作为组成员被引用（用产物标识），这时它同样跟着这个组走。
    local_index = local_node_service.display_index(
        [n for n in snapshot.get("local_nodes", []) if n.get("enabled")])
    groups, rules = _select_structure(
        snapshot, target, warnings, (device or {}).get("name"),
        set(local_index))
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
    sources = [s for s in snapshot["sources"] if s.get("enabled")]
    inline_sources = [s for s in sources
                      if s.get("mode") == config.SOURCE_MODE_INLINE]
    provider_sources = [s for s in sources
                        if s.get("mode") != config.SOURCE_MODE_INLINE]

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
            entry["name"] = raw + (src.get("suffix") or "")
            inline_nodes.append(entry)
            names.append(entry["name"])
        inline_names[src["name"]] = names
        if not names and warnings is not None:
            warnings.append(
                f"节点来源“{src['name']}”设为内联下发，但没有可用节点"
                "（尚未抓取，或全部被来源过滤正则/测速结果排除）")

    cfg["proxies"] = [_guard_proxy(engine)]
    for node in local_enabled.values():
        cfg["proxies"].append(local_node_service.render_proxy(node, engine))
    cfg["proxies"].extend(inline_nodes)

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
            cfg["proxy-groups"].append(
                _group_entry(group, engine, names,
                             [s["name"] for s in sources], inline_names))

    rps = [r for r in snapshot["rule_providers"] if r.get("enabled")]
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

    # 功能模块按引擎合并，平台扩展最后应用、优先级最高
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

    合并语义与「产物配置」的分层完全一致：字典递归、列表**追加**、标量覆盖。
    设备层是"个性化"语义：保存的是与上层的差异，列表只记新增项，
    因此这里用追加语义——下发结果 = 平台产物 + 这台设备新增的内容。

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
    merged = base_config_service.merge_docs(
        cfg, overlay, base_config_service.LIST_APPEND)
    return yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=4096)
