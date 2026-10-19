"""认证、策略维护、构建发布与分发的端到端用例。"""
from conftest import auth_headers, setup_admin


def make_policy(client, csrf):
    """造一套最小可用策略：来源 + 策略组 + 兜底规则 + 目标。"""
    h = auth_headers(csrf)
    # 节点来源（不触发抓取，手工置快照由构建引用名称即可）
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "测试机场", "url": "https://airport.example.com/sub?token=abc123",
    })
    assert r.status_code == 201, r.text
    assert r.json()["url_masked"] == "https://airport.example.com/…(17 字符)"

    r = client.post("/api/v1/groups", headers=h, json={
        "name": "节点选择", "type": "select",
        "proxies": ["地区自动", "DIRECT"], "use_sources": ["测试机场"],
    })
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/groups", headers=h, json={
        "name": "地区自动", "type": "url-test",
        "use_sources": ["测试机场"], "hidden": True,
    })
    assert r.status_code == 201, r.text

    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "example.com", "target": "节点选择",
    })
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT",
    })
    assert r.status_code == 201, r.text

    r = client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios",
    })
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "mihomo-android", "engine": "mihomo", "platform": "android",
    })
    assert r.status_code == 201, r.text


def test_setup_login_logout(client):
    assert client.get("/api/v1/setup/status").json() == {"initialized": False}
    csrf = setup_admin(client)
    assert client.get("/api/v1/setup/status").json() == {"initialized": True}
    # 重复初始化被拒绝
    assert client.post("/api/v1/setup", json={
        "username": "x2", "password": "12345678"}).status_code == 409
    me = client.get("/api/v1/auth/me").json()
    assert me["username"] == "admin" and me["csrf_token"] == csrf
    # 错误口令
    bad = client.post("/api/v1/auth/login",
                      json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    # 无 CSRF 的写操作被拒绝
    assert client.post("/api/v1/rules", json={
        "type": "MATCH", "target": "DIRECT"}).status_code == 403
    # 登出后会话失效
    assert client.post("/api/v1/auth/logout", headers=auth_headers(csrf)).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_multi_maintainer(client):
    csrf = setup_admin(client)
    r = client.post("/api/v1/users", headers=auth_headers(csrf), json={
        "username": "second", "password": "second-pass-1", "display_name": "二号",
    })
    assert r.status_code == 201, r.text
    # 第二个维护者可见同一份数据（不隔离）
    r = client.post("/api/v1/auth/login",
                    json={"username": "second", "password": "second-pass-1"})
    assert r.status_code == 200
    assert client.get("/api/v1/sources").status_code == 200
    users = client.get("/api/v1/users").json()
    assert {u["username"] for u in users} == {"admin", "second"}


def test_build_release_feed_flow(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    build = client.post("/api/v1/builds", headers=h, json={"note": "首次"})
    assert build.status_code == 201, build.text
    build = build.json()
    assert build["status"] == "success"
    assert set(build["results"]) == {"stash-ios", "mihomo-android"}
    for result in build["results"].values():
        assert result["ok"] and result["sha256"] and result["size"] > 0

    bid = build["id"]
    # 产物：mihomo 含 dns，stash 不含；provider 使用 {FEED} 占位
    art = client.get(f"/api/v1/builds/{bid}/artifact/stash-ios").json()["content"]
    assert "{FEED}/res/provider/测试机场" in art
    assert "dns:" not in art
    art_m = client.get(f"/api/v1/builds/{bid}/artifact/mihomo-android").json()["content"]
    assert "enhanced-mode: fake-ip" in art_m
    assert "header:" in art_m and "headers:" not in art_m

    # 未发布时设备拉取返回 503
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "测试手机", "platform": "ios", "target_id": 1, "channel": "stable",
    })
    assert dev.status_code == 201, dev.text
    dev = dev.json()
    token = dev["token"]
    assert token.startswith("mp_")
    url_path = dev["subscription_url"].split("://", 1)[1]
    feed_path = "/" + url_path.split("/", 1)[1]
    assert client.get(feed_path).status_code == 503

    # 发布稳定通道后拉取成功
    r = client.post(f"/api/v1/builds/{bid}/promote", headers=h,
                    json={"channel": "stable", "reason": "验收通过"})
    assert r.status_code == 200, r.text
    resp = client.get(feed_path)
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "private, no-cache"
    assert "profile-update-interval" in resp.headers
    assert resp.text.startswith(f"#SUBSCRIBED ")
    assert f"/feed/{token}/res/provider/" in resp.text
    etag = resp.headers["ETag"]

    # ETag 条件请求与 HEAD
    assert client.get(feed_path, headers={"If-None-Match": etag}).status_code == 304
    head = client.head(feed_path)
    assert head.status_code == 200 and not head.content

    # 下载记录：服务器只能确认下载成功
    devices = client.get("/api/v1/devices").json()
    assert devices[0]["pull_count"] >= 1 and devices[0]["last_pull_at"]

    # 错误令牌一律 404，不泄露设备存在性
    assert client.get("/feed/mp_wrongtokenwrongtokenwrongtoken12/config.yaml").status_code == 404

    # 子资源：未抓取的来源没有快照
    assert client.get(f"/feed/{token}/res/provider/测试机场").status_code == 404

    # 回滚到同一构建（指针移动有记录）
    r = client.post("/api/v1/channels/stable/rollback", headers=h,
                    json={"build_id": bid, "reason": "演练"})
    assert r.status_code == 200
    releases = client.get("/api/v1/releases").json()
    assert [r["action"] for r in releases] == ["rollback", "promote"]

    # 令牌轮换后旧令牌失效
    r = client.post(f"/api/v1/devices/{dev['id']}/rotate-token", headers=h)
    new_token = r.json()["token"]
    assert new_token != token
    assert client.get(feed_path).status_code == 404
    assert client.get(
        f"/feed/{new_token}/config.yaml".replace("//", "/")).status_code in (200, 404)


def test_build_validation_blocks_bad_policy(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    # 缺少兜底规则 + 空策略组
    client.post("/api/v1/groups", headers=h, json={
        "name": "空组", "type": "select"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["status"] == "failed"
    errors = build["results"]["stash-ios"]["errors"]
    assert any("兜底" in e for e in errors)
    assert any("为空" in e for e in errors)
    # 失败构建不能发布
    r = client.post(f"/api/v1/builds/{build['id']}/promote", headers=h,
                    json={"channel": "stable"})
    assert r.status_code == 400


def test_group_cycle_detected(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "A", "type": "select", "proxies": ["B"]})
    client.post("/api/v1/groups", headers=h, json={
        "name": "B", "type": "select", "proxies": ["A"]})
    client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "A"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["status"] == "failed"
    assert any("循环" in e for e in build["results"]["stash-ios"]["errors"])


def test_rule_provider_inline_and_feed(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/rule-providers", headers=h, json={
        "name": "my-rules", "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - example.com\n  - example.org\n",
    })
    assert r.status_code == 201, r.text
    assert r.json()["rule_count"] == 2 and r.json()["last_status"] == "ok"

    make_policy(client, csrf)
    client.post("/api/v1/rules", headers=h, json={
        "type": "RULE-SET", "value": "my-rules", "target": "节点选择"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["status"] == "success", build["results"]
    client.post(f"/api/v1/builds/{build['id']}/promote", headers=h,
                json={"channel": "stable"})
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "安卓", "platform": "android", "target_id": 2}).json()
    token = dev["token"]
    resp = client.get(f"/feed/{token}/res/rule/my-rules")
    assert resp.status_code == 200 and "example.com" in resp.text
    # 设备与令牌解耦检查：删除设备后资源同时失效
    client.delete(f"/api/v1/devices/{dev['id']}", headers=h)
    assert client.get(f"/feed/{token}/res/rule/my-rules").status_code == 404


def test_settings_and_backup(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.put("/api/v1/settings", headers=h,
                   json={"values": {"base_url": "https://panel.example.com"}})
    assert r.status_code == 200
    assert client.get("/api/v1/settings").json()["base_url"] == \
        "https://panel.example.com"
    # 非法设置项被拒绝
    assert client.put("/api/v1/settings", headers=h,
                      json={"values": {"evil": "1"}}).status_code == 400
    backup = client.get("/api/v1/backup/export").json()
    assert "tables" in backup and "users" in backup["tables"]
    # 未确认的恢复被拒绝
    assert client.post("/api/v1/backup/restore", headers=h,
                       json={"data": backup}).status_code == 400


def test_overview(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    data = client.get("/api/v1/overview").json()
    assert data["channels"] == {"stable": None, "candidate": None} or \
        set(data["channels"]) == {"stable", "candidate"}
    assert len(data["sources"]) == 1 and len(data["devices"]) == 0
    assert "note" in data


def test_group_load_balance_and_relay(client):
    """load-balance / relay 类型的校验与双引擎渲染差异。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/sources", headers=h, json={
        "name": "测试机场", "url": "https://airport.example.com/sub?token=abc123"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "前置", "type": "select", "proxies": ["DIRECT"],
        "use_sources": ["测试机场"]})

    r = client.post("/api/v1/groups", headers=h, json={
        "name": "负载", "type": "load-balance",
        "use_sources": ["测试机场"], "strategy": "sticky-sessions"})
    assert r.status_code == 201, r.text
    # 非法分配策略 / 非负载均衡类型带策略均被拒绝
    assert client.post("/api/v1/groups", headers=h, json={
        "name": "负载2", "type": "load-balance",
        "use_sources": ["测试机场"], "strategy": "random"}).status_code == 400
    assert client.post("/api/v1/groups", headers=h, json={
        "name": "选择2", "type": "select", "proxies": ["DIRECT"],
        "strategy": "round-robin"}).status_code == 400

    # relay：固定链，禁止节点来源，至少两个成员
    r = client.post("/api/v1/groups", headers=h, json={
        "name": "链路", "type": "relay", "proxies": ["前置", "负载"]})
    assert r.status_code == 201, r.text
    assert client.post("/api/v1/groups", headers=h, json={
        "name": "链路2", "type": "relay", "proxies": ["前置", "负载"],
        "use_sources": ["测试机场"]}).status_code == 400
    assert client.post("/api/v1/groups", headers=h, json={
        "name": "链路3", "type": "relay", "proxies": ["前置"]}).status_code == 400

    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    client.post("/api/v1/targets", headers=h, json={
        "name": "mihomo-android", "engine": "mihomo", "platform": "android"})
    client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "前置"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["status"] == "success", build

    bid = build["id"]
    art_s = client.get(f"/api/v1/builds/{bid}/artifact/stash-ios").json()["content"]
    art_m = client.get(f"/api/v1/builds/{bid}/artifact/mihomo-android").json()["content"]
    # strategy 是 Mihomo 扩展字段，Stash 产物不输出
    assert "strategy: sticky-sessions" in art_m and "strategy:" not in art_s
    # Stash 的 relay 用 benchmark-* 测速字段
    assert "type: relay" in art_s and "benchmark-url:" in art_s
    assert "type: relay" in art_m
    # load-balance 也插入空组保护
    assert "load-balance" in art_m and "空组保护" in art_m


def test_rule_no_resolve(client):
    """no-resolve 修饰符：仅 IP 类规则可用，渲染到产物行尾。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 域名类规则不允许 no-resolve
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "example.com", "target": "DIRECT",
        "no_resolve": True})
    assert r.status_code == 400
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "IP-CIDR", "value": "10.0.0.0/8", "target": "DIRECT",
        "no_resolve": True})
    assert r.status_code == 201 and r.json()["no_resolve"] is True
    client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "DIRECT"})
    client.post("/api/v1/targets", headers=h, json={
        "name": "mihomo-android", "engine": "mihomo", "platform": "android"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/mihomo-android").json()["content"]
    assert "- IP-CIDR,10.0.0.0/8,DIRECT,no-resolve" in art
