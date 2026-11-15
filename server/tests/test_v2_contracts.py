"""V2 foundation-v2.0 类型合同与离线夹具。"""
import importlib
import sqlite3
from typing import Literal, get_type_hints

import httpx
import pytest
import yaml


@pytest.fixture(autouse=True)
def deny_external_http(monkeypatch):
    def denied(self, request):
        raise AssertionError("external_http_forbidden_in_foundation_test")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)


@pytest.mark.parametrize(("name", "fields"), [
    ("MemberRef", {"kind": Literal["node", "group", "builtin"], "ref": str}),
    ("NodeCatalogEntry", {
        "node_uid": str, "revision": int,
        "origin_kind": Literal["source", "local"],
        "source_id": int | None, "local_node_id": int | None,
        "raw_name": str, "display_name": str, "emit_name": str,
        "enabled": bool, "meta": dict,
    }),
    ("PrivateBlobRef", {
        "blob_id": str, "kind": str, "size": int, "ciphertext_sha256": str,
    }),
    ("ReconcileReport", {
        "catalog_revision": int, "created": list[str], "changed": list[str],
        "renamed": list[str], "retired": list[str], "issues": list[dict],
    }),
    ("ResolvedConfig", {
        "engine": str, "platform": str, "device_id": int,
        "runtime_profile": str, "profile_version": int,
        "inherited": dict, "overlay": dict, "effective": dict,
        "provenance": dict, "input_sha256": str,
    }),
])
def test_contract_fields_are_explicit(name, fields):
    contracts = importlib.import_module("app.contracts.v2")
    contract = getattr(contracts, name)
    assert get_type_hints(contract) == fields
    assert contract.__required_keys__ == fields.keys()
    assert contract.__optional_keys__ == frozenset()


def test_helpers_create_usable_offline_api_fixtures(client):
    from v2_helpers import admin, assert_no_secrets, import_source, make_local, proxy

    headers = admin(client)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "admin"

    local = make_local(client, headers, name="本地-US-01")
    listed = client.get("/api/v1/local-nodes", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [(row["id"], row["name"]) for row in listed.json()] == [
        (local["id"], "本地-US-01")]

    source = import_source(client, headers, [
        proxy(), proxy("新加坡-02", password="example-second-test-password")])
    listed = client.get("/api/v1/sources", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == source["id"]
    assert source["source_kind"] == "file"
    assert source["mode"] == "inline"
    assert source["auto_fetch"] is False
    assert source["auto_test"] is False
    assert source["node_count"] == 2
    assert [(node["name"], node["type"]) for node in source["nodes"]] == [
        ("A", "ss"), ("新加坡-02", "ss")]
    assert_no_secrets(source)

    from app import db, security

    with db.connect() as conn:
        row = db.one(conn, "SELECT snapshot_enc FROM sources WHERE id=?",
                     (source["id"],))
    cached = yaml.safe_load(security.decrypt_text(row["snapshot_enc"]))
    assert [node["password"] for node in cached["proxies"]] == [
        "example-test-password", "example-second-test-password"]


def test_ordering_captures_all_variants_with_stable_ties():
    from v2_helpers import ordering

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE proxy_groups(id INTEGER, variant_id INTEGER, sort INTEGER)")
        conn.execute("CREATE TABLE rules(id INTEGER, variant_id INTEGER, sort INTEGER)")
        conn.executemany("INSERT INTO proxy_groups VALUES(?,?,?)", [
            (2, 2, 1), (1, 0, 4), (3, 0, 1)])
        conn.executemany("INSERT INTO rules VALUES(?,?,?)", [
            (3, 2, 0), (2, 0, 3), (1, 0, 3)])
        assert ordering(conn) == {
            "proxy_groups": [(3, 0, 1), (1, 0, 4), (2, 2, 1)],
            "rules": [(1, 0, 3), (2, 0, 3), (3, 2, 0)],
        }


@pytest.mark.parametrize("value", [
    {"nested": [{"password": "example-test-password"}]},
    {"nested": {"params_enc": ""}},
    [{"snapshot_enc": "ciphertext"}],
])
def test_secret_assertion_rejects_nested_private_data(value):
    from v2_helpers import assert_no_secrets

    with pytest.raises(AssertionError):
        assert_no_secrets(value)
