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
