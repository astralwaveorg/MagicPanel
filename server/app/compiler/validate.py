"""策略与产物的静态校验：引用、环路、空组、正则与 YAML 往返。

静态通过不代表目标客户端实机可用；Stash 没有官方无头校验工具，
其结果只能标记为“静态通过”。实机验收属于客户端环节，不在发布范围内。
"""
import ipaddress
import re

import yaml

from .. import config
from ..services import local_nodes as local_node_service


def _scope_overlap(a: list[str], b: list[str]) -> bool:
    """两个「适用引擎平台」列表是否有交集（"*" 是包含全部的哨兵）。"""
    if config.ALL_SCOPE in a or config.ALL_SCOPE in b:
        return True
    return bool(set(a) & set(b))


# Fake-IP 段（198.18.0.0/15）：Stash 连接竞速会把内部预解析得到的 Fake-IP
# 带进规则评估（AGENTS.md 约束 33），覆盖这段的 IP 规则一旦排在域名规则之前，
# 就会把域名连接误判成私网/直连黑洞。精确到不覆盖 Fake-IP 段且带 no-resolve
# 的 CIDR（如 192.168.0.0/16、::1/128）是安全的。
_FAKEIP_NET = (ipaddress.ip_network("198.18.0.0/15"),)
# 已知覆盖 Fake-IP 段的规则来源（MetaCubeX private/lan 库包含 198.18.0.0/15）：
# 名单只收「确定覆盖」的集合名模式，避免对 cn-ip / apple-push-ip 等公共段误报。
_FAKEIP_PROVIDER_RE = re.compile(r"private|lan", re.IGNORECASE)

_DOMAIN_RULE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX", "GEOSITE",
}
_IP_RULE_TYPES = {"IP-CIDR", "IP-CIDR6", "GEOIP"}


def _cidr_hits_fakeip(value: str) -> bool:
    """字面 CIDR 是否可能包含 Fake-IP 段地址（解析失败按可能处理）。"""
    text = value.split("/")[0].strip()
    if text.startswith("fe80") or text == "255.255.255.255":
        return False
    try:
        net = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return True
    return any(net.overlaps(other) for other in _FAKEIP_NET)


def _fakeip_order_issues(rules: list[dict], behaviors: dict[str, str]) -> list[str]:
    """约束 33：可能命中 Fake-IP 的 IP 类规则必须排在全部域名类规则之后。"""
    last_domain = -1
    for idx, r in enumerate(rules):
        if not r.get("enabled", True):
            continue
        rtype = r["type"]
        if rtype in _DOMAIN_RULE_TYPES:
            last_domain = idx
        elif rtype == "RULE-SET" and behaviors.get(r["value"]) == "domain":
            last_domain = idx
    if last_domain < 0:
        return []
    issues: list[str] = []
    for idx, r in enumerate(rules):
        if not r.get("enabled", True) or idx >= last_domain:
            continue
        rtype, value = r["type"], r.get("value", "")
        no_resolve = bool(r.get("no_resolve"))
        if rtype in ("IP-CIDR", "IP-CIDR6"):
            if no_resolve and not _cidr_hits_fakeip(value):
                continue
            issues.append(f"{rtype},{value}")
        elif rtype == "GEOIP" and not no_resolve:
            issues.append(f"GEOIP,{value}")
        elif rtype == "RULE-SET" and behaviors.get(value) == "ipcidr" \
                and _FAKEIP_PROVIDER_RE.search(value):
            issues.append(f"RULE-SET,{value}")
    return issues


def validate_policy(snapshot: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    sources = {s["name"] for s in snapshot["sources"] if s.get("enabled")}
    providers = {r["name"] for r in snapshot["rule_providers"] if r.get("enabled")}
    local_nodes = {
        node["id"]: node for node in snapshot.get("local_nodes", [])
    }
    # 本地节点的产物标识索引：成员名可以直接写节点，判定只认这一个事实来源
    local_display = local_node_service.display_index(local_nodes.values())
    local_display_all = local_node_service.display_index(
        local_nodes.values(), enabled_only=False)
    groups = snapshot["groups"]
    group_names = [g["name"] for g in groups]
    group_set = set(group_names)

    if len(group_names) != len(group_set):
        errors.append("策略组名称重复")

    # 策略组引用与环路
    edges: dict[str, list[str]] = {}
    for g in groups:
        if g["type"] not in config.GROUP_TYPES:
            errors.append(f"策略组“{g['name']}”类型不支持：{g['type']}")
        if g.get("filter"):
            try:
                re.compile(g["filter"])
            except re.error as exc:
                errors.append(f"策略组“{g['name']}”过滤正则无效：{exc}")
        refs = []
        for p in g.get("proxies") or []:
            if p in config.BUILTIN_TARGETS or p == config.GUARD_PROXY:
                continue
            if p in group_set:
                refs.append(p)
            elif p in local_display:
                # 本地节点：合法成员。位置即优先级，用来把节点插在组中间。
                # 判定靠 display_name() 的权威索引，不在这里复刻名字格式。
                if "*" in (g.get("devices") or []):
                    warnings.append(
                        f"策略组“{g['name']}”适用于所有设备，成员里的本地节点"
                        f"“{p}”会连同其密钥一起下发给全部设备")
            elif p in local_display_all:
                errors.append(
                    f"策略组“{g['name']}”的成员“{p}”是已停用的本地节点，不会进入产物")
            else:
                errors.append(f"策略组“{g['name']}”引用了不存在的策略组“{p}”")
        for u in g.get("use_sources") or []:
            if u == config.ALL_SCOPE:
                continue          # 「包含所有」由渲染时展开，不做具体校验
            if u not in sources:
                errors.append(f"策略组“{g['name']}”引用了不可用节点来源“{u}”")
        enabled_local: list[int] = []
        for node_id in dict.fromkeys(g.get("local_nodes") or []):
            node = local_nodes.get(node_id)
            if not node:
                errors.append(f"策略组“{g['name']}”引用了不存在的本地节点 #{node_id}")
            elif not node.get("enabled"):
                warnings.append(
                    f"策略组“{g['name']}”引用了已停用的本地节点“{node['name']}”")
            else:
                enabled_local.append(node_id)
        # "包含所有"要按实际能取到的来源算：没有任何来源时它等于空
        uses = [u for u in (g.get("use_sources") or []) if u != config.ALL_SCOPE]
        if config.ALL_SCOPE in (g.get("use_sources") or []):
            uses = list(sources)
        if not (g.get("proxies") or uses or enabled_local):
            errors.append(f"策略组“{g['name']}”为空：既无成员也无节点来源")
        if g["type"] == "relay" and len(g.get("proxies") or []) + len(enabled_local) < 2:
            errors.append(f"relay 策略组“{g['name']}”至少需要两个可用成员")
        edges[g["name"]] = refs

    visiting: set[str] = set()
    done: set[str] = set()

    def dfs(name: str, path: list[str]) -> None:
        if name in done:
            return
        if name in visiting:
            cycle = " → ".join(path + [name])
            errors.append(f"策略组存在循环引用：{cycle}")
            return
        visiting.add(name)
        for nxt in edges.get(name, []):
            dfs(nxt, path + [name])
        visiting.discard(name)
        done.add(name)

    for name in group_names:
        dfs(name, [])

    # 分流规则
    # 同一个规则集可能在互斥的引擎平台各挂一条（例如 Stash 侧用 REJECT + pre-matching，
    # Mihomo 侧用策略组），适用范围不重叠就不算重复。
    seen: dict[tuple[str, str], list[list[str]]] = {}
    has_final = False
    for r in snapshot["rules"]:
        if not r.get("enabled", True):
            continue
        rtype = r["type"]
        if rtype not in config.RULE_TYPES:
            errors.append(f"规则类型不支持：{rtype}（{r.get('value', '')}）")
            continue
        if rtype == "RULE-SET":
            if r["value"] not in providers:
                errors.append(f"规则引用了不存在的规则来源“{r['value']}”")
        elif rtype in ("MATCH", "FINAL"):
            has_final = True
        elif not r.get("value"):
            errors.append(f"规则 {rtype} 缺少匹配值")
        key = (rtype, r["value"])
        scope = r.get("targets") or []
        prev_scopes = seen.setdefault(key, [])
        if any(_scope_overlap(scope, prev) for prev in prev_scopes):
            warnings.append(f"规则重复：{rtype},{r['value']}")
        prev_scopes.append(scope)
        target = r["target"]
        if target not in group_set and target not in config.BUILTIN_TARGETS:
            errors.append(f"规则 {rtype},{r.get('value', '')} 指向不存在的目标“{target}”")
        # pre-matching 的目标只能是 REJECT / REJECT-DROP 字面量，
        # 用策略组会让客户端配置加载失败（官方原文）。
        if r.get("pre_matching") and target not in config.PRE_MATCHING_TARGETS:
            errors.append(
                f"规则 {rtype},{r.get('value', '')} 带 pre-matching，"
                f"目标“{target}”只能是 REJECT / REJECT-DROP，否则客户端加载失败")
        if r.get("no_track") and rtype in ("MATCH", "FINAL"):
            errors.append(
                f"规则 {rtype},{r.get('value', '')} 是兜底规则，不能加 no-track")
    if not has_final:
        errors.append("缺少兜底规则：请添加一条 MATCH 规则")

    # 约束 33（AGENTS.md）：可能命中 Fake-IP 的 IP 类规则必须排在全部
    # 域名类规则之后——Stash 连接竞速会把内部预解析的 Fake-IP 带进规则
    # 评估，排在前面的 IP 规则会把域名连接误判成私网直连黑洞。
    behaviors = {r["name"]: r.get("behavior", "domain")
                 for r in snapshot["rule_providers"] if r.get("enabled")}
    for bad in _fakeip_order_issues(snapshot["rules"], behaviors):
        errors.append(
            f"IP 类规则“{bad}”排在域名规则之前，可能命中 Fake-IP 段导致直连黑洞"
            f"（约束 33：IP 规则一律放在全部域名规则之后）")

    # ---- 约束 21/33 的顺序不变量（构建期强制）----
    # 整张表的排布由界面维护，但下面这些相对关系是路由正确性的地基，
    # 破坏它们的重排曾造成 v2ex 误直连（2026-10-25）与 games-cn 被父集合
    # 抢先送进代理（2026-10-31 发现并修复）。要调整设计顺序，先改这里的
    # 不变量表（并同步 AGENTS.md），再动规则。
    _TAIL_DIRECT_SETS = ["cn", "cn-ip", "direct", "private-ip"]
    _CHILD_BEFORE_PARENT = [
        ("ai-cn", "openai"), ("ai-cn", "anthropic"),
        ("ai-cn", "category-ai-chat-!cn"),
        ("apple-cn", "apple"), ("microsoft-cn", "microsoft"),
        ("games-cn", "games"), ("steam-cn", "cn"),
    ]
    _PROXY_FALLBACK_BEFORE_CN = ["aws", "azure", "cloudflare", "cloudflare-ip",
                                 "digitalocean", "vercel", "netlify",
                                 "proxy-bm7", "proxy-domain"]
    in_order = [r for r in snapshot["rules"] if r.get("enabled", True)]
    set_pos: dict[str, int] = {}
    for i, r in enumerate(in_order):
        if r["type"] == "RULE-SET" and r["value"] not in set_pos:
            set_pos[r["value"]] = i
    final_at = next((i for i, r in enumerate(in_order)
                     if r["type"] in ("MATCH", "FINAL")), None)
    if final_at is not None:
        # 兜底错位由渲染器自动归位并告警（test_rule_order），这里不重复报错；
        # 不变量只盯渲染器不会替你修的三组关系：尾部直连块、父子集合、代理兜底。
        tail = [(n, set_pos[n]) for n in _TAIL_DIRECT_SETS if n in set_pos]
        if tail and ([n for n, _ in tail]
                     != [n for n, _ in sorted(tail, key=lambda x: x[1])]
                     or tail[-1][1] > final_at):
            errors.append(
                "尾部直连块顺序错误（约束 21 ⑩ / 约束 33：应为 "
                + " → ".join(_TAIL_DIRECT_SETS) + " → MATCH）")
        for child, parent in _CHILD_BEFORE_PARENT:
            c, p = set_pos.get(child), set_pos.get(parent)
            if c is not None and p is not None and c > p:
                errors.append(
                    f"规则集合“{child}”排在了父集合“{parent}”之后，"
                    "国内子域名会被父集合抢先送进代理（约束 21：子集合必须早于父集合）")
        cn_pos = [set_pos.get(n) for n in ("cn", "cn-ip")]
        cn_pos = [p for p in cn_pos if p is not None]
        if cn_pos:
            first_cn = min(cn_pos)
            for name in _PROXY_FALLBACK_BEFORE_CN:
                i2 = set_pos.get(name)
                if i2 is not None and i2 > first_cn:
                    errors.append(
                        f"代理兜底集合“{name}”排在了直连集合“cn/cn-ip”之后，"
                        "云服务商域名会被国内直连抢先命中（约束 21 ⑨⑩）")

    # 未使用提示
    used_groups = {r["target"] for r in snapshot["rules"] if r.get("enabled", True)}
    for g in groups:
        if g["name"] not in used_groups and not any(
            g["name"] in (x.get("proxies") or []) for x in groups
        ):
            warnings.append(f"策略组“{g['name']}”未被任何规则或策略组引用")
    used_providers = {
        r["value"] for r in snapshot["rules"]
        if r.get("enabled", True) and r["type"] == "RULE-SET"
    }
    for name in providers - used_providers:
        warnings.append(f"规则来源“{name}”已启用但未被规则引用")

    return errors, warnings


def validate_rendered(text: str, engine: str = "") -> list[str]:
    """渲染产物的 YAML 往返校验 + 引擎级安全校验。

    两类问题会让客户端**加载失败**，必须在服务端拦住：
    1. 规则类型不在该引擎的官方白名单内（如 Stash 没有 UID 规则）；
    2. 规则指向的出站（策略组 / 代理）不存在
       （官方原文：分流规则引用的目标必须存在，否则配置加载失败）。
    """
    errors: list[str] = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"产物 YAML 解析失败：{exc}"]
    if not isinstance(data, dict):
        return ["产物不是有效的配置映射"]
    for key in ("mode", "rules"):
        if key not in data:
            errors.append(f"产物缺少字段：{key}")
    if data.get("mode") not in ("rule", "global", "direct"):
        errors.append(f"产物 mode 无效：{data.get('mode')}")
    # 兜底规则：没有 MATCH/FINAL 时，未命中任何规则的流量会被客户端直接拒绝，
    # 等于设备断网。规则按"适用引擎平台"过滤后可能整条消失，必须在这里兜住。
    if data.get("mode") in ("rule",):
        rules = [r for r in (data.get("rules") or []) if isinstance(r, str)]
        def _is_final(rule: str) -> bool:
            return rule.strip().split(",")[0].strip() in ("MATCH", "FINAL")
        final_at = next((i for i, r in enumerate(rules) if _is_final(r)), -1)
        if final_at < 0:
            errors.append("产物缺少兜底规则（MATCH/FINAL），未命中的流量会被客户端拒绝")
        else:
            after = [r for r in rules[final_at + 1:] if not _is_final(r)]
            if after:
                errors.append(
                    f"兜底规则（{rules[final_at].split(',')[0]}）之后还有 "
                    f"{len(after)} 条普通规则永远匹配不到，请把兜底规则放到最后"
                )


    allowed = config.ENGINE_RULE_TYPES.get(engine)
    group_names = [g.get("name") for g in (data.get("proxy-groups") or [])
                   if isinstance(g, dict)]
    proxy_names = [p.get("name") for p in (data.get("proxies") or [])
                   if isinstance(p, dict)]
    # 重名会被客户端拒绝加载（同名策略组 / 同名节点）
    for label, names in (("策略组", group_names), ("节点", proxy_names)):
        seen = set()
        dup = {n for n in names if n and (n in seen or seen.add(n))}
        if dup:
            errors.append(f"产物存在重名{label}：{'、'.join(sorted(dup))}，客户端会拒绝加载")
    groups = set(group_names)
    proxies = set(proxy_names)
    known = groups | proxies | config.BUILTIN_TARGETS
    # 策略组成员必须真实存在：客户端加载配置时会校验成员名，
    # 引用不存在的出站会直接加载失败。内联模式下成员是展开后的节点名，
    # 这里多一道兜底，避免节点改名或来源停用后产物加载不了。
    for group in (data.get("proxy-groups") or []):
        if not isinstance(group, dict):
            continue
        gname = group.get("name")
        # 没有成员的策略组会让客户端整份配置加载失败（实测 Mihomo 报
        # "`use` or `proxies` missing"，不是"这个组失效"而是"配置废了"）。
        # 内联模式下来源节点被过滤光时组会变空，这里挡住。
        if not (group.get("proxies") or group.get("use")):
            errors.append(f"策略组“{gname}”没有可用成员，客户端会拒绝加载配置")
        for member in (group.get("proxies") or []):
            if not isinstance(member, str) or member in known:
                continue
            errors.append(
                f"策略组“{gname}”的成员“{member}”不存在，会导致客户端加载失败")
    for line in (data.get("rules") or []):
        if not isinstance(line, str):
            continue
        parts = [p.strip() for p in line.split(",")]
        rtype = parts[0] if parts else ""
        if allowed is not None and rtype not in allowed:
            errors.append(f"规则类型 {rtype} 不被 {engine} 支持，会导致客户端加载失败")
            continue
        if rtype in ("MATCH", "FINAL"):
            target = parts[1] if len(parts) > 1 else ""
        elif rtype in ("AND", "OR", "NOT", "SUB-RULE"):
            # 逻辑规则的匹配值是括号配平的表达式，值里带逗号
            # （AND,((NETWORK,udp),(DST-PORT,443)),REJECT），朴素按逗号切
            # 会把目标切在值中间；从第一个逗号后做括号配平，顶层逗号
            # 之后才是出站。
            _, _, rest = line.partition(",")
            depth = 0
            target = ""
            for i, ch in enumerate(rest):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth = max(0, depth - 1)
                elif ch == "," and depth == 0:
                    target = rest[i + 1:].split(",")[0].strip()
                    break
            if not target:
                continue
        elif len(parts) >= 3:
            target = parts[2]
        else:
            continue
        # no-resolve / no-track 修饰符不影响出站位置
        if target not in known:
            errors.append(f"规则 {rtype} 指向不存在的出站“{target}”，会导致客户端加载失败")
        # pre-matching 的目标只能是 REJECT / REJECT-DROP 字面量
        if "pre-matching" in parts and target not in config.PRE_MATCHING_TARGETS:
            errors.append(
                f"规则 {rtype} 带 pre-matching 但目标是“{target}”，"
                f"只能用 REJECT / REJECT-DROP，否则客户端加载失败")
    return errors
