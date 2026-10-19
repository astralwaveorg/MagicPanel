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
        "rules": [{"type": "MATCH", "value": "", "target": "PROXY", "enabled": True}],
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
