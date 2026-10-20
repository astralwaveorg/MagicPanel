"""头像上传与门户免 PIN。"""
from conftest import auth_headers, setup_admin

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x05\x05\x02\x02\xec\xb9\x14\x9d\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


def test_avatar_flow(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    uid = client.get("/api/v1/auth/me").json()["id"]

    # 未设置时 404
    assert client.get(f"/api/v1/users/{uid}/avatar").status_code == 404

    # 类型不符与伪造内容被拒
    r = client.post("/api/v1/auth/avatar", content=PNG_1PX, headers={**h, "Content-Type": "text/plain"})
    assert r.status_code == 400
    r = client.post("/api/v1/auth/avatar", content=b"not-a-png", headers={**h, "Content-Type": "image/png"})
    assert r.status_code == 400

    # 正常上传、读取、再删除
    r = client.post("/api/v1/auth/avatar", content=PNG_1PX, headers={**h, "Content-Type": "image/png"})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me").json()["has_avatar"] is True
    assert client.get("/api/v1/users").json()[0]["has_avatar"] is True
    r = client.get(f"/api/v1/users/{uid}/avatar")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content == PNG_1PX

    assert client.delete("/api/v1/auth/avatar", headers=h).status_code == 200
    assert client.get(f"/api/v1/users/{uid}/avatar").status_code == 404
    assert client.get("/api/v1/auth/me").json()["has_avatar"] is False


def test_portal_session_bypasses_pin(client):
    """已登录维护者访问门户数据无需 PIN；未登录仍需。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    client.post("/api/v1/devices", headers=h, json={
        "name": "手机", "platform": "ios", "target_id": 1})

    # 未设置任何 PIN：未登录提示输入 PIN，已登录可取数
    client.cookies.clear()
    assert client.post("/api/v1/portal/data", json={"pin": ""}).status_code == 401
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "admin-pass-1"})
    h = auth_headers(r.json()["csrf_token"])
    r = client.post("/api/v1/portal/data", json={"pin": ""})
    assert r.status_code == 200 and r.json()["devices"]

    # 设置 PIN 后未登录访客按 PIN 进入，已登录仍免 PIN
    client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "246810"})
    client.cookies.clear()
    assert client.post("/api/v1/portal/data", json={"pin": "246810"}).status_code == 200
    client.post("/api/v1/auth/login",
                json={"username": "admin", "password": "admin-pass-1"})
    assert client.post("/api/v1/portal/data", json={"pin": ""}).status_code == 200
