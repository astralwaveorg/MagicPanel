"""渲染层：面板域名置顶直连规则与分发占位符替换。"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _snapshot():
    return {
        "sources": [],
        "groups": [],
        "rule_providers": [],
        # 适用范围显式写 "包含所有"（空列表 = 不适用任何平台/设备）
        "rules": [{"type": "MATCH", "value": "", "target": "PROXY", "enabled": True,
                   "targets": ["*"], "devices": ["*"]}],
        "snippets": [],
    }


def test_render_injects_feed_host_direct_rule():
    from app.compiler import render

    text = render.render_target(_snapshot(), {"engine": "mihomo", "extra_yaml": ""})
    cfg = yaml.safe_load(text)
    # 置顶直连规则：VPN 运行中更新配置不经过代理
    assert cfg["rules"][0] == "DOMAIN-SUFFIX,{FEED_HOST},DIRECT"
    assert cfg["rules"][-1] == "MATCH,PROXY"


def test_substitute_feed_replaces_host_placeholder():
    from app.compiler import render

    text = render.render_target(_snapshot(), {"engine": "stash", "extra_yaml": ""})
    out = render.substitute_feed(text, "https://magichub.top:8443/feed/tok123")
    assert "- DOMAIN-SUFFIX,magichub.top,DIRECT" in out.splitlines()
    assert "{FEED_HOST}" not in out


def test_target_scoped_groups_isolate_private_local_nodes():
    from app.compiler import render

    snapshot = _snapshot()
    snapshot["local_nodes"] = [
        {"id": i, "name": name, "protocol": "socks5", "server": "127.0.0.1",
         "port": 1080, "params": {"password": secret}, "enabled": True}
        for i, name, secret in [(1, "shared", "shared-secret"),
                                (2, "private", "private-secret"),
                                (3, "unreferenced", "unreferenced-secret")]
    ]
    snapshot["groups"] = [
        {"name": "shared-group", "type": "select", "local_nodes": [1],
         "targets": ["*"], "devices": ["*"]},
        {"name": "private-group", "type": "select", "local_nodes": [2],
         "targets": ["friend"], "devices": ["*"]},
    ]
    for engine in ("stash", "mihomo"):
        own = render.render_target(snapshot, {"name": "owner", "engine": engine})
        friend = render.render_target(snapshot, {"name": "friend", "engine": engine})
        assert "shared-secret" in own and "shared-secret" in friend
        assert "private-secret" not in own and "private-group" not in own
        assert "private-secret" in friend and "private-group" in friend
        assert "unreferenced-secret" not in own + friend


def test_regional_inline_names_keep_membership_order_and_dialer():
    from app.compiler import render
    from app.services import node_rename

    snapshot = _snapshot()
    snapshot["sources"] = [
        {"source_id": i, "name": f"来源{i}", "enabled": True, "mode": "inline" if i == 1 else "provider",
         "nodes": [{"name": "HK 002", "type": "ss", "server": f"hk{i}.example.invalid", "port": 443},
                   *([{"name": "JP 003", "type": "vless", "server": "jp.example.invalid",
                       "port": 443, "network": "xhttp", "xhttp-opts": {"path": "/sample"},
                       "dialer-proxy": "HK 002"}] if i == 1 else [])]}
        for i in (1, 2)
    ]
    snapshot["node_catalog"] = [
        {"source_id": i, "display_name": name, "raw_name": name, "emit_name": name,
         "node_uid": f"{i}-{name}", "origin_kind": "source"}
        for i, name in ((1, "HK 002"), (1, "JP 003"), (2, "HK 002"))
    ]
    snapshot["local_nodes"] = [
        {"id": 9, "name": "🇺🇸 美国NTT 01", "node_type": "机房", "protocol": "socks5", "server": "us.example.invalid",
         "port": 1080, "enabled": True},
    ]
    snapshot["node_catalog"].append(
        {"source_id": None, "display_name": "🇺🇸 美国NTT 01", "emit_name": "🇺🇸 美国NTT 01 (机房)",
         "raw_name": "🇺🇸 美国NTT 01", "node_uid": "local-test", "origin_kind": "local", "local_node_id": 9})
    snapshot["groups"] = [
        {"name": "选择", "type": "select", "use_sources": ["*"],
         # 过滤正则匹配的是 rename 标签（机场代码来自来源名首字：来源1→来）
         "filter": r"\[来\] (香港|日本)", "local_nodes": [9],
         "targets": ["*"], "devices": ["*"]}
    ]
    result = yaml.safe_load(render.render_target(
        snapshot, {"name": "router", "engine": "mihomo"},
        regional_plan=node_rename.regional_names(snapshot["node_catalog"]),
        quality_reader=lambda nodes: {p["name"]: {"delay_ms": 130} for p in nodes},
    ))
    proxies = {p["name"]: p for p in result["proxies"]}
    assert proxies["🇭🇰 香港 01"]["server"] == "hk1.example.invalid"
    assert proxies["🇭🇰 香港 02"]["server"] == "hk2.example.invalid"
    assert proxies["🇯🇵 日本"]["dialer-proxy"] == "🇭🇰 香港 01"
    assert proxies["🇯🇵 日本"]["xhttp-opts"] == {"path": "/sample"}
    assert result["proxy-groups"][0]["proxies"] == ["🇺🇸 美国NTT 01", "🇭🇰 香港 01", "🇯🇵 日本"]
    assert "proxy-providers" not in result
    assert node_rename.regional_region("🇨🇳 台湾03 Aliyun1.8x-神龙") == ("🇹🇼", "台湾")
    assert node_rename.regional_region("DaWang-US-Xr1") == ("🇺🇸", "美国")
    assert node_rename.regional_region("HK002") == ("🇭🇰", "香港")
    assert node_rename.regional_region("无地区 03") == ("🌐", "地区待确认")
    assert result["rules"] == yaml.safe_load(
        render.render_target({**snapshot, "sources": []}, {"name": "router", "engine": "mihomo"}))["rules"]
    retired = dict(snapshot["node_catalog"][0], retired=True)
    assert node_rename.regional_names([retired, *snapshot["node_catalog"][1:]])[(2, "HK 002")] == "🇭🇰 香港 02"


def test_stash_hysteria2_render_matches_mihomo_evidence_without_changing_output():
    """Stash 的 hysteria2 渲染与探测指纹口径一致：参数变更即换 revision。"""
    from app.compiler import render
    from app.services import local_nodes, quality_funnel

    node = {"id": 1, "name": "日本自建 01", "node_type": "", "protocol": "hysteria2",
            "server": "test.invalid", "port": 443, "enabled": True,
            "params": {"password": "synthetic", "up": 20, "down": 40}}
    snapshot = _snapshot()
    snapshot["local_nodes"] = [node]
    snapshot["groups"] = [{"name": "选择", "type": "select", "local_nodes": [1],
                           "targets": ["*"], "devices": ["*"]}]
    plan = {(None, node["name"]): node["name"]}
    conf = {"max_delay_ms": 3000, "min_speed_bps": 2000000, "speed_bytes": 1000000, "platform_ids": []}
    def revision(proxy):
        return quality_funnel._fingerprint(proxy, b"fixture", conf)
    expected = revision(local_nodes.render_proxy(node, "mihomo"))

    cfg = yaml.safe_load(render.render_target(
        snapshot, {"name": "phone", "engine": "stash"}, regional_plan=plan,
        quality_reader=lambda nodes: {n["name"]: {"revision": revision(n)} for n in nodes}))
    nodes = {n["name"]: n for n in cfg["proxies"]}
    base = nodes[node["name"]]
    assert "auth" in base and "password" not in base
    assert base == local_nodes.render_proxy(node, "stash")
    node["port"] = 8443
    assert revision(local_nodes.render_proxy(node, "mihomo")) != expected


def test_explicit_inline_sources_follow_group_order():
    from app.compiler.render import _group_entry

    group = {"name": "候选", "type": "select", "proxies": ["本地01", "DIRECT", "本地02"],
             "use_sources": ["第二个来源", "第一个来源"]}
    nodes = {"第一个来源": ["A"], "第二个来源": ["C", "B"]}
    rendered = _group_entry(group, "mihomo", inline_names=nodes)
    assert rendered["proxies"] == ["本地01", "DIRECT", "本地02", "B", "C", "A"]
    rendered = _group_entry({**group, "use_sources": ["*"]}, "mihomo",
                            all_sources=list(nodes), inline_names=nodes)
    assert rendered["proxies"] == ["本地01", "DIRECT", "本地02", "A", "B", "C"]
