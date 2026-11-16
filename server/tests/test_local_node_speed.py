"""手动测速走本地 Mihomo 核心：同步返回延迟，落库 test_status / test_delay。

受管探测（/api/v1/probe-jobs）测的是服务可用性观测，需要注册观测视角才有执行者；
它与节点测速不是一回事，不共用入口。
"""
from conftest import auth_headers, setup_admin


def _make_node(client, h, name="HK-01", protocol="ss"):
    return client.post("/api/v1/local-nodes", headers=h, json={
        "name": name, "node_type": "本地", "protocol": protocol,
        "server": "hk.example.com", "port": 8388,
        "params": {"password": "secret", "udp": True,
                   **({"cipher": "aes-256-gcm"} if protocol == "ss" else {})},
    }).json()


def test_node_test_runs_core_and_records_result(client, monkeypatch):
    from app import db
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h)

    def fake_test_proxy(proxy):
        assert proxy["type"] == "ss" and proxy["password"] == "secret"
        return {"ok": True, "delay": 123, "name": proxy["name"]}

    monkeypatch.setattr(tester, "test_proxy", fake_test_proxy)
    response = client.post(f"/api/v1/local-nodes/{node['id']}/test", headers=h)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["delay"] == 123
    assert body["status"] == "ok" and body["tested_at"]

    with db.connect() as conn:
        row = db.one(conn, "SELECT test_status, test_delay, tested_at FROM local_nodes WHERE id=?",
                     (node["id"],))
    assert row["test_status"] == "ok" and row["test_delay"] == 123
    assert row["tested_at"]


def test_node_test_failure_is_recorded_not_raised(client, monkeypatch):
    from app import db
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h)

    monkeypatch.setattr(tester, "test_proxy",
                        lambda proxy: {"ok": False, "delay": -1, "name": proxy["name"]})
    response = client.post(f"/api/v1/local-nodes/{node['id']}/test", headers=h)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False and body["delay"] == 0 and body["status"] == "failed"

    with db.connect() as conn:
        row = db.one(conn, "SELECT test_status, test_delay FROM local_nodes WHERE id=?", (node["id"],))
    assert row["test_status"] == "failed" and row["test_delay"] == 0


def test_node_test_missing_node_returns_404(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    response = client.post("/api/v1/local-nodes/999999/test", headers=h)
    assert response.status_code == 404
