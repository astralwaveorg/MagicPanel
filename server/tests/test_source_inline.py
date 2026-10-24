"""节点来源内联下发：节点写进顶层 proxies，才能进 GLOBAL 组。

provider 模式：节点在 proxy-providers 段，客户端自己拉取更新，
但 Clash/Stash 的 GLOBAL 组只收顶层 proxies 与策略组，provider 节点进不去。
inline 模式：节点直接写进顶层 proxies，代价是机场换节点后要重拉订阅。
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _snapshot(sources=None, groups=None, rule_providers=None):
    return {
        "sources": sources or [],
        "groups": groups or [],
        "rule_providers": rule_providers or [],
        "local_nodes": [],
        "rules": [{"type": "MATCH", "value": "", "target": "PROXY", "enabled": True,
                   "targets": ["*"], "devices": ["*"]}],
        "snippets": [],
    }


def _source(name, mode="inline", nodes=None, suffix="", filter=""):
    return {"name": name, "enabled": True, "filter": filter, "ua": "Stash",
            "suffix": suffix, "interval": 3600, "client_interval": 0,
            "mode": mode, "nodes": nodes or []}


def _node(name, node_type="ss"):
    return {"name": name, "type": node_type, "server": "a.example.com",
            "port": 443, "cipher": "aes-256-gcm", "password": "pw"}


def _group(name, group_type="select", **kwargs):
    item = {"name": name, "type": group_type, "hidden": False, "filter": "",
            "use_sources": [], "local_nodes": [], "proxies": [],
            "targets": ["*"], "devices": ["*"], "interval": 600,
            "timeout": 8000, "tolerance": 100, "lazy": True, "strategy": ""}
    item.update(kwargs)
    return item


def test_inline_nodes_go_to_top_level_proxies():
    """内联来源的节点写进顶层 proxies：这样它们会进 GLOBAL 组。"""
    from app.compiler import render

    snap = _snapshot(
        sources=[_source("机场A", nodes=[_node("香港 01")])],
        groups=[_group("🚀 默认代理", "select", proxies=["🇭🇰 香港"])],
    )
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash"}))
    names = [p["name"] for p in cfg["proxies"]]
    assert "香港 01" in names
    # 内联来源不再产出 proxy-providers 段
    assert "proxy-providers" not in cfg


def test_inline_source_suffix_makes_names_unique():
    """跨来源同名节点靠后缀区分：客户端按名字去重会互相覆盖。"""
    from app.compiler import render

    snap = _snapshot(
        sources=[_source("机场A", nodes=[_node("香港 01")], suffix="-A"),
                 _source("机场B", nodes=[_node("香港 01")], suffix="-B")],
    )
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash"}))
    names = [p["name"] for p in cfg["proxies"]]
    assert "香港 01-A" in names and "香港 01-B" in names
    assert len(names) == len(set(names))


def test_inline_source_filter_removes_pseudo_nodes():
    """来源自身的过滤正则在这里生效：内联后没有客户端帮忙筛。"""
    from app.compiler import render

    snap = _snapshot(
        sources=[_source("机场A",
                         nodes=[_node("香港 01"), _node("剩余流量")],
                         filter=r"(?i)^(?!.*剩余).+$")],
    )
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash"}))
    names = [p["name"] for p in cfg["proxies"]]
    assert "香港 01" in names
    assert "剩余流量" not in names


def test_inline_respects_filter_unavailable():
    """「只分发可用节点」在内联模式下也要生效：测速失败的节点不进产物。"""
    from app.compiler import render

    src = _source("机场A", nodes=[_node("香港 01"), _node("香港 02")])
    src["excluded_nodes"] = ["香港 02"]
    snap = _snapshot(
        sources=[src],
        groups=[_group("🇭🇰 香港", "url-test", use_sources=["*"],
                       filter=r"(?i)香港")],
    )
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash"}))
    names = [p["name"] for p in cfg["proxies"]]
    assert "香港 01" in names
    assert "香港 02" not in names
    # 组里也不能再出现被排除的节点
    grp = next(g for g in cfg["proxy-groups"] if g["name"] == "🇭🇰 香港")
    assert "香港 02" not in grp["proxies"]


def test_group_expands_inline_sources_into_members():
    """组引用内联来源时展开成显式成员：没有 provider 可用，use 会是空的。"""
    from app.compiler import render

    snap = _snapshot(
        sources=[_source("机场A", nodes=[_node("香港 01"), _node("日本 01")])],
        groups=[_group("🇭🇰 香港", "url-test", use_sources=["*"],
                       filter=r"(?i)香港")],
    )
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash"}))
    grp = next(g for g in cfg["proxy-groups"] if g["name"] == "🇭🇰 香港")
    assert "香港 01" in grp["proxies"]
    assert "日本 01" not in grp["proxies"]   # 组自己的过滤正则只筛来源节点
    assert "use" not in grp                  # 内联来源不再走 provider
    # 没有 provider 时不再下发这个正则（已经筛过一遍）
    assert "filter" not in grp


def test_provider_mode_keeps_proxy_providers():
    """provider 模式维持原样：产物里仍有 proxy-providers，组里仍有 use。"""
    from app.compiler import render

    snap = _snapshot(
        sources=[_source("机场A", mode="provider", nodes=[_node("香港 01")])],
        groups=[_group("🇭🇰 香港", "url-test", use_sources=["*"])],
    )
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash"}))
    assert "机场A" in cfg["proxy-providers"]
    grp = next(g for g in cfg["proxy-groups"] if g["name"] == "🇭🇰 香港")
    assert grp["use"] == ["机场A"]
    # provider 节点不在顶层 proxies 里（客户端自己下载）
    assert [p["name"] for p in cfg["proxies"]] == ["空组保护"]


def test_source_snapshot_keeps_only_proxies():
    """机场订阅自带的 rules / dns / 策略组不进快照：与面板的策略无关。"""
    from app.services import source_nodes

    body = b"""proxies:
  - {name: HK01, type: ss, server: a.example.com, port: 443}
rules:
  - MATCH,DIRECT
proxy-groups:
  - {name: g, type: select, proxies: [HK01]}
dns:
  enable: true
"""
    nodes = source_nodes.extract(body)
    assert [n["name"] for n in nodes] == ["HK01"]
    dumped = source_nodes.dump(nodes)
    data = yaml.safe_load(dumped)
    assert set(data) == {"proxies"}
    assert source_nodes.parse(dumped) == nodes


def test_rule_provider_path_matches_format():
    """MRS 是二进制内容，路径后缀也要跟着变。"""
    from app.compiler import render

    snap = _snapshot(rule_providers=[
        {"name": "cn", "behavior": "domain", "format": "mrs", "kind": "remote",
         "interval": 86400, "client_interval": 0, "enabled": True},
        {"name": "inline-set", "behavior": "classical", "format": "yaml",
         "kind": "inline", "interval": 86400, "client_interval": 0, "enabled": True},
    ])
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "mihomo"}))
    paths = {name: entry["path"] for name, entry in cfg["rule-providers"].items()}
    assert paths["cn"] == "./rules/cn.mrs"
    assert paths["inline-set"] == "./rules/inline-set.yaml"
