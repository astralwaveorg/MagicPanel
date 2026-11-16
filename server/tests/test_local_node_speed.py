"""旧同步测速入口已退场；手动请求只创建受管探测任务。"""
from conftest import auth_headers, setup_admin


def _make_node(client, h, name="HK-01", protocol="ss"):
    return client.post("/api/v1/local-nodes", headers=h, json={
        "name": name, "node_type": "本地", "protocol": protocol,
        "server": "hk.example.com", "port": 8388,
        "params": {"password": "secret", "udp": True,
                   **({"cipher": "aes-256-gcm"} if protocol == "ss" else {})},
    }).json()


def test_node_test_creates_job_without_running_core(client, monkeypatch):
    from app import db
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h)
    with db.connect() as conn:
        catalog = db.one(conn, "SELECT node_uid FROM node_catalog WHERE local_node_id=?", (node["id"],))

    def forbidden(proxy):
        raise AssertionError("旧同步核心探测不应被手动测速入口启动")

    monkeypatch.setattr(tester, "test_proxy", forbidden)
    response = client.post(f"/api/v1/local-nodes/{node['id']}/test", headers=h)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert response.json()["state"] == "queued"
    assert response.json()["poll"] == f"/api/v1/probe-jobs/{job_id}"

    with db.connect() as conn:
        row = db.one(conn, "SELECT * FROM local_nodes WHERE id=?", (node["id"],))
    assert row["test_status"] == "" and row["tested_at"] is None

    detail = client.get(f"/api/v1/probe-jobs/{job_id}", headers=h).json()
    assert detail["job"]["id"] == job_id
    assert detail["items"][0]["node_uid"] == catalog["node_uid"]
    assert detail["items"][0]["state"] == "queued"
    assert "password" not in str(detail)


def test_node_test_missing_node_returns_404(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    response = client.post("/api/v1/local-nodes/999999/test", headers=h)
    assert response.status_code == 404
