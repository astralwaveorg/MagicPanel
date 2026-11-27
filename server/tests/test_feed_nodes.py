"""门户「全部节点」订阅：令牌、配置形状与来源过滤。"""
import base64
import json

import yaml

from conftest import auth_headers, setup_admin


def _make_node(client, h, name="US-01"):
    resp = client.post("/api/v1/local-nodes", headers=h, json={
        "name": name, "node_type": "机房", "protocol": "ss",
        "server": "node.example.com", "port": 8388,
        "params": {"cipher": "aes-256-gcm", "password": "example-test-password"}})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_nodes_feed_requires_valid_token(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 未生成令牌前，任意令牌都是 404
    assert client.get("/feed/nodes/whatever-token.yaml").status_code == 404
    data = client.post("/api/v1/portal/data", headers=h, json={"pin": ""})
    assert data.status_code == 200, data.text
    feed = data.json()["nodes_feed"]
    assert "/feed/nodes/" in feed["url"] and "node_count" in feed
    # 错误令牌 404；正确令牌 200
    assert client.get("/feed/nodes/wrong-token.yaml").status_code == 404
    ok = client.get(feed["url"])
    assert ok.status_code == 200, ok.text
    assert "magicpanel-nodes" in ok.headers.get("Content-Disposition", "")


def test_nodes_feed_shape_contains_all_enabled_nodes(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h, "US-01")
    _make_node(client, h, "JP-02")
    client.patch(f"/api/v1/local-nodes/{node['id']}/enabled", headers=h,
                 json={"enabled": False})
    data = client.post("/api/v1/portal/data", headers=h, json={"pin": ""}).json()
    body = client.get(data["nodes_feed"]["url"]).text
    # 停用节点不进列表；启用节点在列
    assert "US-01" not in body and "JP-02" in body
    doc = yaml.safe_load(body)
    names = [p["name"] for p in doc["proxies"]]
    # 本地节点用用户自定义名（不带类型后缀），与产物一致
    assert names == ["JP-02"]
    # NodeList 形态：纯 proxies 段，不再附带策略组与兜底规则
    assert "proxy-groups" not in doc and "rules" not in doc
    assert doc["proxies"]


def test_nodes_feed_respects_source_health_filter_without_losing_probe_candidates(client):
    from app import db
    from app.services import scheduler

    headers = auth_headers(setup_admin(client))
    _make_node(client, headers)
    for source, prefix, filter_unavailable in (
        ("甲机场", "filtered", True),
        ("乙机场", "unfiltered", False),
    ):
        nodes = [
            {"name": f"{raw_name} {prefix}", "type": "ss", "server": f"{prefix}-{suffix}.example.com",
             "port": 8388, "cipher": "aes-256-gcm", "password": "example-test-password"}
            for raw_name, suffix in (("美国失败线路", "failed"), ("日本可用线路", "ok"),
                                     ("香港新线路", "untested"))
        ]
        response = client.post("/api/v1/sources/import-file", headers=headers, json={
            "name": source, "mode": "inline",
            "content_b64": base64.b64encode(yaml.safe_dump({"proxies": nodes}).encode()).decode(),
        })
        assert response.status_code == 201, response.text
        with db.tx() as conn:
            conn.execute("UPDATE sources SET filter_unavailable=?,test_results=? WHERE name=?",
                         (filter_unavailable, json.dumps({f"美国失败线路 {prefix}": -1,
                                                         f"日本可用线路 {prefix}": 120}),
                          source))

    portal = client.post("/api/v1/portal/data", headers=headers, json={"pin": ""}).json()
    response = client.get(portal["nodes_feed"]["url"])
    assert response.status_code == 200
    servers = {p["server"] for p in yaml.safe_load(response.text)["proxies"]}
    assert servers == {"node.example.com", "filtered-ok.example.com", "filtered-untested.example.com",
                       "unfiltered-failed.example.com", "unfiltered-ok.example.com",
                       "unfiltered-untested.example.com"}
    assert int(response.headers["X-MagicPanel-Node-Count"]) == len(servers)
    # 失败节点只是不发给客户端；后台仍能探测它恢复了没有。
    candidates = {p["server"] for p in scheduler._collect_probe_proxies()}
    assert candidates == servers | {"filtered-failed.example.com"}


def test_rotate_nodes_token_invalidates_old_link(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _make_node(client, h)
    old = client.post("/api/v1/portal/data", headers=h, json={"pin": ""}).json()["nodes_feed"]
    assert client.get(old["url"]).status_code == 200
    rotated = client.post("/api/v1/portal/rotate-nodes-token", headers=h, json={"pin": ""})
    assert rotated.status_code == 200, rotated.text
    # 旧链接立即失效，门户数据给出新链接
    assert client.get(old["url"]).status_code == 404
    fresh = client.post("/api/v1/portal/data", headers=h, json={"pin": ""}).json()["nodes_feed"]
    assert fresh["url"] != old["url"]
    assert client.get(fresh["url"]).status_code == 200


def test_nodes_feed_preview_no_store_and_304(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _make_node(client, h)
    data = client.post("/api/v1/portal/data", headers=h, json={"pin": ""}).json()
    url = data["nodes_feed"]["url"]
    first = client.get(url)
    etag = first.headers["ETag"]
    # 正常拉取支持 304 协商
    again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304
    # 预览不协商、不缓存
    preview = client.get(url + "?preview=1")
    assert preview.status_code == 200
    assert preview.headers["Cache-Control"] == "no-store"
