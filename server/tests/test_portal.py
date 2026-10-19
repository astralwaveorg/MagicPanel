"""门户展示页：PIN 与维护者账号绑定、失败锁定、订阅地址还原。"""
from conftest import auth_headers, setup_admin


def _make_device(client, h):
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    r = client.post("/api/v1/devices", headers=h, json={
        "name": "展示手机", "platform": "ios", "target_id": 1, "channel": "stable"})
    assert r.status_code == 201, r.text
    return r.json()


def test_portal_pin_flow(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)

    # 未设置 PIN：状态关闭，取数 404
    assert client.get("/api/v1/portal/status").json() == {"enabled": False}
    r = client.post("/api/v1/portal/data", json={"pin": "1234"})
    assert r.status_code == 404

    # 非 4 位数字直接被参数校验拒绝
    assert client.post("/api/v1/portal/my-pin", headers=h,
                       json={"pin": "12ab"}).status_code == 422

    # 设置 PIN 后：错误 PIN 403，错误次数累计到上限后锁定
    assert client.post("/api/v1/portal/my-pin", headers=h,
                       json={"pin": "2468"}).status_code == 201
    assert client.get("/api/v1/portal/status").json() == {"enabled": True}
    assert client.get("/api/v1/auth/me").json()["has_portal_pin"] is True
    for _ in range(5):
        assert client.post("/api/v1/portal/data",
                           json={"pin": "0000"}).status_code == 403
    assert client.post("/api/v1/portal/data", json={"pin": "2468"}).status_code == 429

    # 撤销本人 PIN 后门户关闭（无其他 PIN 时）
    assert client.delete("/api/v1/portal/my-pin", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me").json()["has_portal_pin"] is False
    assert client.post("/api/v1/portal/data", json={"pin": "2468"}).status_code == 404


def test_portal_pin_bound_to_user(client):
    """两位维护者各自的 PIN 都能进入门户；撤销其一不影响另一个。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/users", headers=h, json={
        "username": "second", "password": "second-pass-1", "display_name": "二号"})
    client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "1111"})

    r = client.post("/api/v1/auth/login",
                    json={"username": "second", "password": "second-pass-1"})
    csrf2 = r.json()["csrf_token"]
    h2 = auth_headers(csrf2)
    client.post("/api/v1/portal/my-pin", headers=h2, json={"pin": "2222"})

    assert client.post("/api/v1/portal/data", json={"pin": "1111"}).status_code == 200
    assert client.post("/api/v1/portal/data", json={"pin": "2222"}).status_code == 200

    # 用户列表只暴露是否设置，不暴露 PIN 本身
    users = client.get("/api/v1/users").json()
    assert all(u["has_portal_pin"] for u in users)
    assert all("portal_pin_hash" not in u for u in users)

    # 撤销 second 的 PIN：2222 失效，1111 仍可用
    client.delete("/api/v1/portal/my-pin", headers=h2)
    assert client.post("/api/v1/portal/data", json={"pin": "2222"}).status_code == 403
    assert client.post("/api/v1/portal/data", json={"pin": "1111"}).status_code == 200


def test_portal_data_content(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    dev = _make_device(client, h)
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "example.com", "target": "DIRECT",
        "note": "内网直连"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "RULE-SET", "value": "https://example.com/list.yaml",
        "target": "PROXY"})
    client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "1357"})

    r = client.post("/api/v1/portal/data", json={"pin": "1357"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["devices"][0]["subscription_url"] == dev["subscription_url"]
    assert data["devices"][0]["engine"] == "stash"
    assert len(data["clients"]) >= 5 and data["guides"]
    # 个人规则不含 RULE-SET（公共规则来源不在门户展示）
    assert [x["type"] for x in data["rules"]] == ["DOMAIN-SUFFIX"]

    # 轮换令牌后 reveal 返回新地址，门户同步更新
    r = client.post(f"/api/v1/devices/{dev['id']}/rotate-token", headers=h)
    new_url = r.json()["subscription_url"]
    r = client.post(f"/api/v1/devices/{dev['id']}/reveal", headers=h)
    assert r.status_code == 200
    assert r.json()["subscription_url"] == new_url
    data = client.post("/api/v1/portal/data", json={"pin": "1357"}).json()
    assert data["devices"][0]["subscription_url"] == new_url
