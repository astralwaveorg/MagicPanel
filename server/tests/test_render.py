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
         "filter": r"^.+ \[来源1\] (香港|日本) 01$", "local_nodes": [9],
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


def test_service_aliases_copy_only_scoped_nodes_with_matching_revisions():
    from app.compiler import render
    from app.services import node_rename

    snapshot = _snapshot()
    snapshot["local_nodes"] = [
        {"id": i, "name": name, "protocol": "socks5", "server": host,
         "port": 1080, "enabled": True}
        for i, name, host in [(1, "JP first", "a.example.invalid"),
                              (2, "JP second", "b.example.invalid"),
                              (3, "US private", "c.example.invalid")]]
    snapshot["groups"] = [{"name": "选择", "type": "select", "local_nodes": [1, 2],
                           "targets": ["*"], "devices": ["*"]}]
    snapshot["service_aliases"] = {
        "JP first": {"revision": "matching", "services": ["claude", "netflix"]},
        "JP second": {"revision": "stale", "services": ["gemini"]},
        "US private": {"revision": "matching", "services": ["tiktok"]},
    }
    plan = node_rename.regional_names(
        [{"source_id": None, "emit_name": n["name"], "display_name": n["name"]}
         for n in snapshot["local_nodes"]])
    for engine in ("stash", "mihomo"):
        cfg = yaml.safe_load(render.render_target(
            snapshot, {"name": "router", "engine": engine}, regional_plan=plan,
            quality_reader=lambda nodes: {n["name"]: {"revision": "matching"} for n in nodes}))
        proxies = {p["name"]: p for p in cfg["proxies"]}
        for service in ("Claude", "Netflix"):
            label = f"JP first - {service}"
            assert proxies[label] == {**proxies["JP first"], "name": label}
            assert {"name": f"已验证 · {service}", "type": "select", "proxies": [label]} in cfg["proxy-groups"]
        assert cfg["proxy-groups"][0]["proxies"] == ["JP first", "JP second"]
        assert "JP second - Gemini" not in proxies
        assert "US private - TikTok" not in proxies


def test_service_groups_split_media_in_place_and_require_jp_netflix_evidence():
    from app.compiler import render

    rows = [
        {"type": "RULE-SET", "value": "cn", "target": "DIRECT"},
        {"type": "RULE-SET", "value": "netflix", "target": "🎞️ 国际影音"},
        {"type": "RULE-SET", "value": "spotify", "target": "🎞️ 国际影音"},
        {"type": "RULE-SET", "value": "anthropic", "target": "🤖 Claude"},
        {"type": "MATCH", "value": "", "target": "🚀 默认代理"},
    ]
    groups = [{"name": name} for name in ("🎞️ 国际影音", "🤖 Claude")]
    cfg = {"proxies": [{"name": name, "type": "ss"} for name in ("日本 01", "美国 01", "日本 02")],
           "proxy-groups": groups}
    evidence = {
        "jp": {"revision": "now", "services": ["netflix"], "regions": {"netflix": "JP"}},
        "us": {"revision": "now", "services": ["netflix"], "regions": {"netflix": "US"}},
        "stale": {"revision": "old", "services": ["claude"]},
    }
    rules = render._apply_service_groups(
        cfg, rows, evidence, {name: {"revision": "now"} for name in evidence},
        {"jp": "日本 01", "us": "美国 01", "stale": "日本 02"})
    assert [r["target"] for r in rules] == [
        "DIRECT", "Netflix 日本", "Spotify", "🤖 Claude", "🚀 默认代理"]
    assert [r["value"] for r in rules] == [r["value"] for r in rows]
    assert groups[-2]["proxies"] == ["日本 01 - Netflix"]
    assert groups[-1]["proxies"] == ["🎞️ 国际影音"]
    assert "日本 02 - Claude" not in {p["name"] for p in cfg["proxies"]}


def test_ai_service_rules_preserve_google_direct_and_explicit_overrides():
    from app.compiler import render

    rules = [
        {"type": "RULE-SET", "value": "ai-cn", "target": "DIRECT"},
        {"type": "RULE-SET", "value": "google", "target": "🔍 谷歌服务"},
        {"type": "DOMAIN-SUFFIX", "value": "grok.com", "target": "DIRECT"},
        {"type": "RULE-SET", "value": "global-ai", "target": "🧠 人工智能"},
        {"type": "RULE-SET", "value": "openai", "target": "🧠 人工智能"},
        {"type": "MATCH", "value": "", "target": "🚀 默认代理"},
    ]
    cfg = {"proxies": [{"name": name, "type": "ss"} for name in ("美国 NTT 01", "日本 01")],
           "proxy-groups": [{"name": "🧠 人工智能"}]}
    evidence = {
        "self": {"revision": "now", "preferred_ai": True,
                 "services": ["chatgpt", "perplexity", "grok"], "latencies": {"chatgpt": 400}},
        "other": {"revision": "now", "services": ["chatgpt"], "latencies": {"chatgpt": 100}},
    }
    result = render._apply_service_groups(
        cfg, rules, evidence, {n: {"revision": "now"} for n in evidence},
        {"self": "美国 NTT 01", "other": "日本 01"})
    assert result[:3] == rules[:3]
    assert [(r["value"], r["target"]) for r in result[3:]] == [
        ("openai", "ChatGPT"), ("perplexity.ai", "Perplexity"),
        ("global-ai", "🧠 人工智能"), ("", "🚀 默认代理"),
    ]
    groups = {g["name"]: g for g in cfg["proxy-groups"]}
    assert groups["ChatGPT"]["proxies"] == ["美国 NTT 01 - ChatGPT", "日本 01 - ChatGPT"]
    assert "Grok" not in groups
