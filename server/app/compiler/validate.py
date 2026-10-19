"""策略与产物的静态校验：引用、环路、空组、正则与 YAML 往返。

静态通过不代表目标客户端实机可用；Stash 没有官方无头校验工具，
其结果只能标记为“静态通过，实机待验收”。
"""
import re

import yaml

from .. import config


def validate_policy(snapshot: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    sources = {s["name"] for s in snapshot["sources"] if s.get("enabled")}
    providers = {r["name"] for r in snapshot["rule_providers"] if r.get("enabled")}
    local_nodes = {
        node["id"]: node for node in snapshot.get("local_nodes", [])
    }
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
            if p not in group_set:
                errors.append(f"策略组“{g['name']}”引用了不存在的策略组“{p}”")
            else:
                refs.append(p)
        for u in g.get("use_sources") or []:
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
        if not (g.get("proxies") or g.get("use_sources") or enabled_local):
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


def validate_rendered(text: str) -> list[str]:
    """渲染产物的 YAML 往返校验。"""
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
    return errors
