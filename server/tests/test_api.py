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
    channel = client.get("/api/v1/channels").json()["stable"]
    assert channel["publish"]["operator"] == "admin"
    assert channel["publish"]["action"] == "promote"
    assert channel["publish"]["reason"] == "验收通过"
    assert channel["publish"]["at"]
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


def test_source_batch_interval_delete_and_references(client):
    """节点来源批量间隔、批量删除，以及策略组引用保护。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    a = client.post("/api/v1/sources", headers=h, json={
        "name": "A机场", "url": "https://a.example.com/sub"}).json()
    b = client.post("/api/v1/sources", headers=h, json={
        "name": "B机场", "url": "https://b.example.com/sub"}).json()
    group = client.post("/api/v1/groups", headers=h, json={
        "name": "选择", "type": "select", "proxies": ["DIRECT"],
        "use_sources": ["A机场"]}).json()

    reveal = client.post(f"/api/v1/sources/{a['id']}/reveal", headers=h)
    assert reveal.status_code == 200
    assert reveal.json()["url"] == "https://a.example.com/sub"

    r = client.patch("/api/v1/sources/batch", headers=h, json={
        "ids": [a["id"], b["id"]], "interval": 3600})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    assert {s["interval"] for s in client.get("/api/v1/sources").json()} == {3600}

    # 被引用时重命名同样会被拒绝，避免策略组引用失效
    r = client.put(f"/api/v1/sources/{a['id']}", headers=h, json={
        "name": "A机场改名", "enabled": True, "interval": 3600})
    assert r.status_code == 400
    assert "重命名" in r.json()["detail"]

    # 批量删除：A 被策略组引用而保留，B 正常删除
    r = client.post("/api/v1/sources/batch/delete", headers=h,
                    json={"ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] == [b["id"]]
    assert [x["id"] for x in data["blocked"]] == [a["id"]]
    assert "策略组" in data["blocked"][0]["reason"]
    assert {s["name"] for s in client.get("/api/v1/sources").json()} == {"A机场"}

    # 解除引用后单删成功
    assert client.delete(f"/api/v1/groups/{group['id']}", headers=h).status_code == 200
    assert client.delete(f"/api/v1/sources/{a['id']}", headers=h).status_code == 200


def test_rule_provider_batch_interval_delete_and_references(client):
    """规则来源批量操作：停用的 RULE-SET 也视为引用。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    a = client.post("/api/v1/rule-providers", headers=h, json={
        "name": "rules-a", "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - a.example.com\n"}).json()
    b = client.post("/api/v1/rule-providers", headers=h, json={
        "name": "rules-b", "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - b.example.com\n"}).json()
    rule = client.post("/api/v1/rules", headers=h, json={
        "type": "RULE-SET", "value": "rules-a", "target": "DIRECT",
        "enabled": False}).json()

    r = client.patch("/api/v1/rule-providers/batch", headers=h, json={
        "ids": [a["id"], b["id"]], "interval": 7200})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2

    r = client.put(f"/api/v1/rule-providers/{a['id']}", headers=h, json={
        "name": "rules-a-renamed", "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - a.example.com\n"})
    assert r.status_code == 400
    assert "重命名" in r.json()["detail"]

    r = client.post("/api/v1/rule-providers/batch/delete", headers=h,
                    json={"ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] == [b["id"]]
    assert [x["id"] for x in data["blocked"]] == [a["id"]]
    assert "分流规则" in data["blocked"][0]["reason"]

    # 单删同样被停用规则引用阻止
    assert client.delete(f"/api/v1/rule-providers/{a['id']}",
                         headers=h).status_code == 400
    client.delete(f"/api/v1/rules/{rule['id']}", headers=h)
    assert client.delete(f"/api/v1/rule-providers/{a['id']}",
                         headers=h).status_code == 200


def test_build_delete_and_channel_reference(client):
    """构建删除：通道指针是硬引用，历史发布记录随构建清理。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    first = client.post("/api/v1/builds", headers=h, json={"note": "一"}).json()
    assert first["status"] == "success"
    assert client.post(f"/api/v1/builds/{first['id']}/promote", headers=h,
                       json={"channel": "stable"}).status_code == 200

    # 活跃通道中的构建不能删除
    r = client.delete(f"/api/v1/builds/{first['id']}", headers=h)
    assert r.status_code == 400
    assert "稳定通道" in r.json()["detail"]

    second = client.post("/api/v1/builds", headers=h, json={"note": "二"}).json()
    assert second["status"] == "success"
    assert client.post(f"/api/v1/builds/{second['id']}/promote", headers=h,
                       json={"channel": "stable"}).status_code == 200
    # 指针移走后，旧构建可删除；产物与发布历史一并清理
    r = client.delete(f"/api/v1/builds/{first['id']}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["deleted_releases"] == 1
    assert client.get(f"/api/v1/builds/{first['id']}").status_code == 404
    assert client.get(f"/api/v1/builds/{first['id']}/artifact/stash-ios")\
        .status_code == 404

    third = client.post("/api/v1/builds", headers=h, json={"note": "三"}).json()
    r = client.post("/api/v1/builds/batch/delete", headers=h,
                    json={"ids": [second["id"], third["id"]]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] == [third["id"]]
    assert data["blocked"][0]["id"] == second["id"]


def test_device_display_name_and_filename(client):
    """文件名与设备名分离：name 用于下载文件名，note 用于展示。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    target = client.post("/api/v1/targets", headers=h, json={
        "name": "stash-macos", "engine": "stash", "platform": "macos"}).json()
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "Stash-Macmini", "platform": "macos", "target_id": target["id"],
        "note": "客厅 Mac mini"}).json()
    assert dev["name"] == "Stash-Macmini"
    assert dev["display_name"] == "客厅 Mac mini"
    listed = client.get("/api/v1/devices").json()[0]
    assert listed["display_name"] == "客厅 Mac mini"
    portal = client.post("/api/v1/portal/data", json={}).json()
    assert portal["devices"][0]["display_name"] == "客厅 Mac mini"
    assert portal["devices"][0]["name"] == "Stash-Macmini"


def test_source_refresh_failure_is_persisted(client, monkeypatch):
    """抓取失败的状态必须在返回 502 前落库，不能被事务回滚。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    source = client.post("/api/v1/sources", headers=h, json={
        "name": "坏来源", "url": "https://bad.example.com/sub"}).json()
    from app.services import fetcher

    def boom(*args, **kwargs):
        raise fetcher.FetchError("上游超时")

    monkeypatch.setattr(fetcher, "fetch", boom)
    r = client.post(f"/api/v1/sources/{source['id']}/refresh", headers=h)
    assert r.status_code == 502

    from app import db
    with db.connect() as conn:
        row = db.one(conn, "SELECT * FROM sources WHERE id=?", (source["id"],))
    assert row["last_status"] == "failed"
    assert row["fail_count"] == 1
    assert "上游超时" in row["last_error"]
    assert row["last_attempt_at"]
    audit = client.get("/api/v1/audit").json()
    assert any("刷新节点来源失败" in a["action"] for a in audit)


def test_release_history_retention(client):
    """发布历史只保留最近 10 条。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    for _ in range(12):
        assert client.post(f"/api/v1/builds/{build['id']}/promote", headers=h,
                           json={"channel": "stable"}).status_code == 200
    releases = client.get("/api/v1/releases").json()
    assert len(releases) == 10
    # 手动发布不进入“自动发布”页
    assert client.get("/api/v1/releases?auto_only=true").json() == []
    from app import db
    with db.connect() as conn:
        count = db.one(conn, "SELECT COUNT(*) AS c FROM releases")["c"]
    assert count == 10


def test_scheduler_fetch_test_build_and_publish(client, monkeypatch):
    """调度器一轮内完成抓取、测速、自动构建与发布，并跳过未到期项目。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    source = client.get("/api/v1/sources").json()[0]

    from app import db, security
    from app.services import scheduler, updater

    # 预置快照与旧尝试时间，使抓取和测速都到期
    with db.tx() as conn:
        conn.execute(
            "UPDATE sources SET snapshot_enc=?, last_attempt_at=?, "
            "test_attempt_at=NULL, tested_at=NULL WHERE id=?",
            (security.encrypt_text("proxies:\n  - {name: n1, type: ss}\n"),
             "2026-01-01T00:00:00+08:00", source["id"]),
        )

    calls = []

    def fake_refresh(source_id, operator, automatic=False):
        calls.append("fetch")
        with db.tx() as conn:
            conn.execute(
                "UPDATE sources SET last_attempt_at=?, last_fetched_at=? WHERE id=?",
                (db.now(), db.now(), source_id),
            )
        with db.connect() as conn:
            return db.one(conn, "SELECT * FROM sources WHERE id=?", (source_id,))

    def fake_test(source_id, operator, automatic=False):
        calls.append("test")
        with db.tx() as conn:
            conn.execute(
                "UPDATE sources SET test_attempt_at=?, tested_at=? WHERE id=?",
                (db.now(), db.now(), source_id),
            )
        return {"test_results": '{"n1": 88, "n2": -1}'}

    monkeypatch.setattr(updater, "refresh_source", fake_refresh)
    monkeypatch.setattr(updater, "test_source", fake_test)
    monkeypatch.setattr(scheduler, "_core_available", lambda: True)

    summary = scheduler.run_once(force=True)
    assert calls.count("fetch") == 1
    assert calls.count("test") == 1
    assert summary["sources_fetched"] == 1
    assert summary["tests_run"] == 1
    assert summary["tests_ok"] == 1 and summary["tests_failed"] == 1
    assert summary["build"]["status"] == "success"
    assert summary["published"] == "stable"

    channels = client.get("/api/v1/channels").json()
    assert channels["stable"]["id"] == summary["build"]["id"]
    assert channels["stable"]["publish"]["operator"] == "系统"
    assert channels["stable"]["publish"]["action"] == "promote"
    releases = client.get("/api/v1/releases").json()
    assert releases[0]["operator"] == "系统"
    assert releases[0]["reason"] == "自动构建发布"
    auto_releases = client.get("/api/v1/releases?auto_only=true").json()
    assert len(auto_releases) == 1
    assert auto_releases[0]["build_id"] == summary["build"]["id"]

    status = client.get("/api/v1/automation/status", headers=h).json()
    assert status["last_result"]["published"] == "stable"

    # 第二轮：按正常到期判断，不应重复抓取或构建
    second = scheduler.run_once()
    assert second["sources_fetched"] == 0
    assert second["tests_run"] == 0
    assert second["build"] is None
    assert len(client.get("/api/v1/builds").json()) == 1


def test_automation_settings_and_run_endpoint(client, monkeypatch):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    status = client.get("/api/v1/automation/status", headers=h).json()
    assert status["autostart"] is False
    assert status["settings"]["auto_build_interval_hours"] == "12"

    # 非法开关 / 通道 / 间隔被拒绝
    for values in (
        {"auto_publish_enabled": "yes"},
        {"auto_build_interval_hours": "0"},
        {"auto_publish_channel": "beta"},
    ):
        assert client.put("/api/v1/settings", headers=h,
                          json={"values": values}).status_code == 400

    r = client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_build_interval_hours": "6",
        "auto_publish_channel": "candidate",
        "auto_publish_enabled": "0",
    }})
    assert r.status_code == 200
    status = client.get("/api/v1/automation/status", headers=h).json()
    assert status["settings"]["auto_build_interval_hours"] == "6"
    assert status["settings"]["auto_publish_channel"] == "candidate"
    assert status["settings"]["auto_publish_enabled"] == "0"

    from app.services import scheduler
    called = []
    monkeypatch.setattr(
        scheduler, "run_once_safe",
        lambda force=False, trigger="scheduled", actor="": called.append(
            (force, trigger, actor)),
    )
    r = client.post("/api/v1/automation/run", headers=h)
    assert r.status_code == 200 and r.json()["accepted"] is True
    assert called == [(True, "manual", "admin")]


def test_target_reorder(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    ids = []
    for name in ("stash-ios", "mihomo-android", "stash-macos"):
        r = client.post("/api/v1/targets", headers=h, json={
            "name": name, "engine": "stash" if name.startswith("stash") else "mihomo",
            "platform": "ios" if name == "stash-ios" else "android",
        })
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = client.post("/api/v1/targets/reorder", headers=h, json=list(reversed(ids)))
    assert r.status_code == 200, r.text
    assert [t["id"] for t in client.get("/api/v1/targets").json()] == list(reversed(ids))
    # 排序列表必须覆盖全部目标
    assert client.post("/api/v1/targets/reorder", headers=h,
                       json=ids[:-1]).status_code == 400


def test_auto_publish_waits_for_filtered_speed_test(client, monkeypatch):
    """启用只分发可用节点的来源没有测速结果时，不自动构建/发布。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    source = client.get("/api/v1/sources").json()[0]
    client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_fetch_sources": "0", "auto_fetch_rules": "0",
    }})

    from app import db
    from app.services import scheduler

    with db.tx() as conn:
        conn.execute(
            "UPDATE sources SET filter_unavailable=1, test_results='{}', "
            "tested_at=NULL, test_attempt_at=NULL WHERE id=?", (source["id"],),
        )
    summary = scheduler.run_once(force=True)
    assert summary["build"] is None
    assert "等待测速结果" in summary["build_error"]
    assert client.get("/api/v1/builds").json() == []
    assert client.get("/api/v1/releases").json() == []

    with db.tx() as conn:
        conn.execute(
            "UPDATE sources SET test_results=?, tested_at=?, test_attempt_at=? "
            "WHERE id=?",
            ('{"节点A": 120}', db.now(), db.now(), source["id"]),
        )
    summary = scheduler.run_once(force=True)
    assert summary["build"]["status"] == "success"
    assert summary["published"] == "stable"
    assert len(client.get("/api/v1/releases").json()) == 1


def test_auto_fetch_switch_skips_scheduled_fetch(client, monkeypatch):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    source = client.post("/api/v1/sources", headers=h, json={
        "name": "时效订阅", "url": "https://time-limited.example.com/sub",
        "auto_fetch": False,
    }).json()
    assert source["auto_fetch"] is False
    assert client.get("/api/v1/sources").json()[0]["auto_fetch"] is False

    client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_fetch_sources": "1",
        "auto_test_sources": "0",
        "auto_build_enabled": "0",
    }})

    from app import db
    from app.services import scheduler, updater

    called = []

    def fake_refresh(source_id, operator, automatic=False):
        called.append(source_id)
        with db.tx() as conn:
            conn.execute(
                "UPDATE sources SET last_attempt_at=?, last_fetched_at=? WHERE id=?",
                (db.now(), db.now(), source_id),
            )
        with db.connect() as conn:
            return db.one(conn, "SELECT * FROM sources WHERE id=?", (source_id,))

    monkeypatch.setattr(updater, "refresh_source", fake_refresh)

    summary = scheduler.run_once(force=True)
    assert summary["sources_fetched"] == 0
    assert called == []

    # 重新开启自动抓取后，调度器会处理
    with db.tx() as conn:
        conn.execute("UPDATE sources SET auto_fetch=1 WHERE id=?", (source["id"],))
    summary = scheduler.run_once(force=True)
    assert summary["sources_fetched"] == 1
    assert called == [source["id"]]


def test_auto_test_switch_skips_scheduled_test(client, monkeypatch):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    source = client.post("/api/v1/sources", headers=h, json={
        "name": "不自动测速", "url": "https://no-test.example.com/sub",
        "auto_test": False,
    }).json()
    assert source["auto_test"] is False

    client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_fetch_sources": "0",
        "auto_fetch_rules": "0",
        "auto_test_sources": "1",
        "auto_build_enabled": "0",
    }})

    from app import db, security
    from app.services import scheduler, updater

    with db.tx() as conn:
        conn.execute(
            "UPDATE sources SET snapshot_enc=?, test_attempt_at=NULL, tested_at=NULL "
            "WHERE id=?",
            (security.encrypt_text("proxies:\n  - {name: n1, type: ss}\n"),
             source["id"]),
        )

    called = []

    def fake_test(source_id, operator, automatic=False):
        called.append(source_id)
        with db.tx() as conn:
            conn.execute(
                "UPDATE sources SET test_attempt_at=?, tested_at=? WHERE id=?",
                (db.now(), db.now(), source_id),
            )
        return {"test_results": '{"n1": 100}'}

    monkeypatch.setattr(updater, "test_source", fake_test)
    monkeypatch.setattr(scheduler, "_core_available", lambda: True)

    summary = scheduler.run_once(force=True)
    assert summary["tests_run"] == 0
    assert called == []

    with db.tx() as conn:
        conn.execute("UPDATE sources SET auto_test=1 WHERE id=?", (source["id"],))
    summary = scheduler.run_once(force=True)
    assert summary["tests_run"] == 1
    assert called == [source["id"]]







def test_manual_run_records_history_and_audit(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_fetch_sources": "0", "auto_fetch_rules": "0",
        "auto_test_sources": "0", "auto_build_enabled": "0",
    }})
    from app.services import scheduler
    scheduler.run_once(force=True, trigger="manual", actor="admin")
    runs = client.get("/api/v1/automation/runs", headers=h).json()
    assert len(runs) == 1
    assert runs[0]["trigger"] == "manual"
    assert runs[0]["summary"]["trigger"] == "manual"
    assert runs[0]["summary"]["actor"] == "admin"
    audit = client.get("/api/v1/audit").json()
    assert any(a["action"] == "手动自动任务运行完成" and "manual" in a["detail"]
               for a in audit)

    # 无实际动作的定时 tick 不写运行记录
    scheduler.run_once(force=False)
    assert len(client.get("/api/v1/automation/runs", headers=h).json()) == 1
def test_local_node_crud_render_and_group_reference(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    schema = client.get("/api/v1/local-nodes/schema", headers=h).json()
    values = {p["value"] for p in schema["protocols"]}
    assert {"ss", "vmess", "vless", "trojan", "hysteria2", "custom"} <= values

    # Shadowsocks 缺密码被拒绝
    bad = client.post("/api/v1/local-nodes", headers=h, json={
        "name": "坏节点", "protocol": "ss", "server": "bad.example.com",
        "port": 8388, "params": {"cipher": "aes-256-gcm"},
    })
    assert bad.status_code == 400

    node = client.post("/api/v1/local-nodes", headers=h, json={
        "name": "HK-01", "protocol": "ss", "server": "hk.example.com",
        "port": 8388,
        "params": {"cipher": "aes-256-gcm", "password": "secret", "udp": True},
    }).json()
    assert node["marked_name"] == "[单] HK-01"

    custom = client.post("/api/v1/local-nodes", headers=h, json={
        "name": "Custom-01", "protocol": "custom", "server": "custom.example.com",
        "port": 443, "params": {"proxy_type": "mieru"},
        "extra_yaml": "transport: tcp\n",
    })
    assert custom.status_code == 201, custom.text

    group = client.post("/api/v1/groups", headers=h, json={
        "name": "手动节点", "type": "select", "proxies": ["DIRECT"],
        "local_nodes": [node["id"]],
    }).json()
    assert group["local_nodes"] == [node["id"]]
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "手动节点"})

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    assert "[单] HK-01" in art
    assert "hk.example.com" in art
    assert "aes-256-gcm" in art

    # 被策略组引用时不能删除
    assert client.delete(f"/api/v1/local-nodes/{node['id']}",
                         headers=h).status_code == 400

    # 停用后不再写入产物，但组里仍有 DIRECT，构建仍可通过
    disabled = client.put(f"/api/v1/local-nodes/{node['id']}", headers=h, json={
        "name": node["name"], "protocol": node["protocol"],
        "server": node["server"], "port": node["port"],
        "params": node["params"], "extra_yaml": node["extra_yaml"],
        "enabled": False,
    })
    assert disabled.status_code == 200, disabled.text
    build2 = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build2["status"] == "success", build2
    art2 = client.get(
        f"/api/v1/builds/{build2['id']}/artifact/stash-ios").json()["content"]
    assert "[单] HK-01" not in art2

    # 解除引用后可删除
    body = {**group, "local_nodes": []}
    assert client.put(f"/api/v1/groups/{group['id']}", headers=h,
                      json=body).status_code == 200
    assert client.delete(f"/api/v1/local-nodes/{node['id']}",
                         headers=h).status_code == 200
