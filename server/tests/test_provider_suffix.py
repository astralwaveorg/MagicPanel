"""节点来源的 additional-suffix 与 MRS 二进制规则集。

同名节点跨来源会互相覆盖（客户端按名字去重），后缀用于区分；
MRS 是二进制规则集，内容按字节处理，存库 base64、下发还原。
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _snapshot(sources=None, rule_providers=None):
    return {
        "sources": sources or [],
        "groups": [],
        "rule_providers": rule_providers or [],
        "rules": [{"type": "MATCH", "value": "", "target": "PROXY", "enabled": True,
                   "targets": ["*"], "devices": ["*"]}],
        "snippets": [],
    }


def _source(name, suffix=""):
    return {"name": name, "enabled": True, "filter": "", "ua": "Stash",
            "suffix": suffix, "interval": 3600, "client_interval": 3600}


def test_provider_gets_additional_suffix():
    """填了后缀就写进 override，客户端据此给节点名加后缀。"""
    from app.compiler import render

    snap = _snapshot(sources=[_source("神龙机场", "-神龙")])
    for engine in ("stash", "mihomo"):
        cfg = yaml.safe_load(render.render_target(snap, {"engine": engine, "extra_yaml": ""}))
        entry = cfg["proxy-providers"]["神龙机场"]
        assert entry["override"] == {"additional-suffix": "-神龙"}, engine


def test_provider_without_suffix_has_no_override():
    from app.compiler import render

    snap = _snapshot(sources=[_source("白月光")])
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash", "extra_yaml": ""}))
    assert "override" not in cfg["proxy-providers"]["白月光"]


def test_mrs_provider_declares_format():
    """MRS 集合的 format 要写进产物，客户端才知道按二进制解析。"""
    from app.compiler import render

    snap = _snapshot(rule_providers=[{
        "name": "cn", "behavior": "domain", "format": "mrs", "kind": "remote",
        "url": "https://example.com/cn.mrs", "client_interval": 21600,
        "interval": 86400, "enabled": True, "content": "", "sha256": "x",
    }])
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash", "extra_yaml": ""}))
    assert cfg["rule-providers"]["cn"]["format"] == "mrs"


def test_engine_default_layer_overrides_reach_the_artifact():
    """「引擎默认配置」层的用户覆盖要真正进产物（此前渲染只取源码常量）。"""
    from app.compiler import render

    snap = _snapshot()
    snap["base"] = {"mihomo|": {"log-level": "debug"}}
    cfg = yaml.safe_load(render.render_target(
        snap, {"engine": "mihomo", "platform": "macos", "extra_yaml": ""}))
    assert cfg["log-level"] == "debug"
