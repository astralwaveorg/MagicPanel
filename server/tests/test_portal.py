"""门户展示页：PIN 与维护者账号绑定、失败锁定、订阅地址还原。

TestClient 会保留登录 Cookie；凡匿名访问用例先清 Cookie。
"""
from conftest import auth_headers, setup_admin
from test_api import make_policy, publish_to_prod


def _anonymous(client):
    client.cookies.clear()


def _make_device(client, h):
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    r = client.post("/api/v1/devices", headers=h, json={
        "name": "展示手机", "platform": "ios", "target_id": 1, "env": "production"})
    assert r.status_code == 201, r.text
    return r.json()


def test_portal_pin_flow(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)

    # 未设置 PIN：状态关闭，匿名取数 404
    assert client.get("/api/v1/portal/status").json() == {"enabled": False}
    _anonymous(client)
    r = client.post("/api/v1/portal/data", json={"pin": "1234"})
    assert r.status_code == 404

    # 非 4 位数字直接被参数校验拒绝（登录态下）
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "admin-pass-1"})
    h = auth_headers(r.json()["csrf_token"])
    assert client.post("/api/v1/portal/my-pin", headers=h,
                       json={"pin": "12ab"}).status_code == 422

    # 设置 PIN 后：错误 PIN 403，错误次数累计到上限后锁定
    assert client.post("/api/v1/portal/my-pin", headers=h,
                       json={"pin": "2468"}).status_code == 201
    assert client.get("/api/v1/portal/status").json() == {"enabled": True}
    assert client.get("/api/v1/auth/me").json()["has_portal_pin"] is True
    _anonymous(client)
    for _ in range(5):
        assert client.post("/api/v1/portal/data",
                           json={"pin": "0000"}).status_code == 403
    assert client.post("/api/v1/portal/data", json={"pin": "2468"}).status_code == 429

    # 撤销本人 PIN 后门户关闭（无其他 PIN 时）
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "admin-pass-1"})
    h = auth_headers(r.json()["csrf_token"])
    assert client.delete("/api/v1/portal/my-pin", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me").json()["has_portal_pin"] is False
    _anonymous(client)
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

    _anonymous(client)
    assert client.post("/api/v1/portal/data", json={"pin": "1111"}).status_code == 200
    assert client.post("/api/v1/portal/data", json={"pin": "2222"}).status_code == 200

    # 用户列表只暴露是否设置，不暴露 PIN 本身
    client.post("/api/v1/auth/login",
                json={"username": "admin", "password": "admin-pass-1"})
    users = client.get("/api/v1/users").json()
    assert all(u["has_portal_pin"] for u in users)
    assert all("portal_pin_hash" not in u for u in users)

    # 撤销 second 的 PIN：2222 失效，1111 仍可用
    r = client.post("/api/v1/auth/login",
                    json={"username": "second", "password": "second-pass-1"})
    h2 = auth_headers(r.json()["csrf_token"])
    client.delete("/api/v1/portal/my-pin", headers=h2)
    _anonymous(client)
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

    _anonymous(client)
    r = client.post("/api/v1/portal/data", json={"pin": "1357"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["devices"][0]["subscription_url"] == dev["subscription_url"]
    assert data["devices"][0]["engine"] == "stash"
    assert len(data["clients"]) >= 5 and data["guides"]
    # 个人规则不含 RULE-SET；规则来源只展示元信息
    assert [x["type"] for x in data["rules"]] == ["DOMAIN-SUFFIX"]
    assert "rule_providers" in data

    # 轮换令牌后 reveal 返回新地址，门户同步更新
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "admin-pass-1"})
    h = auth_headers(r.json()["csrf_token"])
    r = client.post(f"/api/v1/devices/{dev['id']}/rotate-token", headers=h)
    new_url = r.json()["subscription_url"]
    r = client.post(f"/api/v1/devices/{dev['id']}/reveal", headers=h)
    assert r.status_code == 200
    assert r.json()["subscription_url"] == new_url
    _anonymous(client)
    data = client.post("/api/v1/portal/data", json={"pin": "1357"}).json()
    assert data["devices"][0]["subscription_url"] == new_url


def test_portal_provider_detail(client):
    """规则来源：首屏只给元信息，原始内容按需拉取。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/rule-providers", headers=h, json={
        "name": "demo", "behavior": "domain", "format": "yaml", "kind": "inline",
        "inline_content": "# 说明: 演示集合\npayload:\n  - +.example.com\n"})
    client.post("/api/v1/rule-providers", headers=h, json={
        "name": "remote-demo", "behavior": "ipcidr", "format": "yaml", "kind": "remote",
        "url": "https://cdn.jsdelivr.net/gh/astralwaveorg/magic-sets@main/rule/demo.yaml"})
    client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "1357"})

    _anonymous(client)
    data = client.post("/api/v1/portal/data", json={"pin": "1357"}).json()
    by_name = {p["name"]: p for p in data["rule_providers"]}
    assert "demo" in by_name and "remote-demo" in by_name

    demo = by_name["demo"]
    assert demo["behavior"] == "domain" and demo["kind"] == "inline"
    assert demo["desc"] == "演示集合"
    # 首屏只有元信息，不带原始内容
    assert "content" not in demo and "preview" not in demo
    # 内联来源没有上游地址
    assert demo["url"] == ""
    remote = by_name["remote-demo"]
    assert remote["origin"] == "astralwaveorg/magic-sets"
    assert remote["url"].endswith("rule/demo.yaml")
    assert remote["behavior"] == "ipcidr"

    # 详情按需拉，带内容预览
    r = client.post("/api/v1/portal/provider-detail", json={"name": "demo", "pin": "1357"})
    assert r.status_code == 200, r.text
    detail = r.json()
    assert "payload:" in detail["preview"]
    assert detail["truncated"] is False
    assert detail["total_lines"] == 3

    # 未登录又不带 PIN：拒绝；名字不存在：404
    _anonymous(client)
    assert client.post("/api/v1/portal/provider-detail",
                       json={"name": "demo"}).status_code == 401
    assert client.post("/api/v1/portal/provider-detail",
                       json={"name": "nope", "pin": "1357"}).status_code == 404


def test_portal_preview_url_points_to_same_token(client):
    """门户给每个设备一个「看配置源码」的地址：同一枚令牌，只多一个 preview 标记。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _make_device(client, h)
    client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "1357"})
    _anonymous(client)
    data = client.post("/api/v1/portal/data", json={"pin": "1357"}).json()
    dev = data["devices"][0]
    assert dev["preview_url"].endswith("/config.yaml?preview=1")
    sub_token = dev["subscription_url"].split("/feed/")[1].split("/")[0]
    prev_token = dev["preview_url"].split("/feed/")[1].split("/")[0]
    assert sub_token == prev_token


def test_preview_is_same_content_but_not_a_pull(client):
    """预览与下发同一份产物，但不记拉取、不带 #SUBSCRIBED、内联展示。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    target = client.get("/api/v1/targets", headers=h).json()[0]
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "预览机", "platform": target["platform"], "target_id": target["id"]}).json()
    bid = client.post("/api/v1/builds", headers=h, json={}).json()["id"]
    publish_to_prod(client, h, bid)
    token = dev["token"]

    normal = client.get(f"/feed/{token}/config.yaml")
    assert normal.status_code == 200, normal.text
    assert normal.headers["content-disposition"].startswith("attachment")
    assert normal.text.startswith("#SUBSCRIBED ")

    row = client.get("/api/v1/devices", headers=h).json()[0]
    pulled_at = row["last_config_at"]
    pulls = row["pull_count"]
    assert pulled_at is not None

    preview = client.get(f"/feed/{token}/config.yaml?preview=1")
    assert preview.status_code == 200, preview.text
    # 新标签页直接显示文本，而不是触发下载
    assert preview.headers["content-disposition"].startswith("inline")
    # 内容与下发完全一致，只差 #SUBSCRIBED 那一行提示
    assert not preview.text.startswith("#SUBSCRIBED ")
    assert preview.text == normal.text.split("\n", 1)[1]

    # 预览不计入拉取：不能把「人在看」记成「客户端刚更新过」
    row2 = client.get("/api/v1/devices", headers=h).json()[0]
    assert row2["last_config_at"] == pulled_at
    assert row2["pull_count"] == pulls
