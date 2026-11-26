"""Stash 与 Mihomo 本地节点渲染差异的回归测试。

口径来自官方文档：
- Stash: https://stash.wiki/proxy-protocols/proxy-types
- Mihomo: https://wiki.metacubex.one/config/proxies/
OpenClash 使用 Mihomo 内核，与 mihomo 产物一致。
"""
import pytest


def _node(protocol, params, **overrides):
    node = {
        "name": "测试节点", "node_type": "机房", "protocol": protocol,
        "server": "example.com", "port": 443, "params": params,
        "extra_yaml": "",
    }
    node.update(overrides)
    return node


def test_vless_reality_mlkem_is_rendered_for_stash_too():
    from app.services.local_nodes import render_proxy
    node = _node("vless", {
        "uuid": "uuid", "flow": "", "tls": True, "servername": "www.example.com",
        "network": "tcp", "reality_public_key": "pk", "reality_short_id": "sid",
        "reality_support_x25519mlkem768": True, "udp": True,
    })
    for engine in ("mihomo", "stash"):
        entry = render_proxy(node, engine)
        assert entry["reality-opts"]["support-x25519mlkem768"] is True
        assert entry["client-fingerprint"] == "chrome"


def test_hysteria2_stash_and_mihomo_auth_fields():
    from app.services.local_nodes import render_proxy
    node = _node("hysteria2", {
        "password": "pw", "sni": "s.example.com", "obfs": "gecko",
        "obfs_password": "op", "fast_open": True, "up": 50, "down": 200,
    })
    stash = render_proxy(node, "stash")
    assert stash["auth"] == "pw" and "password" not in stash
    assert stash["up-speed"] == 50 and stash["down-speed"] == 200
    assert stash["obfs"] == "gecko" and stash["obfs-password"] == "op"
    assert stash["fast-open"] is True
    mihomo = render_proxy(node, "mihomo")
    assert mihomo["password"] == "pw" and "auth" not in mihomo
    assert mihomo["up"] == "50 Mbps" and mihomo["down"] == "200 Mbps"
    assert mihomo["fast-open"] is True


def test_tuic_v4_uses_token_for_both_engines():
    from app.services.local_nodes import render_proxy
    node = _node("tuic", {
        "version": "4", "token": "tok", "uuid": "", "password": "",
        "congestion_controller": "bbr",
    })
    for engine in ("mihomo", "stash"):
        entry = render_proxy(node, engine)
        assert entry["token"] == "tok"
        assert "uuid" not in entry and "password" not in entry
    assert render_proxy(node, "stash")["version"] == 4


def test_tuic_v5_uses_uuid_password_for_both_engines():
    from app.services.local_nodes import render_proxy
    node = _node("tuic", {
        "version": "5", "token": "", "uuid": "uuid", "password": "pw",
        "udp_relay_mode": "native", "reduce_rtt": True,
        "congestion_controller": "bbr",
    })
    for engine in ("mihomo", "stash"):
        entry = render_proxy(node, engine)
        assert entry["uuid"] == "uuid" and entry["password"] == "pw"
        assert "token" not in entry
    mihomo = render_proxy(node, "mihomo")
    assert mihomo["udp-relay-mode"] == "native" and mihomo["reduce-rtt"] is True
    stash = render_proxy(node, "stash")
    assert "udp-relay-mode" not in stash and "reduce-rtt" not in stash


def test_tuic_validation_requires_fields_by_version():
    from app.services.local_nodes import normalize_params
    with pytest.raises(ValueError, match="TUIC v4 需要 Token"):
        normalize_params("tuic", {"version": "4", "uuid": "u", "password": "p"})
    with pytest.raises(ValueError, match="TUIC v5 需要 UUID 和密码"):
        normalize_params("tuic", {"version": "5", "token": "t"})
    assert normalize_params("tuic", {"version": "4", "token": "t"})["token"] == "t"
    assert normalize_params("tuic", {"version": "5", "uuid": "u",
                                     "password": "p"})["uuid"] == "u"


def test_stash_trojan_and_socks5_keep_udp():
    from app.services.local_nodes import render_proxy
    trojan = render_proxy(_node("trojan", {"password": "pw", "udp": True}), "stash")
    assert trojan["udp"] is True
    socks = render_proxy(_node("socks5", {"udp": True}), "stash")
    assert socks["udp"] is True
