"""本地节点「节点类型」：默认值、名称拼接、产物一致性与迁移。

节点的产物标识统一为「名称 (类型)」，类型为空时不加括号。
"""
import os
import sqlite3
import sys

import yaml

from conftest import auth_headers, setup_admin


def _yaml(text: str) -> dict:
    return yaml.safe_load(text)


def _make_node(client, h, name="HK-01", node_type=None, protocol="ss"):
    body = {
        "name": name, "protocol": protocol, "server": "hk.example.com",
        "port": 8388,
        "params": {"cipher": "aes-256-gcm", "password": "secret", "udp": True},
    }
    if node_type is not None:
        body["node_type"] = node_type
    return client.post("/api/v1/local-nodes", headers=h, json=body)


def test_node_type_defaults_to_local(client):
    """不传类型时默认「本地」。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h).json()
    assert node["node_type"] == "本地"
    assert node["display_name"] == "HK-01 (本地)"
    # 数据库里存的是纯名称，类型单独存放
    assert node["name"] == "HK-01"


def test_display_name_appends_type(client):
    """产物标识 = 名称 (类型)。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h, name="🇺🇸 美国机房 01", node_type="家宽").json()
    assert node["display_name"] == "🇺🇸 美国机房 01 (家宽)"

    empty = _make_node(client, h, name="NoType", node_type="").json()
    assert empty["node_type"] == ""
    assert empty["display_name"] == "NoType"


def test_invalid_node_type_is_rejected(client):
    """类型必须在白名单内。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = _make_node(client, h, name="坏类型", node_type="随便写")
    assert r.status_code == 400
    assert "节点类型" in r.json()["detail"]


def test_schema_exposes_node_types(client):
    """前端下拉的数据来自服务端 schema。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    schema = client.get("/api/v1/local-nodes/schema", headers=h).json()
    assert schema["node_types"] == ["本地", "自建", "家宽", "机房", "专线", "中转", "落地"]
    assert schema["default_node_type"] == "本地"
    assert "mark" not in schema


def test_artifact_uses_display_name_consistently(client):
    """产物里的 proxies 名与策略组成员名必须完全一致，否则组引用不到节点。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h, name="JP-01", node_type="机房").json()
    client.post("/api/v1/groups", headers=h, json={
        "name": "手动节点", "type": "select", "proxies": ["DIRECT"],
        "local_nodes": [node["id"]],
    })
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "手动节点"})

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    cfg = _yaml(art)
    proxy_names = [p["name"] for p in cfg["proxies"]]
    assert "JP-01 (机房)" in proxy_names
    assert "JP-01" not in proxy_names
    group = next(g for g in cfg["proxy-groups"] if g["name"] == "手动节点")
    assert "JP-01 (机房)" in group["proxies"]
    # 顶层 proxies 与组成员用的是同一个名字
    assert set(group["proxies"]) <= set(proxy_names) | {"DIRECT", "空组保护"}


def test_updating_type_changes_artifact_name(client):
    """改类型后产物里的名字跟着变。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h, name="SG-01", node_type="本地").json()
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "手动节点", "type": "select", "proxies": ["DIRECT"],
        "local_nodes": [node["id"]],
    })
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "手动节点"})

    updated = client.put(f"/api/v1/local-nodes/{node['id']}", headers=h, json={
        "name": node["name"], "node_type": "中转", "protocol": node["protocol"],
        "server": node["server"], "port": node["port"],
        "params": node["params"], "extra_yaml": node["extra_yaml"],
        "enabled": True,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "SG-01 (中转)"

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    assert "SG-01 (中转)" in art
    assert "SG-01 (本地)" not in art


def _prepare_old_db(path) -> None:
    """造一个"没有类型字段、名称里带 [单] 前缀"的旧库。"""
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE local_nodes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      protocol TEXT NOT NULL,
      server TEXT NOT NULL,
      port INTEGER NOT NULL,
      params_enc TEXT NOT NULL DEFAULT '',
      extra_yaml_enc TEXT NOT NULL DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 1,
      sort INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    """)
    conn.execute("INSERT INTO local_nodes(name, protocol, server, port, created_at, "
                 "updated_at) VALUES('[单] 旧节点', 'ss', 'a.example.com', 8388, "
                 "'2026-01-01T00:00:00+08:00', '2026-01-01T00:00:00+08:00')")
    conn.execute("INSERT INTO local_nodes(name, protocol, server, port, created_at, "
                 "updated_at) VALUES('[本地] 另一个', 'ss', 'b.example.com', 8388, "
                 "'2026-01-01T00:00:00+08:00', '2026-01-01T00:00:00+08:00')")
    conn.commit()
    conn.close()


def test_migration_adds_type_and_cleans_legacy_prefix(tmp_path):
    """迁移：补类型列 + 清理名称里的旧前缀。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _prepare_old_db(data_dir / "magicpanel.db")

    os.environ["MAGICPANEL_DATA_DIR"] = str(data_dir)
    os.environ["MAGICPANEL_SCHEDULER"] = "0"
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from app import db
    db.init_db()

    conn = db.connect()
    rows = {r["name"]: r["node_type"] for r in conn.execute(
        "SELECT name, node_type FROM local_nodes")}
    assert rows == {"旧节点": "本地", "另一个": "本地"}
    conn.close()
