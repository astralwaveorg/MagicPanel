"""本地节点测速：结果记录与展示字段。

测速本身要靠 Mihomo 核心，用例里把它替换成桩，
验证「接口 → 落库 → 出参」这条链路。
"""
from conftest import auth_headers, setup_admin


def _make_node(client, h, name="HK-01", protocol="ss"):
    return client.post("/api/v1/local-nodes", headers=h, json={
        "name": name, "node_type": "本地", "protocol": protocol,
        "server": "hk.example.com", "port": 8388,
        "params": {"cipher": "aes-256-gcm", "password": "secret", "udp": True},
    }).json()


def test_node_test_stores_success(client, monkeypatch):
    """测速通过：状态、延迟与时间都要记下来。"""
    from app import db
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h)

    monkeypatch.setattr(
        tester, "test_proxy",
        lambda proxy: {"ok": True, "delay": 428, "name": proxy["name"]},
    )

    r = client.post(f"/api/v1/local-nodes/{node['id']}/test", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["status"] == "ok"
    assert data["delay"] == 428
    assert data["tested_at"]

    with db.connect() as conn:
        row = db.one(conn, "SELECT * FROM local_nodes WHERE id=?", (node["id"],))
    assert row["test_status"] == "ok"
    assert row["test_delay"] == 428
    assert row["tested_at"]

    # 列表接口带上测速结果
    listed = client.get("/api/v1/local-nodes", headers=h).json()
    item = next(n for n in listed if n["id"] == node["id"])
    assert item["test_status"] == "ok"
    assert item["test_delay"] == 428
    assert item["tested_at"]


def test_node_test_stores_failure(client, monkeypatch):
    """测速失败：状态记为 failed，延迟记 0。"""
    from app import db
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h)

    monkeypatch.setattr(
        tester, "test_proxy",
        lambda proxy: {"ok": False, "delay": -1, "name": proxy["name"]},
    )

    r = client.post(f"/api/v1/local-nodes/{node['id']}/test", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert r.json()["status"] == "failed"
    assert r.json()["delay"] == 0

    with db.connect() as conn:
        row = db.one(conn, "SELECT * FROM local_nodes WHERE id=?", (node["id"],))
    assert row["test_status"] == "failed"
    assert row["test_delay"] == 0


def test_node_test_uses_display_name_and_mihomo_flavor(client, monkeypatch):
    """测速用的节点标识是「名称 (类型)」，协议按 Mihomo 方言渲染。"""
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h, name="🇺🇸 美国机房 01", protocol="trojan")

    seen = {}

    def fake(proxy):
        seen.update(proxy)
        return {"ok": True, "delay": 100, "name": proxy["name"]}

    monkeypatch.setattr(tester, "test_proxy", fake)
    r = client.post(f"/api/v1/local-nodes/{node['id']}/test", headers=h)
    assert r.status_code == 200, r.text
    assert seen["name"] == "🇺🇸 美国机房 01 (本地)"
    assert seen["type"] == "trojan"
    # Mihomo 方言：trojan 用 sni 字段，Stash 才是 servername
    assert "sni" in seen or "servername" not in seen


def test_node_test_without_core_returns_clear_error(client, monkeypatch):
    """核心不可用时给出明确提示，而不是 500。"""
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _make_node(client, h)

    def boom(proxy):
        raise tester.TestError("Mihomo 核心不可用，请先在设置中安装")

    monkeypatch.setattr(tester, "test_proxy", boom)
    r = client.post(f"/api/v1/local-nodes/{node['id']}/test", headers=h)
    assert r.status_code == 400
    assert "核心不可用" in r.json()["detail"]


def test_node_test_missing_node_returns_404(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/local-nodes/999999/test", headers=h)
    assert r.status_code == 404
