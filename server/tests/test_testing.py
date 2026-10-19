"""节点测速与不可用过滤的用例。"""
import json

import yaml
from conftest import auth_headers, setup_admin


SNAPSHOT = """proxies:
  - name: 节点A
    type: ss
    server: a.example.com
    port: 443
  - name: 节点B
    type: vmess
    server: b.example.com
    port: 443
  - name: 节点C
    type: trojan
    server: c.example.com
    port: 443
"""


def _set_snapshot(source_id: int, results: dict, filter_unavailable: bool):
    """直接写入快照与测速结果（绕过抓取，供分发过滤用例使用）。"""
    from app import db, security
    with db.tx() as conn:
        conn.execute(
            "UPDATE sources SET snapshot_enc=?, nodes_meta=?, test_results=?, "
            "filter_unavailable=?, last_status='ok' WHERE id=?",
            (security.encrypt_text(SNAPSHOT),
             json.dumps([{"name": n, "type": t} for n, t in
                         [("节点A", "ss"), ("节点B", "vmess"), ("节点C", "trojan")]],
                        ensure_ascii=False),
             json.dumps(results, ensure_ascii=False),
             int(filter_unavailable), source_id),
        )


def test_filter_snapshot_unit():
    from app.services import tester
    out = tester.filter_snapshot(SNAPSHOT, {"节点B"})
    data = yaml.safe_load(out)
    names = [p["name"] for p in data["proxies"]]
    assert names == ["节点A", "节点C"]
    # 全部失败时返回空列表而不是错误内容
    out = tester.filter_snapshot(SNAPSHOT, {"节点A", "节点B", "节点C"})
    assert yaml.safe_load(out)["proxies"] == []


def test_filter_flag_roundtrip(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "机场", "url": "https://a.example.com/sub", "filter_unavailable": True,
    })
    assert r.status_code == 201 and r.json()["filter_unavailable"] is True
    sid = r.json()["id"]
    r = client.put(f"/api/v1/sources/{sid}", headers=h, json={
        "name": "机场", "filter_unavailable": False,
    })
    assert r.status_code == 200 and r.json()["filter_unavailable"] is False


def test_test_endpoint_requires_snapshot_and_core(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "机场", "url": "https://a.example.com/sub"})
    sid = r.json()["id"]
    # 无快照
    assert client.post(f"/api/v1/sources/{sid}/test", headers=h).status_code == 400
    # 有快照但核心未安装
    _set_snapshot(sid, {}, False)
    resp = client.post(f"/api/v1/sources/{sid}/test", headers=h)
    assert resp.status_code == 400 and "核心" in resp.json()["detail"]


def test_feed_filters_failed_nodes(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "机场", "url": "https://a.example.com/sub", "filter_unavailable": True})
    sid = r.json()["id"]
    _set_snapshot(sid, {"节点A": 123, "节点B": -1, "节点C": 456}, True)

    client.post("/api/v1/groups", headers=h, json={
        "name": "节点选择", "type": "select", "use_sources": ["机场"],
        "proxies": ["DIRECT"]})
    client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "节点选择"})
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["status"] == "success"
    client.post(f"/api/v1/builds/{build['id']}/promote", headers=h,
                json={"channel": "stable"})
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "iPhone", "platform": "ios", "target_id": 1}).json()
    token = dev["token"]

    resp = client.get(f"/feed/{token}/res/provider/机场")
    assert resp.status_code == 200
    names = [p["name"] for p in yaml.safe_load(resp.text)["proxies"]]
    assert names == ["节点A", "节点C"]

    # 关闭过滤后恢复完整快照
    client.put(f"/api/v1/sources/{sid}", headers=h, json={
        "name": "机场", "filter_unavailable": False})
    resp = client.get(f"/feed/{token}/res/provider/机场")
    names = [p["name"] for p in yaml.safe_load(resp.text)["proxies"]]
    assert names == ["节点A", "节点B", "节点C"]
