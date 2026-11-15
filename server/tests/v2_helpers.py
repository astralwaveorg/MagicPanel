"""V2 测试共用的离线节点与顺序夹具。"""
import base64
import json

import yaml

from conftest import auth_headers, setup_admin


def admin(client):
    return auth_headers(setup_admin(client))


def make_local(client, headers, name="US-01"):
    response = client.post("/api/v1/local-nodes", headers=headers, json={
        "name": name, "node_type": "机房", "protocol": "ss",
        "server": "node.example.com", "port": 8388,
        "params": {"cipher": "aes-256-gcm", "password": "example-test-password"}})
    assert response.status_code == 201, response.text
    return response.json()


def proxy(name="A", password="example-test-password"):
    return {"name": name, "type": "ss", "server": "node.example.com",
            "port": 8388, "cipher": "aes-256-gcm", "password": password}


def import_source(client, headers, nodes):
    payload = yaml.safe_dump({"proxies": nodes}, allow_unicode=True).encode()
    response = client.post("/api/v1/sources/import-file", headers=headers, json={
        "name": "source-fixture", "content_b64": base64.b64encode(payload).decode(),
        "auto_test": False, "mode": "inline"})
    assert response.status_code == 201, response.text
    return response.json()


def ordering(conn):
    return {table: [tuple(row) for row in conn.execute(
        f"SELECT id,variant_id,sort FROM {table} ORDER BY variant_id,sort,id")]
        for table in ("proxy_groups", "rules")}


def assert_no_secrets(value):
    text = json.dumps(value, ensure_ascii=False)
    assert "example-test-password" not in text
    assert "params_enc" not in text
    assert "snapshot_enc" not in text
