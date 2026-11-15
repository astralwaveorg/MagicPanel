"""纯节点身份归一化，固定离线材料。"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v2_helpers import proxy

KEY = b"example-identity-key-for-tests-only"


def test_name_metadata_and_secret_rotation():
    from app.services.node_identity import fingerprints
    first = fingerprints(proxy("old"), source_id=4, key=KEY)
    renamed = proxy("new")
    renamed["x-magicpanel"] = {"display_name": "renamed"}
    assert first == fingerprints(renamed, source_id=4, key=KEY)
    rotated = fingerprints(proxy("new", "example-rotated-password"), source_id=4, key=KEY)
    assert first["material_hmac"] != rotated["material_hmac"]
    assert first["identity_hmac"] == rotated["identity_hmac"]
    assert set(first) == {"identity_hmac", "material_hmac", "key_version"}
    assert first["key_version"] == 1
    assert "example-test-password" not in repr(first)


@pytest.mark.parametrize("left,right", [
    ("EXAMPLE.COM.", "example.com"),
    ("例子.测试", "xn--fsqu00a.xn--0zwm56d"),
    ("2001:0DB8:0:0:0:0:0:1", "2001:db8::1"),
    ("[2001:db8::1]", "2001:db8::1"),
])
def test_server_normalization(left, right):
    from app.services.node_identity import fingerprints
    assert fingerprints(dict(proxy(), server=left), source_id=None, key=KEY) == fingerprints(
        dict(proxy(), server=right), source_id=None, key=KEY)


@pytest.mark.parametrize("change", [
    {"port": 443}, {"type": "trojan"}, {"network": "ws"},
    {"ws-opts": {"path": "/a"}}, {"unknown-option": {"opaque": [1, 2]}},
])
def test_transport_and_unknown_options_affect_both_hashes(change):
    from app.services.node_identity import fingerprints
    before = fingerprints(proxy(), source_id=4, key=KEY)
    after = fingerprints(dict(proxy(), **change), source_id=4, key=KEY)
    assert before["identity_hmac"] != after["identity_hmac"]
    assert before["material_hmac"] != after["material_hmac"]


def test_accounts_nested_auth_and_source_scope():
    from app.services.node_identity import fingerprints
    first = dict(proxy(), username="example-account-a", **{"tls-opts": {"private-key": "example-key-a", "sni": "a.example"}})
    second = copy.deepcopy(first)
    second["username"] = "example-account-b"
    second["tls-opts"]["private-key"] = "example-key-b"
    a = fingerprints(first, source_id=4, key=KEY)
    b = fingerprints(second, source_id=4, key=KEY)
    assert a["identity_hmac"] == b["identity_hmac"]
    assert a["material_hmac"] != b["material_hmac"]
    other = fingerprints(first, source_id=5, key=KEY)
    assert a["identity_hmac"] != other["identity_hmac"]
    assert a["material_hmac"] == other["material_hmac"]


@pytest.mark.parametrize("change", [
    {"port": True}, {"port": 0}, {"port": 65536}, {"port": 1.5}, {"port": "443"},
    {"port": None}, {"server": ""}, {"server": "bad host"}, {"server": "https://example.com/secret"},
    {"server": None}, {"option": float("nan")}, {"option": {"nested": float("inf")}},
    {"option": object()}, {"option": {1: "example-sensitive"}}, {"type": None},
])
def test_invalid_material_has_safe_error(change):
    from app.services.node_identity import canonical_material
    with pytest.raises(ValueError, match="^catalog_material_invalid$") as error:
        canonical_material(dict(proxy(), **change))
    assert error.value.__cause__ is None
    assert "example-sensitive" not in str(error.value)


def test_material_preserves_options_and_does_not_mutate_input():
    from app.services.node_identity import canonical_material
    original = dict(proxy(), **{"x-other": {"values": [1, "b"]}})
    frozen = copy.deepcopy(original)
    result = canonical_material(original)
    assert result == {k: v for k, v in original.items() if k != "name"}
    result["x-other"]["values"].append(3)
    assert original == frozen


def test_catalog_key_derivation_domains_and_missing_key():
    from app.security import derive_subkey
    from app.services.node_identity import derive_catalog_key, fingerprints
    master = bytes(range(32))
    assert derive_catalog_key(master) == derive_subkey(master, purpose="node-identity", version=1)
    assert derive_catalog_key(master) != derive_subkey(master, purpose="other-purpose", version=1)
    with pytest.raises(ValueError):
        derive_catalog_key(b"")
    with pytest.raises(ValueError):
        derive_catalog_key(master, version=2)
    for key in (b"", None, "example-key"):
        with pytest.raises(ValueError, match="^catalog_material_invalid$"):
            fingerprints(proxy(), source_id=4, key=key)


def test_hmac_depends_on_key_and_mapping_order_is_irrelevant():
    from app.services.node_identity import fingerprints
    value = dict(proxy(), **{"ws-opts": {"path": "/a", "headers": {"Host": "example.com"}}})
    reordered = dict(reversed(list(value.items())))
    first = fingerprints(value, source_id=None, key=KEY)
    assert first == fingerprints(reordered, source_id=None, key=KEY)
    second = fingerprints(value, source_id=None, key=b"example-other-fixed-test-key")
    assert first["identity_hmac"] != second["identity_hmac"]
    assert first["material_hmac"] != second["material_hmac"]
    assert len(first["material_hmac"]) == len(first["identity_hmac"]) == 64


@pytest.mark.parametrize("source_id", [True, 0, -1, "4", 1.5])
def test_invalid_source_scope_rejected(source_id):
    from app.services.node_identity import fingerprints
    with pytest.raises(ValueError, match="^catalog_material_invalid$"):
        fingerprints(proxy(), source_id=source_id, key=KEY)


def test_recursive_material_rejected_without_value_in_error():
    from app.services.node_identity import canonical_material
    value = proxy()
    value["example-sensitive"] = value
    with pytest.raises(ValueError, match="^catalog_material_invalid$"):
        canonical_material(value)

@pytest.mark.parametrize("server", ["xn--a.example", "XN--A.example", "xn--0.example", "xn--abc-.example"])
def test_invalid_ace_server_rejected_with_safe_error(server):
    from app.services.node_identity import canonical_material, fingerprints
    value = dict(proxy(), server=server)
    for operation in (lambda: canonical_material(value),
                      lambda: fingerprints(value, source_id=None, key=KEY)):
        with pytest.raises(ValueError, match="^catalog_material_invalid$") as error:
            operation()
        assert error.value.__cause__ is None


@pytest.mark.parametrize("server", [
    "example。com。", "example．com．", "example｡com｡", "EXAMPLE。COM。",
])
def test_unicode_domain_separators_are_canonical(server):
    from app.services.node_identity import fingerprints
    assert fingerprints(dict(proxy(), server=server), source_id=None, key=KEY) == fingerprints(
        dict(proxy(), server="example.com."), source_id=None, key=KEY)


@pytest.mark.parametrize("server", [
    "[example.com]", "example..com", "-example.com", "example-.com",
    "example.com:443", "fe80::1%eth0", "example.com..",
])
def test_review_invalid_server_forms_remain_rejected(server):
    from app.services.node_identity import canonical_material
    with pytest.raises(ValueError, match="^catalog_material_invalid$"):
        canonical_material(dict(proxy(), server=server))


@pytest.mark.parametrize("server,expected", [
    ("XN--FSQU00A.XN--0ZWM56D.", "xn--fsqu00a.xn--0zwm56d"),
    ("例子。测试。", "xn--fsqu00a.xn--0zwm56d"),
    ("192.0.2.1", "192.0.2.1"),
])
def test_valid_ace_unicode_and_ipv4_stay_canonical(server, expected):
    from app.services.node_identity import fingerprints
    assert fingerprints(dict(proxy(), server=server), source_id=4, key=KEY) == fingerprints(
        dict(proxy(), server=expected), source_id=4, key=KEY)

@pytest.mark.parametrize("header", ["Authorization", "Proxy-Authorization", "Cookie", "Set-Cookie"])
def test_header_credential_rotation_preserves_identity_but_host_does_not(header):
    from app.services.node_identity import fingerprints
    value = dict(proxy(), **{"ws-opts": {"headers": {header: "example-token-a", "Host": "first.example"}}})
    before = fingerprints(value, source_id=4, key=KEY)
    rotated = copy.deepcopy(value)
    rotated["ws-opts"]["headers"][header] = "example-token-b"
    after = fingerprints(rotated, source_id=4, key=KEY)
    assert before["identity_hmac"] == after["identity_hmac"]
    assert before["material_hmac"] != after["material_hmac"]
    changed_host = copy.deepcopy(value)
    changed_host["ws-opts"]["headers"]["Host"] = "second.example"
    assert before["identity_hmac"] != fingerprints(changed_host, source_id=4, key=KEY)["identity_hmac"]
