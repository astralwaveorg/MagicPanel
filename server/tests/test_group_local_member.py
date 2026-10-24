"""策略组成员可以是本地节点：位置自由，判定只认 display_name() 一个事实来源。

写死名字格式的判定会随节点改名、换类型、显示格式调整一起失效，
所以校验器、渲染器、数据自检统一走服务层的 display_index()。
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _snapshot(local_nodes=None, groups=None):
    return {
        "sources": [],
        "groups": groups if groups is not None else [],
        "rule_providers": [],
        "local_nodes": local_nodes or [],
        "rules": [{"type": "MATCH", "value": "", "target": "PROXY", "enabled": True,
                   "targets": ["*"], "devices": ["*"]}],
        "snippets": [],
    }


def _node(node_id, name, node_type="机房", enabled=True):
    return {"id": node_id, "name": name, "node_type": node_type,
            "enabled": enabled, "protocol": "ss", "server": "x.example.com",
            "port": 8388, "params": {}}


def test_local_node_can_be_group_member():
    """成员直接写本地节点的产物标识：合法，且不再报"不存在的策略组"。"""
    from app.compiler import validate

    snap = _snapshot(
        local_nodes=[_node(1, "🇭🇰 香港机房 01")],
        groups=[{
            "name": "🇭🇰 香港", "type": "select", "hidden": False, "filter": "",
            "use_sources": [], "local_nodes": [], "proxies": ["🇭🇰 香港机房 01 (机房)"],
            "targets": ["*"], "devices": ["*"],
        }],
    )
    errors, warnings = validate.validate_policy(snap)
    assert not [e for e in errors if "香港机房" in e], errors
    # 通用组引用本地节点会扩散密钥，必须有告警
    assert any("香港机房" in w and "下发给全部设备" in w for w in warnings), warnings


def test_disabled_local_node_member_is_rejected():
    """停用节点不进产物，不能当成员——要报明确原因而不是"不存在的策略组"。"""
    from app.compiler import validate

    snap = _snapshot(
        local_nodes=[_node(1, "🇭🇰 香港机房 01", enabled=False)],
        groups=[{
            "name": "🇭🇰 香港", "type": "select", "hidden": False, "filter": "",
            "use_sources": [], "local_nodes": [], "proxies": ["🇭🇰 香港机房 01 (机房)"],
            "targets": ["*"], "devices": ["*"],
        }],
    )
    errors, _ = validate.validate_policy(snap)
    assert any("已停用的本地节点" in e for e in errors), errors


def test_member_name_follows_rename_and_type_change():
    """改名或换类型后判定自动跟着变：索引由 display_name() 生成，不是写死的字符串。"""
    from app.services import local_nodes as local_node_service

    nodes = [_node(1, "香港 01", node_type="中转")]
    index = local_node_service.display_index(nodes)
    assert "香港 01 (中转)" in index
    # 换成别的类型，标识随之改变，旧标识不再命中
    nodes[0]["node_type"] = "机房"
    assert "香港 01 (机房)" in local_node_service.display_index(nodes)
    assert "香港 01 (中转)" not in local_node_service.display_index(nodes)


def test_render_keeps_member_position_and_dedupes():
    """成员写进 proxies 时位置即优先级；与 local_nodes 重复时只留一份。"""
    from app.compiler import render

    snap = _snapshot(
        local_nodes=[_node(1, "🇯🇵 日本机房 01"), _node(2, "🇯🇵 日本机房 02")],
        groups=[{
            "name": "🇯🇵 日本", "type": "url-test", "hidden": False, "filter": "",
            "use_sources": [], "local_nodes": [], "proxies": [],
            "targets": ["*"], "devices": ["*"],
        }, {
            "name": "🎏 日韩服务", "type": "select", "hidden": False, "filter": "",
            "use_sources": [], "local_nodes": [2],
            "proxies": ["🇯🇵 日本", "🇯🇵 日本机房 01 (机房)"],
            "targets": ["*"], "devices": ["*"],
        }],
    )
    text = render.render_target(snap, {"engine": "stash", "extra_yaml": ""})
    cfg = yaml.safe_load(text)
    grp = next(g for g in cfg["proxy-groups"] if g["name"] == "🎏 日韩服务")
    # 节点插在第二位，local_nodes 的 02 号节点追加在后，且不重复
    assert grp["proxies"][:3] == ["🇯🇵 日本", "🇯🇵 日本机房 01 (机房)", "🇯🇵 日本机房 02 (机房)"]
    assert len(grp["proxies"]) == len(set(grp["proxies"]))
