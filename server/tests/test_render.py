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
        "JP first": {"revision": "matching", "services": ["claude", "netflix"],
                     "regions": {"netflix": "JP"}},
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


def test_stash_hysteria2_alias_matches_mihomo_evidence_without_changing_output():
    from app.compiler import render
    from app.services import local_nodes, quality_funnel

    node = {"id": 1, "name": "日本软银 01", "node_type": "", "protocol": "hysteria2",
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
    snapshot["service_aliases"] = {
        node["name"]: {"revision": expected, "services": ["netflix"], "regions": {"netflix": "JP"}},
    }
    def generate():
        return yaml.safe_load(render.render_target(
            snapshot, {"name": "phone", "engine": "stash"}, regional_plan=plan,
            quality_reader=lambda nodes: {n["name"]: {"revision": revision(n)} for n in nodes}))

    cfg = generate()
    nodes = {n["name"]: n for n in cfg["proxies"]}
    name = node["name"]
    base = nodes[name]
    assert "auth" in base and "password" not in base
    assert base == local_nodes.render_proxy(node, "stash")
    assert nodes[f"{name} - Netflix"] == {**base, "name": f"{name} - Netflix"}
    node["port"] = 8443
    assert not any(n["name"].endswith(" - Netflix") for n in generate()["proxies"])


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
        "DIRECT", "Netflix", "Spotify", "🤖 Claude", "🚀 默认代理"]
    assert [r["value"] for r in rules] == [r["value"] for r in rows]
    assert groups[-3]["proxies"] == ["日本 01 - Netflix"]
    assert groups[-2]["proxies"] == ["Netflix 日本", "🎞️ 国际影音"]
    assert groups[-1]["proxies"] == ["🎞️ 国际影音"]
    assert "日本 02 - Claude" not in {p["name"] for p in cfg["proxies"]}
    # 美国地区的 Netflix 证据不会进「Netflix 日本」组，也不应生成孤儿别名节点
    assert "美国 01 - Netflix" not in {p["name"] for p in cfg["proxies"]}


def test_claude_adds_verified_choices_without_removing_manual_routes():
    from app.compiler.render import _apply_service_groups

    original = {"name": "🤖 Claude", "type": "select", "proxies": ["美国 01", "日本 01", "其他"],
                "use": ["手动订阅"], "filter": "US"}
    cfg = {"proxies": [{"name": n} for n in ("美国 01", "日本 01", "其他")],
           "proxy-groups": [dict(original)]}
    rules = [{"type": "RULE-SET", "value": "anthropic", "target": "🤖 Claude"}]
    evidence = {name: {"services": ["claude"], "revision": 1, "preferred_ai": True,
                       "latencies": {"claude": delay}}
                for name, delay in (("美国 01", 40), ("日本 01", 20))}
    assert _apply_service_groups(cfg, rules, evidence,
                                 {name: {"revision": 1} for name in evidence},
                                 {name: name for name in evidence}, engine="stash") == rules
    group, automatic = cfg["proxy-groups"]
    assert group == {**original, "proxies": ["Claude 自动", "日本 01 - Claude",
                                             "美国 01 - Claude", *original["proxies"]]}
    assert automatic == {"name": "Claude 自动", "type": "fallback", "hidden": True,
                         "proxies": ["日本 01 - Claude", "美国 01 - Claude"], "interval": 600}


def test_us_media_use_only_eligible_us_nodes_and_keep_the_previous_us_group():
    from app.compiler.render import _apply_service_groups

    rows = [
        {"type": "RULE-SET", "value": "HuluUSA", "target": "🇺🇸美国"},
        {"type": "RULE-SET", "value": "HBOUSA", "target": "🇺🇸美国"},
        {"type": "RULE-SET", "value": "disney", "target": "Disney+"},
        {"type": "RULE-SET", "value": "cn", "target": "DIRECT"},
    ]
    cfg = {"proxies": [{"name": name} for name in ("美国 01", "日本 01")],
           "proxy-groups": [{"name": "🇺🇸美国"}]}
    evidence = {
        "us": {"revision": "current", "services": ["hbo"], "regions": {"hbo": "US"}},
        "jp": {"revision": "current", "services": ["hbo", "hulu"],
               "regions": {"hbo": "JP", "hulu": "JP"}},
    }
    result = _apply_service_groups(cfg, rows, evidence,
                                   {key: {"revision": "current"} for key in evidence},
                                   {"us": "美国 01", "jp": "日本 01"})
    assert result == [{**rows[0], "target": "Hulu"}, {**rows[1], "target": "HBO Max"}, *rows[2:]]
    groups = {group["name"]: group for group in cfg["proxy-groups"]}
    assert groups["Hulu"]["proxies"] == ["🇺🇸美国"]
    assert groups["HBO Max"]["proxies"] == ["美国 01 - HBO Max", "🇺🇸美国"]
    # 日本地区的 HBO 证据不进 HBO Max 组，也不生成孤儿别名
    assert "日本 01 - HBO Max" not in {p["name"] for p in cfg["proxies"]}
    assert "日本 01 - Hulu" not in {p["name"] for p in cfg["proxies"]}


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
        ("copilot.microsoft.com", "Copilot"),
        ("global-ai", "🧠 人工智能"), ("", "🚀 默认代理"),
    ]
    groups = {g["name"]: g for g in cfg["proxy-groups"]}
    assert groups["ChatGPT"]["proxies"] == ["美国 NTT 01 - ChatGPT", "日本 01 - ChatGPT", "🧠 人工智能"]
    assert "Grok" not in groups


def test_unproved_ai_can_be_selected_independently_without_changing_default_outbound():
    from app.compiler.render import _apply_service_groups

    shared = "🧠 人工智能"
    rules = [
        {"type": "RULE-SET", "value": "google", "target": "🔍 谷歌服务"},
        {"type": "RULE-SET", "value": "global-ai", "target": shared},
        {"type": "RULE-SET", "value": "openai", "target": shared},
        {"type": "RULE-SET", "value": "cn", "target": "DIRECT"},
    ]
    cfg = {"proxies": [{"name": "已下发自建节点"}],
           "proxy-groups": [{"name": shared, "type": "select", "proxies": ["已下发自建节点"]}]}
    result = _apply_service_groups(cfg, rules, {}, {}, {},
                                   local_ai_nodes=["已下发自建节点", "未下发的节点"])
    assert result[0] == rules[0] and result[-1] == rules[-1]
    assert [(r["value"], r["target"]) for r in result[1:-1]] == [
        ("openai", "ChatGPT"), ("perplexity.ai", "Perplexity"), ("grok.com", "Grok"),
        ("copilot.microsoft.com", "Copilot"), ("global-ai", shared)]
    for group in cfg["proxy-groups"][1:]:
        assert group["type"] == "select"
        assert group["proxies"] == [shared, "已下发自建节点"]

def test_prime_video_site_precedes_amazon_without_reordering_other_rules():
    from app.compiler.render import _apply_service_groups

    amazon_cn = {"type": "RULE-SET", "value": "AmazonCN", "target": "DIRECT"}
    amazon = {"type": "RULE-SET", "value": "Amazon", "target": "🛒 跨境电商"}
    prime_set = {"type": "RULE-SET", "value": "PrimeVideo", "target": "🎞️ 国际影音"}
    explicit = {"type": "DOMAIN", "value": "www.primevideo.com", "target": "DIRECT"}
    def render(rules):
        cfg = {"proxies": [], "proxy-groups": [{"name": "🎞️ 国际影音"}]}
        return _apply_service_groups(cfg, rules, {}, {}, {})

    media = [{"type": "DOMAIN-SUFFIX", "value": domain, "target": "Prime Video"}
             for domain in ("primevideo.com", "amazonvideo.com", "aiv-cdn.net", "aiv-delivery.net", "pv-cdn.net")]
    result = render([amazon_cn, amazon, prime_set])
    assert result == [amazon_cn, *media, amazon, {**prime_set, "target": "Prime Video"}]
    assert render([amazon_cn, explicit, amazon, prime_set]) == [
        amazon_cn, explicit, *media[1:], amazon, {**prime_set, "target": "Prime Video"}]
    assert render([amazon_cn, prime_set, amazon]) == [
        amazon_cn, {**prime_set, "target": "Prime Video"}, amazon]



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
