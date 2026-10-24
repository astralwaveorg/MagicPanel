"""策略与产物的静态校验：引用、环路、空组、正则与 YAML 往返。

静态通过不代表目标客户端实机可用；Stash 没有官方无头校验工具，
其结果只能标记为“静态通过”。实机验收属于客户端环节，不在发布范围内。
"""
import re

import yaml

from .. import config
from ..services import local_nodes as local_node_service


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
    seen: set[tuple[str, str]] = set()
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
        if key in seen:
            warnings.append(f"规则重复：{rtype},{r['value']}")
        seen.add(key)
        target = r["target"]
        if target not in group_set and target not in config.BUILTIN_TARGETS:
            errors.append(f"规则 {rtype},{r.get('value', '')} 指向不存在的目标“{target}”")
    if not has_final:
        errors.append("缺少兜底规则：请添加一条 MATCH 规则")

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
        elif len(parts) >= 3:
            target = parts[2]
        else:
            continue
        # no-resolve / no-track 修饰符不影响出站位置
        if target not in known:
            errors.append(f"规则 {rtype} 指向不存在的出站“{target}”，会导致客户端加载失败")
    return errors
