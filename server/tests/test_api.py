"""认证、策略维护、构建发布与分发的端到端用例。"""
import httpx
import urllib.parse
import pytest

from conftest import auth_headers, setup_admin
from app import db


def test_scope_all_sentinel_means_everything(client):
    """「包含所有」哨兵：节点来源、引擎平台、设备都按"全部"处理。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    # 第二个来源：用来验证"包含所有"能带上后来新增的来源
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "后加机场", "url": "https://later.example.com/sub?token=xyz789"})
    assert r.status_code == 201, r.text

    # 选满全部来源 → 归一为"包含所有"
    r = client.post("/api/v1/groups", headers=h, json={
        "name": "全选组", "type": "url-test",
        "use_sources": ["测试机场", "后加机场"], "filter": "x"})
    assert r.status_code == 201, r.text
    assert r.json()["use_sources"] == ["*"]

    # 不传适用范围 = 默认包含所有
    r = client.post("/api/v1/groups", headers=h, json={
        "name": "默认组", "type": "select", "proxies": ["DIRECT"]})
    assert r.status_code == 201, r.text
    assert r.json()["targets"] == ["*"]
    assert r.json()["devices"] == ["*"]

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build["results"]
    bid = build["id"]
    artifact = client.get(
        f"/api/v1/builds/{bid}/artifact/stash-ios", headers=h).json()["content"]
    # 「包含所有」的组在产物里带上全部来源（含后来新增的）
    assert "测试机场" in artifact
    assert "后加机场" in artifact
    assert "全选组" in artifact

    # 显式传空数组 = 不适用任何平台/设备
    r = client.post("/api/v1/groups", headers=h, json={
        "name": "空范围组", "type": "select", "proxies": ["DIRECT"],
        "targets": [], "devices": []})
    assert r.status_code == 201, r.text
    assert r.json()["targets"] == []
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    artifact = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios", headers=h).json()["content"]
    assert "空范围组" not in artifact


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


def publish_to_prod(client, h, bid, reason=""):
    """把构建发布到生产环境。

    生命周期状态机要求"先测试、后生产"：BUILT 不能直接上生产，
    所以这里固定走 publish-to-test → publish-to-prod 两步。
    """
    r = client.post(f"/api/v1/builds/{bid}/publish-to-test", headers=h,
                    json={"reason": reason})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/builds/{bid}/publish-to-prod", headers=h,
                    json={"reason": reason})
    assert r.status_code == 200, r.text
    return r


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
    # 生命周期状态是「已构建」，校验结果单独看 verify_status
    assert build["status"] == "BUILT"
    assert build["verify_status"] == "success"
    assert set(build["results"]) == {"stash-ios", "mihomo-android"}
    for result in build["results"].values():
        assert result["ok"] and result["sha256"] and result["size"] > 0

    bid = build["id"]
    # 产物：两个引擎都带 dns 段（引擎默认配置里已含官方 DNS 基线）；
    # provider 使用 {FEED} 占位
    art = client.get(f"/api/v1/builds/{bid}/artifact/stash-ios").json()["content"]
    # 来源名会进入 URL 路径，做百分号转义
    assert "{FEED}/res/provider/" + urllib.parse.quote("测试机场") in art
    assert "fake-ip-range: 198.18.0.1/16" in art   # 引擎默认配置里的 DNS 基线
    assert "enhanced-mode" not in art              # enhanced-mode 是 Mihomo 专有键
    art_m = client.get(f"/api/v1/builds/{bid}/artifact/mihomo-android").json()["content"]
    assert "enhanced-mode: fake-ip" in art_m
    assert "header:" in art_m and "headers:" not in art_m

    # 未发布时设备拉取返回 503
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "测试手机", "platform": "ios", "target_id": 1, "env": "production",
    })
    assert dev.status_code == 201, dev.text
    dev = dev.json()
    assert dev["env"] == "production"
    token = dev["token"]
    assert token.startswith("mp_")
    url_path = dev["subscription_url"].split("://", 1)[1]
    feed_path = "/" + url_path.split("/", 1)[1]
    assert client.get(feed_path).status_code == 503

    # 发布到生产后拉取成功（状态机：先过测试环境）
    publish_to_prod(client, h, bid, reason="验收通过")
    state = client.get("/api/v1/release-state").json()["production"]
    assert state["id"] == bid
    assert state["status"] == "PRODUCTION"
    assert state["published_by"] == "admin"
    assert state["publish_reason"] == "验收通过"
    assert state["published_at"]
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

    # 回滚：先造一个新版本顶替当前生产版本，旧版本下线后再回滚
    second = client.post("/api/v1/builds", headers=h, json={"note": "第二个"}).json()
    publish_to_prod(client, h, second["id"], reason="新版本")
    r = client.post(f"/api/v1/builds/{bid}/rollback-to-prod", headers=h,
                    json={"reason": "演练"})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/release-state").json()["production"]["id"] == bid
    releases = client.get("/api/v1/releases").json()
    assert releases[0]["action"] == "rollback"
    assert releases[0]["env"] == "production"
    assert [x["action"] for x in releases] == [
        "rollback", "publish", "publish", "publish", "publish"]

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
    assert build["verify_status"] == "failed"
    assert build["status"] == "BUILT"
    errors = build["results"]["stash-ios"]["errors"]
    assert any("兜底" in e for e in errors)
    assert any("为空" in e for e in errors)
    # 失败构建不能发布
    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                    json={"reason": "试试"})
    assert r.status_code == 400
    assert "未通过校验" in r.json()["detail"]


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
    assert build["verify_status"] == "failed"
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
    assert build["verify_status"] == "success", build["results"]
    publish_to_prod(client, h, build["id"])
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
    # 顶部发布状态：两个环境各一个生效版本（此处都还没有）
    assert data["release_state"] == {"production": None, "testing": None}
    assert "channels" not in data
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
    assert build["verify_status"] == "success", build

    bid = build["id"]
    art_s = client.get(f"/api/v1/builds/{bid}/artifact/stash-ios").json()["content"]
    art_m = client.get(f"/api/v1/builds/{bid}/artifact/mihomo-android").json()["content"]
    # Stash 官方支持 load-balance 的 strategy，但只认 consistent-hashing / round-robin
    assert "strategy: sticky-sessions" in art_m
    assert "strategy: consistent-hashing" in art_s
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
    assert build["verify_status"] == "success", build
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

    # 被引用时重命名默认拒绝（409 + 引用明细），force=1 时同步更新引用
    r = client.put(f"/api/v1/sources/{a['id']}", headers=h, json={
        "name": "A机场改名", "enabled": True, "interval": 3600})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "source_in_use"
    assert detail["rename_to"] == "A机场改名"
    r = client.put(f"/api/v1/sources/{a['id']}?force=1", headers=h, json={
        "name": "A机场改名", "enabled": True, "interval": 3600})
    assert r.status_code == 200, r.text
    groups = client.get("/api/v1/groups", headers=h).json()
    assert groups[0]["use_sources"] == ["A机场改名"]
    # 改回原名，后面用例还用旧名字
    assert client.put(f"/api/v1/sources/{a['id']}?force=1", headers=h, json={
        "name": "A机场", "enabled": True, "interval": 3600}).status_code == 200

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
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "rule_provider_in_use"
    assert detail["rename_to"] == "rules-a-renamed"
    # force=1 时把引用它的 RULE-SET 规则一起改名
    r = client.put(f"/api/v1/rule-providers/{a['id']}?force=1", headers=h, json={
        "name": "rules-a-renamed", "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - a.example.com\n"})
    assert r.status_code == 200, r.text
    rules = client.get("/api/v1/rules", headers=h).json()
    assert any(x["value"] == "rules-a-renamed" for x in rules)
    # 改回原名，后面用例继续用旧名字
    assert client.put(f"/api/v1/rule-providers/{a['id']}?force=1", headers=h, json={
        "name": "rules-a", "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - a.example.com\n"}).status_code == 200

    r = client.post("/api/v1/rule-providers/batch/delete", headers=h,
                    json={"ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] == [b["id"]]
    assert [x["id"] for x in data["blocked"]] == [a["id"]]
    assert "分流规则" in data["blocked"][0]["reason"]

    # 单删同样被停用规则引用阻止：409 + 引用明细（前端据此弹二次确认）
    r = client.delete(f"/api/v1/rule-providers/{a['id']}", headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "rule_provider_in_use"
    assert detail["references"][0]["id"] == rule["id"]
    # 强制删除会连带删掉引用它的分流规则
    r = client.delete(f"/api/v1/rule-providers/{a['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()["deleted_rules"]] == [rule["id"]]
    assert client.get(f"/api/v1/rules/{rule['id']}", headers=h).status_code == 404


def test_build_delete_and_release_state_reference(client):
    """构建删除：只有从未发布过的构建可物理删除，其余状态只能归档。

    旧模型里"通道指针"是硬引用，指针移走后旧构建就能删；
    新模型改成单一生命周期状态机，发布过的构建一律不可删——
    它们的发布历史要一直留着，界面才能回溯"谁在什么时候上了哪个版本"。
    """
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    first = client.post("/api/v1/builds", headers=h, json={"note": "一"}).json()
    assert first["verify_status"] == "success"
    assert first["status"] == "BUILT"
    publish_to_prod(client, h, first["id"])

    # 生效中的构建不能删除
    r = client.delete(f"/api/v1/builds/{first['id']}", headers=h)
    assert r.status_code == 400
    assert "只有未发布过的构建可以手动删除" in r.json()["detail"]

    second = client.post("/api/v1/builds", headers=h, json={"note": "二"}).json()
    assert second["verify_status"] == "success"
    publish_to_prod(client, h, second["id"])
    # 被替换的版本变成"已下线"，同样不能删（归档，不是垃圾）
    r = client.delete(f"/api/v1/builds/{first['id']}", headers=h)
    assert r.status_code == 400
    assert "只有未发布过的构建可以手动删除" in r.json()["detail"]

    # 从未发布过的构建可以删；产物目录一并清理
    third = client.post("/api/v1/builds", headers=h, json={"note": "三"}).json()
    r = client.delete(f"/api/v1/builds/{third['id']}", headers=h)
    assert r.status_code == 200, r.text
    # 从未发布过 → 没有发布历史需要清理
    assert r.json()["deleted_releases"] == 0
    assert client.get(f"/api/v1/builds/{third['id']}").status_code == 404
    assert client.get(f"/api/v1/builds/{third['id']}/artifact/stash-ios")\
        .status_code == 404

    fourth = client.post("/api/v1/builds", headers=h, json={"note": "四"}).json()
    r = client.post("/api/v1/builds/batch/delete", headers=h,
                    json={"ids": [second["id"], fourth["id"]]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] == [fourth["id"]]
    assert data["blocked"][0]["id"] == second["id"]
    assert "只有未发布过的构建可以手动删除" in data["blocked"][0]["reason"]


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
    audit = client.get("/api/v1/audit").json()["items"]
    assert any("刷新节点来源失败" in a["action"] for a in audit)


def test_release_history_retention(client):
    """发布历史只保留最近 20 条。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    # 每次发布都会写一条历史；状态机不允许把同一个构建重复发布到同一环境，
    # 所以用多个构建凑够 22 条（每个构建"先测试、后生产"两条）。
    for i in range(11):
        build = client.post("/api/v1/builds", headers=h,
                            json={"note": f"版本{i}"}).json()
        publish_to_prod(client, h, build["id"], reason=f"第{i}版")
    releases = client.get("/api/v1/releases").json()
    assert len(releases) == 20
    # 动作是 publish / rollback / offline，不再是 promote
    assert {r["action"] for r in releases} == {"publish"}
    assert {r["env"] for r in releases} == {"testing", "production"}
    # 手动发布不进入“自动发布”页
    assert client.get("/api/v1/releases?auto_only=true").json() == []
    from app import db
    with db.connect() as conn:
        count = db.one(conn, "SELECT COUNT(*) AS c FROM releases")["c"]
    assert count == 20


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
    # 模拟核心校验通过：没有核心时 Mihomo 目标只能静态校验，
    # 自动发布到生产环境会被拦下。
    from app.services import tester
    monkeypatch.setattr(tester, "validate_config", lambda text, *a, **k: (True, ""))

    summary = scheduler.run_once(force=True)
    assert calls.count("fetch") == 1
    assert calls.count("test") == 1
    assert summary["sources_fetched"] == 1
    assert summary["tests_run"] == 1
    assert summary["tests_ok"] == 1 and summary["tests_failed"] == 1
    assert summary["build"]["status"] == "success"
    # 发布目标现在是环境名，不是通道名
    assert summary["published"] == "production"

    state = client.get("/api/v1/release-state").json()
    assert state["production"]["id"] == summary["build"]["id"]
    assert state["production"]["status"] == "PRODUCTION"
    assert state["production"]["published_by"] == "系统"
    assert state["production"]["publish_reason"] == "自动构建发布"
    # 自动发布到生产时是"先置测试、再置生产"两步同事务，
    # 因此发布完成后测试环境空置，直到下一次发布。
    assert state["testing"] is None
    releases = client.get("/api/v1/releases").json()
    assert releases[0]["operator"] == "系统"
    assert releases[0]["reason"] == "自动构建发布"
    assert releases[0]["action"] == "publish"
    assert releases[0]["env"] == "production"
    auto_releases = client.get("/api/v1/releases?auto_only=true").json()
    # 自动发布是"同一事务内先置测试再置生产"的一步操作，发布历史只记一条
    assert len(auto_releases) == 1
    assert auto_releases[0]["env"] == "production"
    assert all(r["build_id"] == summary["build"]["id"] for r in auto_releases)

    status = client.get("/api/v1/automation/status", headers=h).json()
    assert status["last_result"]["published"] == "production"

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
    assert status["settings"]["auto_build_interval_hours"] == "1"

    # 非法开关 / 发布环境 / 间隔被拒绝
    for values in (
        {"auto_publish_enabled": "yes"},
        {"auto_build_interval_hours": "0"},
        {"auto_publish_env": "beta"},
    ):
        assert client.put("/api/v1/settings", headers=h,
                          json={"values": values}).status_code == 400

    r = client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_build_interval_hours": "6",
        "auto_publish_env": "testing",
        "auto_publish_enabled": "0",
    }})
    assert r.status_code == 200
    status = client.get("/api/v1/automation/status", headers=h).json()
    assert status["settings"]["auto_build_interval_hours"] == "6"
    assert status["settings"]["auto_publish_env"] == "testing"
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
    for name, engine, platform in (("stash-ios", "stash", "ios"),
                                   ("mihomo-android", "mihomo", "android"),
                                   ("stash-macos", "stash", "macos")):
        r = client.post("/api/v1/targets", headers=h, json={
            "name": name, "engine": engine, "platform": platform,
        })
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = client.post("/api/v1/targets/reorder", headers=h, json=list(reversed(ids)))
    assert r.status_code == 200, r.text
    assert [t["id"] for t in client.get("/api/v1/targets").json()] == list(reversed(ids))
    # 列表已分页：只提交部分 id 时，按这些 id 之间的新顺序重排，其余不动
    r = client.post("/api/v1/targets/reorder", headers=h, json=ids[:-1])
    assert r.status_code == 200, r.text
    # 重复 id 与不存在的 id 都要拒绝
    assert client.post("/api/v1/targets/reorder", headers=h,
                       json=[ids[0], ids[0]]).status_code == 400
    assert client.post("/api/v1/targets/reorder", headers=h,
                       json=[999999]).status_code == 400


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
    assert summary["published"] == "production"
    # 自动发布到生产是"同一事务内先置测试再置生产"的一步操作，
    # 发布历史只记最终那一条（否则 10 条上限一轮就吃掉两条）
    history = client.get("/api/v1/releases").json()
    assert len(history) == 1
    assert history[0]["env"] == "production"
    assert history[0]["action"] == "publish"
    # 自动发布后该构建就是生产版本
    state = client.get("/api/v1/release-state").json()
    assert state["production"]["id"] == summary["build"]["id"]


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
    audit = client.get("/api/v1/audit").json()["items"]
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
    # 节点类型默认「本地」，产物里的标识是「名称 (类型)」
    assert node["node_type"] == "本地"
    assert node["display_name"] == "HK-01 (本地)"

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
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    assert "HK-01 (本地)" in art
    assert "hk.example.com" in art
    assert "aes-256-gcm" in art

    # 被策略组引用时默认不删：409 + 引用明细（前端据此弹二次确认）
    r = client.delete(f"/api/v1/local-nodes/{node['id']}", headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "local_node_in_use"
    assert detail["references"][0]["name"] == group["name"]
    # 强制删除会自动从策略组里摘掉这个节点
    r = client.delete(f"/api/v1/local-nodes/{node['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["detached_groups"] == [group["name"]]
    groups = client.get("/api/v1/groups", headers=h).json()
    assert next(g for g in groups if g["id"] == group["id"])["local_nodes"] == []
    # 节点已删除
    assert client.delete(f"/api/v1/local-nodes/{node['id']}",
                         headers=h).status_code == 404
    # 后续用例继续用节点重建一个同名的，避免影响其它断言
    node = client.post("/api/v1/local-nodes", headers=h, json={
        "name": node["name"], "protocol": node["protocol"],
        "server": node["server"], "port": node["port"],
        "params": node["params"], "extra_yaml": node["extra_yaml"],
    }).json()
    client.put(f"/api/v1/groups/{group['id']}", headers=h,
               json={**group, "local_nodes": [node["id"]]})

    # 停用后不再写入产物，但组里仍有 DIRECT，构建仍可通过
    disabled = client.put(f"/api/v1/local-nodes/{node['id']}", headers=h, json={
        "name": node["name"], "protocol": node["protocol"],
        "server": node["server"], "port": node["port"],
        "params": node["params"], "extra_yaml": node["extra_yaml"],
        "enabled": False,
    })
    assert disabled.status_code == 200, disabled.text
    build2 = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build2["verify_status"] == "success", build2
    art2 = client.get(
        f"/api/v1/builds/{build2['id']}/artifact/stash-ios").json()["content"]
    assert "HK-01 (本地)" not in art2

    # 解除引用后可删除
    body = {**group, "local_nodes": []}
    assert client.put(f"/api/v1/groups/{group['id']}", headers=h,
                      json=body).status_code == 200
    assert client.delete(f"/api/v1/local-nodes/{node['id']}",
                         headers=h).status_code == 200


# ---- 基础配置、引擎差异、链路修复 ----

import json  # noqa: E402
import yaml  # noqa: E402


def test_base_config_defaults_and_crud(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)

    stash = client.get("/api/v1/base-config?engine=stash&platform=ios", headers=h).json()
    assert stash["is_default"] is True
    assert stash["effective"]["mode"] == "rule"
    # Stash 官方精简：不含端口与 profile
    assert "mixed-port" not in stash["effective"] and "profile" not in stash["effective"]
    mihomo = client.get("/api/v1/base-config?engine=mihomo&platform=android", headers=h).json()
    assert mihomo["effective"]["mixed-port"] == 7890
    assert mihomo["effective"]["profile"]["store-selected"] is True

    # 只改一个键：服务端只把这个键的差异存进本层，其余继续跟随上层
    saved = client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h, json={
        "content": "mode: global\nlog-level: warning\nipv6: false\n"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["effective"]["mode"] == "global"
    assert saved.json()["is_default"] is False
    assert saved.json()["overlay"] == {"mode": "global"}
    # 来源标注：被本层改写的键来源是「引擎平台配置」，其余仍是「引擎默认配置」
    assert saved.json()["sources"]["mode"] == "引擎平台配置"
    assert saved.json()["sources"]["log-level"] == "引擎默认配置"

    # 乐观锁：版本不一致时拒绝
    stale = client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h, json={
        "content": "mode: rule\n", "updated_at": "2000-01-01T00:00:00+08:00"})
    assert stale.status_code == 409

    reset = client.post("/api/v1/base-config/reset?engine=stash&platform=ios", headers=h)
    assert reset.status_code == 200 and reset.json()["is_default"] is True

    schema = client.get("/api/v1/base-config/schema?engine=stash", headers=h).json()
    keys = [f["key"] for f in schema["fields"]]
    assert "mode" in keys and "dns.nameserver" in keys
    # Stash 不暴露 Mihomo 专有的 profile 开关
    assert "profile.store-selected" not in keys
    assert schema["presets"]


def test_base_config_validation_and_protected_keys(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    for content in ("rules:\n- MATCH,DIRECT\n", "proxy-groups:\n- name: x\n"):
        r = client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h,
                       json={"content": content})
        assert r.status_code == 400, content
    bad_inputs = [
        "[]\n",                       # 不是映射
        "mode: [unclosed\n",          # YAML 语法错误
        "",                           # 空
        "mode: xxx\n",                # 取值非法
        "log-level: verbose\n",       # 取值非法
        "mixed-port: 70000\n",        # 端口越界
        "mixed-port: 'abc'\n",        # 端口类型错误
        'allow-lan: "yes"\n',         # 布尔类型错误
    ]
    for content in bad_inputs:
        r = client.put("/api/v1/base-config?engine=mihomo", headers=h,
                       json={"content": content})
        assert r.status_code == 400, content


def test_base_config_render_preview_and_policy_sha(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    content = "mode: rule\nlog-level: info\nipv6: false\nsocks-port: 7892\n"
    assert client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h,
                      json={"content": content}).status_code == 200

    before = len(client.get("/api/v1/builds", headers=h).json())
    preview = client.post("/api/v1/base-config/preview", headers=h,
                           json={"engine": "stash", "target": "stash-ios"})
    assert preview.status_code == 200, preview.text
    text = preview.json()["content"]
    assert "log-level: info" in text and "socks-port: 7892" in text
    assert "{FEED}" in text and "{FEED_HOST}" in text
    # 预览不产生构建
    assert len(client.get("/api/v1/builds", headers=h).json()) == before

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    art = client.get(f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    assert art == text
    sha1 = build["policy_sha"]

    client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h,
               json={"content": "mode: rule\nlog-level: debug\n"})
    build2 = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build2["policy_sha"] != sha1


def test_base_config_apply_builds_and_publishes(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    r = client.post("/api/v1/base-config/apply", headers=h, json={
        "engine": "stash", "platform": "ios",
        "content": "mode: rule\nlog-level: info\n",
        "env": "production", "note": "基础配置发布"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success"
    assert r.json()["env"] == "production"
    state = client.get("/api/v1/release-state", headers=h).json()
    assert state["production"]["id"] == r.json()["build_id"]
    art = client.get(
        f"/api/v1/builds/{r.json()['build_id']}/artifact/stash-ios").json()["content"]
    assert "log-level: info" in art


def test_artifact_keys_follow_official_docs(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    node = client.post("/api/v1/local-nodes", headers=h, json={
        "name": "H1", "protocol": "hysteria2", "server": "h.example.com",
        "port": 443,
        "params": {"password": "pw", "sni": "h.example.com", "down": 1000},
    }).json()
    client.post("/api/v1/groups", headers=h, json={
        "name": "单组", "type": "select", "proxies": ["DIRECT"],
        "local_nodes": [node["id"]]})
    client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "单组"})

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art_s = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    art_m = client.get(
        f"/api/v1/builds/{build['id']}/artifact/mihomo-android").json()["content"]

    # 远程代理集：Stash 用 benchmark-*，Mihomo 用 health-check
    assert "benchmark-url:" in art_s and "health-check:" not in art_s
    assert "health-check:" in art_m and "benchmark-url:" not in art_m
    assert "headers:" in art_s and "header:" not in art_s
    assert "header:" in art_m

    # 本地节点 Hysteria2：Stash 用 auth / down-speed，Mihomo 用 password / down
    assert "auth: pw" in art_s and "password: pw" not in art_s
    assert "down-speed: 1000" in art_s
    assert "password: pw" in art_m and "auth: pw" not in art_m
    assert "down: 1000 Mbps" in art_m

    # 策略组：Stash 无 url/timeout，Mihomo 有
    groups_s = yaml.safe_load(art_s)["proxy-groups"]
    groups_m = yaml.safe_load(art_m)["proxy-groups"]
    g_s = next(g for g in groups_s if g["name"] == "地区自动")
    g_m = next(g for g in groups_m if g["name"] == "地区自动")
    assert "url" not in g_s and "timeout" not in g_s
    assert g_m["url"].startswith("http") and "timeout" in g_m
    # 顶层键：Stash 官方精简，Mihomo 保留端口与 profile
    assert "mixed-port" not in yaml.safe_load(art_s)
    assert yaml.safe_load(art_m)["mixed-port"] == 7890


def test_target_extra_yaml_rejects_structural_keys(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "bad-target", "engine": "stash", "platform": "tvos",
        "extra_yaml": "rules:\n- MATCH,DIRECT\n"})
    assert r.status_code == 400
    ok = client.post("/api/v1/targets", headers=h, json={
        "name": "ok-target", "engine": "stash", "platform": "macos",
        "extra_yaml": "log-level: info\n"})
    assert ok.status_code == 201, ok.text


def test_build_snapshot_is_encrypted(client):
    from app import db
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    with db.connect() as conn:
        row = db.one(conn, "SELECT snapshot FROM builds WHERE id=?", (build["id"],))
    assert row["snapshot"].startswith("enc:v1:")
    detail = client.get(f"/api/v1/builds/{build['id']}", headers=h).json()
    assert detail["snapshot"]["groups"]
    assert "base" in detail["snapshot"]


def test_provider_etag_follows_test_results(client):
    from app import db, security
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "设备A", "platform": "ios", "target_id": 1,
        "env": "production"}).json()
    token = dev["token"]
    with db.connect() as conn:
        source = db.one(conn, "SELECT * FROM sources WHERE name='测试机场'")
    snapshot = ("proxies:\n- name: n1\n  type: ss\n  server: a.example.com\n"
                "  port: 443\n  cipher: aes-256-gcm\n  password: p\n")
    with db.tx() as conn:
        conn.execute(
            "UPDATE sources SET snapshot_enc=?, sha256=?, filter_unavailable=1, "
            "test_results=? WHERE id=?",
            (security.encrypt_text(snapshot), security.sha256_text(snapshot),
             json.dumps({"n1": 120}), source["id"]))
    first = client.get(f"/feed/{token}/res/provider/测试机场")
    assert first.status_code == 200
    etag1 = first.headers["etag"]
    with db.tx() as conn:
        conn.execute("UPDATE sources SET test_results=? WHERE id=?",
                     (json.dumps({"n1": -1}), source["id"]))
    second = client.get(f"/feed/{token}/res/provider/测试机场")
    assert second.headers["etag"] != etag1
    assert "n1" not in second.text
    # 带旧 ETag 再取应返回 200 而不是 304
    third = client.get(f"/feed/{token}/res/provider/测试机场",
                       headers={"If-None-Match": etag1})
    assert third.status_code == 200


def test_fetch_failure_persists_state_and_backs_off(client, monkeypatch):
    import httpx
    from app import db
    from app.services import fetcher, scheduler
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    source = client.post("/api/v1/sources", headers=h, json={
        "name": "坏来源", "url": "https://example.com:notaport/sub"}).json()

    def boom(*args, **kwargs):
        raise httpx.InvalidURL("Invalid port")

    monkeypatch.setattr(fetcher, "fetch", boom)
    r = client.post(f"/api/v1/sources/{source['id']}/refresh", headers=h)
    assert r.status_code == 502
    with db.connect() as conn:
        row = db.one(conn, "SELECT * FROM sources WHERE id=?", (source["id"],))
    assert row["last_status"] == "failed"
    assert row["fail_count"] == 1
    assert row["last_attempt_at"], "失败后必须记录尝试时间，避免每个 tick 重试"
    summary = scheduler.run_once(force=False)
    assert summary["sources_failed"] == 0


def test_scheduler_records_gate_reason_once(client):
    from app.services import scheduler
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/sources", headers=h, json={
        "name": "门禁机场", "url": "https://airport.example.com/sub",
        "filter_unavailable": True, "auto_fetch": False})
    client.post("/api/v1/groups", headers=h, json={
        "name": "门禁组", "type": "select", "proxies": ["DIRECT"]})
    client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "门禁组"})
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})

    summary = scheduler.run_once(force=True)
    assert "等待测速结果" in (summary.get("build_error") or "")
    runs = client.get("/api/v1/automation/runs", headers=h).json()
    assert any("等待测速结果" in (r["summary"].get("build_error") or "")
               for r in runs)
    count = len(runs)
    scheduler.run_once(force=True)
    assert len(client.get("/api/v1/automation/runs", headers=h).json()) == count


def test_client_interval_reaches_artifact(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    with_source = client.get("/api/v1/sources", headers=h).json()[0]
    updated = client.put(f"/api/v1/sources/{with_source['id']}", headers=h, json={
        "name": with_source["name"], "client_interval": 3600}).json()
    assert updated["client_interval"] == 3600
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    data = yaml.safe_load(art)
    assert data["proxy-providers"]["测试机场"]["interval"] == 3600


def test_settings_intervals_default_to_one_hour(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    settings = client.get("/api/v1/settings", headers=h).json()
    assert settings["profile_update_interval"] == "1"
    assert settings["auto_build_interval_hours"] == "1"


def test_production_fixes_script(client):
    """一次性生产修正脚本：百度网盘分流、规则来源行为、客户端更新间隔。"""
    import importlib.util
    import os
    from app import db, security

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 造出与线上一致的结构：cn 规则、classical 规则来源、Hysteria2 本地节点
    client.post("/api/v1/rule-providers", headers=h, json={
        "name": "Google", "kind": "inline", "behavior": "classical",
        "inline_content": "payload:\n  - example.com\n"})
    client.post("/api/v1/rule-providers", headers=h, json={
        "name": "cn", "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - example.cn\n"})
    client.post("/api/v1/sources", headers=h, json={
        "name": "机场", "url": "https://airport.example.com/sub"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "节点选择", "type": "select", "proxies": ["DIRECT"]})
    client.post("/api/v1/rules", headers=h, json={
        "type": "RULE-SET", "value": "cn", "target": "节点选择"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "节点选择"})
    client.post("/api/v1/local-nodes", headers=h, json={
        "name": "US 01", "protocol": "hysteria2", "server": "lax.example.com",
        "port": 443,
        "params": {"password": "pw", "sni": "lax.example.com",
                   "down": "1000 Mbps"}})

    repo_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(repo_root, "scripts", "apply_production_fixes.py")
    spec = importlib.util.spec_from_file_location("apply_production_fixes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()

    with db.connect() as conn:
        group = db.one(conn, "SELECT * FROM proxy_groups WHERE name='百度网盘'")
        assert group is not None
        assert json.loads(group["proxies"]) == ["节点选择", "DIRECT"]
        rules = db.all_(conn, "SELECT * FROM rules ORDER BY sort, id")
        baidu = [r for r in rules if r["value"] == "pan.baidu.com"]
        assert baidu and baidu[0]["target"] == "百度网盘"
        cn = next(r for r in rules if r["value"] == "cn")
        # 百度规则必须排在 cn 之前
        assert baidu[0]["sort"] < cn["sort"]
        provider = db.one(conn, "SELECT * FROM rule_providers WHERE name='Google'")
        assert provider["behavior"] == "domain"
        source = db.one(conn, "SELECT * FROM sources WHERE name='机场'")
        assert source["client_interval"] == 3600
        node = db.one(conn, "SELECT * FROM local_nodes WHERE name='US 01'")
        params = json.loads(security.decrypt_text(node["params_enc"]))
        assert params["down"] == 1000

    # 幂等：再执行一次不产生重复规则
    spec.loader.exec_module(module)
    module.main()
    with db.connect() as conn:
        count = db.one(conn, "SELECT COUNT(*) AS c FROM rules "
                              "WHERE value='pan.baidu.com'")["c"]
        assert count == 1


def test_build_does_not_hold_write_lock_during_core_check(client, monkeypatch):
    """构建期间不得长时间持有写锁：否则设备拉取配置会 database is locked。"""
    from app import db
    from app.services import tester
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    original = tester.validate_config

    def probe(text):
        # 核心校验期间：另一个事务必须能立刻写入
        with db.tx() as conn:
            conn.execute("UPDATE settings SET value=value WHERE key='base_url'")
        return original(text)

    monkeypatch.setattr(tester, "validate_config", probe)
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build


def test_panel_direct_rule_can_be_disabled(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    # 默认置顶面板域名直连规则
    assert "DOMAIN-SUFFIX,{FEED_HOST},DIRECT" in art
    # 应用级伪键不进入产物
    assert "_panel_direct_rule" not in art

    client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h, json={
        "content": "mode: rule\nlog-level: warning\nipv6: false\n"
                   "_panel_direct_rule: false\n"})
    build2 = client.post("/api/v1/builds", headers=h, json={}).json()
    art2 = client.get(
        f"/api/v1/builds/{build2['id']}/artifact/stash-ios").json()["content"]
    assert "DOMAIN-SUFFIX,{FEED_HOST},DIRECT" not in art2
    assert "_panel_direct_rule" not in art2


def test_personal_direct_domains_and_fake_ip_filter(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    content = (
        "mode: rule\nlog-level: warning\nipv6: false\n"
        "_direct_domains:\n- magichub.top\n- '*.Jiek.top'\n- jiek.top\n"
        "- example.com\n"
        "_fake_ip_filter:\n- '+.lan'\n- 'geosite:private,cn,apple'\n"
    )
    assert client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h,
                      json={"content": content}).status_code == 200
    assert client.put("/api/v1/base-config?engine=mihomo&platform=android", headers=h,
                      json={"content": content}).status_code == 200
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art_s = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"])
    art_m = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/mihomo-android").json()["content"])

    # 个人直连域名：归一化后置顶在用户规则之前
    rules_s = art_s["rules"]
    assert "DOMAIN-SUFFIX,magichub.top,DIRECT" in rules_s
    assert "DOMAIN-SUFFIX,jiek.top,DIRECT" in rules_s
    assert "DOMAIN-SUFFIX,example.com,DIRECT" in rules_s
    assert rules_s.count("DOMAIN-SUFFIX,jiek.top,DIRECT") == 1
    assert rules_s.index("DOMAIN-SUFFIX,magichub.top,DIRECT") < rules_s.index(
        [r for r in rules_s if r.startswith("MATCH")][0])
    # 伪键不进入产物
    assert "_direct_domains" not in art_s and "_fake_ip_filter" not in art_s

    # Fake-IP 过滤：Mihomo 用个人列表替换内置列表，Stash 生成 dns 段
    assert art_m["dns"]["fake-ip-filter"] == ["+.lan", "geosite:private,cn,apple"]
    assert "localhost.ptlogin2.qq.com" not in art_m["dns"]["fake-ip-filter"]
    assert art_s["dns"]["fake-ip-filter"] == ["+.lan", "geosite:private,cn,apple"]


def test_personal_config_applied_by_production_script(client):
    """生产修正脚本应把个人直连域名与 Fake-IP 过滤写进两个引擎的基础配置。"""
    import importlib.util
    import os
    from app import db

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 引擎平台配置按「引擎 + 平台」，需要先有引擎平台
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    repo_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(repo_root, "scripts", "apply_production_fixes.py")
    spec = importlib.util.spec_from_file_location("apply_production_fixes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()

    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM base_configs "
                            "WHERE device_id=0 AND platform<>''")
        assert rows
        for row in rows:
            doc = json.loads(json.dumps(__import__("yaml").safe_load(row["content"])))
            assert "magichub.top" in doc["_direct_domains"]
            assert "ghfast.top" in doc["_direct_domains"]
            assert "geosite:private,cn,apple" in doc["_fake_ip_filter"]
            assert "+.xboxlive.com" in doc["_fake_ip_filter"]


def test_feed_marker_and_duplicate_rules(client):
    """Stash 客户端自己补 #SUBSCRIBED（避免重复）；完全重复的规则只保留一条。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h, json={
        "content": "mode: rule\nlog-level: warning\nipv6: false\n"
                   "_direct_domains:\n- testserver\n- example.com\n"})
    client.post("/api/v1/builds", headers=h, json={})
    client.post("/api/v1/builds", headers=h, json={})
    publish_to_prod(client, h, 1)
    device = client.post("/api/v1/devices", headers=h, json={
        "name": "测试机", "platform": "ios", "target_id": 1, "env": "production"}).json()
    token = device["token"]
    url = f"/feed/{token}/config.yaml"

    # 浏览器下载：保留 #SUBSCRIBED 首行（导入后客户端才知道从哪更新）
    resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 200
    assert resp.text.startswith("#SUBSCRIBED ")
    assert resp.text.count("#SUBSCRIBED ") == 1

    # Stash 客户端：不再补行，避免与客户端自己写的行重复
    resp = client.get(url, headers={"User-Agent": "Stash/3.7.0 (macOS)"})
    assert resp.status_code == 200
    assert "#SUBSCRIBED" not in resp.text

    # 面板置顶规则与个人直连域名同名时只保留一条
    rules = [l[2:] for l in resp.text.splitlines() if l.startswith("- ")]
    # 面板置顶规则替换占位符后与个人直连域名同名，只保留一条
    assert rules.count("DOMAIN-SUFFIX,testserver,DIRECT") == 1
    assert "DOMAIN-SUFFIX,example.com,DIRECT" in rules


def test_platform_scoped_base_config_differs_per_platform(client):
    """引擎平台配置按「引擎 + 平台」：同一引擎的不同平台可以产出不同产物。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "stash-mac", "engine": "stash", "platform": "macos"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "stash-android", "engine": "stash", "platform": "android"})
    assert r.status_code == 201, r.text

    # iOS 引擎平台配置
    client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h, json={
        "content": "mode: rule\nlog-level: warning\nipv6: false\nlog-level: info\n"})
    # macOS 引擎平台配置
    r = client.put("/api/v1/base-config?engine=stash&platform=macos", headers=h, json={
        "content": "mode: rule\nlog-level: warning\nipv6: false\nlog-level: debug\n"})
    assert r.status_code == 200, r.text

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    mac = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-mac").json()["content"])
    ios = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"])
    assert mac["log-level"] == "debug"
    assert ios["log-level"] == "info"
    # 平台级配置不写进其它平台
    other = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-android").json()["content"])
    assert other["log-level"] == "warning"


def test_group_and_rule_target_scope_filters_output(client):
    """策略组与规则的「适用目标」：只出现在指定目标里。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    for name, platform in (("stash-a", "macos"), ("stash-b", "tvos")):
        client.post("/api/v1/targets", headers=h, json={
            "name": name, "engine": "stash", "platform": platform})
    # 桌面专用组与规则
    r = client.post("/api/v1/groups", headers=h, json={
        "name": "桌面专用", "type": "select", "proxies": ["DIRECT"],
        "targets": ["stash-a"]})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "desktop-only.com", "target": "桌面专用",
        "targets": ["stash-a"]})
    assert r.status_code == 201, r.text

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    a = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-a").json()["content"])
    b = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-b").json()["content"])
    assert any(g["name"] == "桌面专用" for g in a["proxy-groups"])
    assert not any(g["name"] == "桌面专用" for g in b["proxy-groups"])
    assert "DOMAIN-SUFFIX,desktop-only.com,桌面专用" in a["rules"]
    assert "DOMAIN-SUFFIX,desktop-only.com,桌面专用" not in b["rules"]


def test_rule_pointing_to_absent_group_is_dropped(client):
    """规则指向不适用于本目标的组时，规则被剔除（否则客户端加载失败）。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    for name, platform in (("stash-a", "macos"), ("stash-b", "tvos")):
        client.post("/api/v1/targets", headers=h, json={
            "name": name, "engine": "stash", "platform": platform})
    client.post("/api/v1/groups", headers=h, json={
        "name": "仅A", "type": "select", "proxies": ["DIRECT"], "targets": ["stash-a"]})
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "x.com", "target": "仅A"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    b = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-b").json()["content"])
    assert "DOMAIN-SUFFIX,x.com,仅A" not in b["rules"]
    # 构建结果里应有剔除说明
    results = build["results"]
    assert any("仅A" in w for w in results["stash-b"]["warnings"])


def test_final_rule_group_is_always_kept(client):
    """兜底规则指向的组即使限定了其它目标，也必须保留。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    for name, platform in (("stash-a", "macos"), ("stash-b", "tvos")):
        client.post("/api/v1/targets", headers=h, json={
            "name": name, "engine": "stash", "platform": platform})
    client.post("/api/v1/groups", headers=h, json={
        "name": "兜底组", "type": "select", "proxies": ["DIRECT"],
        "targets": ["stash-a"]})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "value": "", "target": "兜底组"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    b = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-b").json()["content"])
    assert any(g["name"] == "兜底组" for g in b["proxy-groups"])
    assert "MATCH,兜底组" in b["rules"]


def test_platform_trims_process_rules(client):
    """移动端 / 电视端剔除进程类规则（该平台拿不到进程名）。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    for name, platform in (("stash-mac", "macos"), ("stash-ios", "ios")):
        client.post("/api/v1/targets", headers=h, json={
            "name": name, "engine": "stash", "platform": platform})
    client.post("/api/v1/rules", headers=h, json={
        "type": "PROCESS-NAME", "value": "qbittorrent", "target": "节点选择"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    mac = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-mac").json()["content"])
    ios = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"])
    assert "PROCESS-NAME,qbittorrent,节点选择" in mac["rules"]
    assert "PROCESS-NAME,qbittorrent,节点选择" not in ios["rules"]
    assert any("剔除" in w for w in build["results"]["stash-ios"]["warnings"])


def test_device_level_override_only_affects_that_device(client):
    """设备级扩展：只对该设备生效，且不允许覆盖结构键。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    client.post("/api/v1/builds", headers=h, json={})
    publish_to_prod(client, h, 1)
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "个性化设备", "platform": "ios", "target_id": 1,
        "env": "production"}).json()
    other = client.post("/api/v1/devices", headers=h, json={
        "name": "普通设备", "platform": "ios", "target_id": 1,
        "env": "production"}).json()
    # 设备配置作用域：只存与上层不同的差异
    r = client.put(f"/api/v1/base-config?engine=stash&device_id={dev['id']}",
                   headers=h, json={"content": "mode: rule\nlog-level: debug\n"
                                              "ipv6: false\n"})
    assert r.status_code == 200, r.text
    assert r.json()["overlay"]["log-level"] == "debug"
    assert r.json()["sources"]["log-level"] == "设备独立配置"
    a = client.get(f"/feed/{dev['token']}/config.yaml").text
    b = client.get(f"/feed/{other['token']}/config.yaml").text
    assert "log-level: debug" in a
    assert "log-level: debug" not in b
    # ETag 必须不同，避免缓存串味
    ra = client.get(f"/feed/{dev['token']}/config.yaml")
    rb = client.get(f"/feed/{other['token']}/config.yaml")
    assert ra.headers["etag"] != rb.headers["etag"]


def test_device_override_rejects_structural_keys(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "坏设备", "platform": "ios", "target_id": 1,
        "env": "production"}).json()
    client.post("/api/v1/builds", headers=h, json={})
    publish_to_prod(client, h, 1)
    # 结构键在设备配置作用域同样被拒绝
    r = client.put(f"/api/v1/base-config?engine=stash&device_id={dev['id']}",
                   headers=h, json={"content": "rules:\n  - MATCH,DIRECT\n"})
    assert r.status_code == 400
    assert "rules" in r.text


def test_no_differentiation_keeps_artifact_identical(client):
    """不做任何差异化配置时，产物与既有行为保持一致（结构与内容都不变）。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    client.post("/api/v1/builds", headers=h, json={})
    a = client.get("/api/v1/builds/1/artifact/stash-ios").json()["content"]
    client.post("/api/v1/builds", headers=h, json={})
    b = client.get("/api/v1/builds/2/artifact/stash-ios").json()["content"]
    assert a == b
    # 断言关键结构仍然存在
    cfg = yaml.safe_load(a)
    assert cfg["rules"][0] == "DOMAIN-SUFFIX,{FEED_HOST},DIRECT"
    assert cfg["rules"][-1].startswith("MATCH,")


def test_audit_batch_delete_and_clear(client):
    """审计日志：批量删除与清空。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 先产生几条记录
    client.post("/api/v1/sources", headers=h, json={
        "name": "机场", "url": "https://airport.example.com/sub"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "组", "type": "select", "proxies": ["DIRECT"]})
    rows = client.get("/api/v1/audit?limit=50", headers=h).json()["items"]
    assert len(rows) >= 2
    ids = [r["id"] for r in rows[:2]]
    r = client.post("/api/v1/audit/delete", headers=h, json={"ids": ids})
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == 2
    after = client.get("/api/v1/audit?limit=50", headers=h).json()["items"]
    assert not [x for x in after if x["id"] in ids]
    # 清空全部
    r = client.post("/api/v1/audit/delete", headers=h, json={"all": True})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/audit?limit=50", headers=h).json()["items"] == []
    # 空选择应被拒绝
    r = client.post("/api/v1/audit/delete", headers=h, json={})
    assert r.status_code == 400


def test_reset_base_config_keeps_personal_config(client):
    """恢复默认不应清空手工维护的个人直连域名与 Fake-IP 过滤。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    content = ("mode: rule\nlog-level: warning\nipv6: false\n"
               "_direct_domains:\n- example.com\n"
               "_fake_ip_filter:\n- '+.lan'\n")
    r = client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h,
                   json={"content": content})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/base-config/reset?engine=stash&platform=ios", headers=h)
    assert r.status_code == 200, r.text
    doc = r.json()["effective"]
    assert doc["_direct_domains"] == ["example.com"]
    assert doc["_fake_ip_filter"] == ["+.lan"]
    # 其余键恢复为默认
    assert doc["mode"] == "rule"


def test_validate_rendered_blocks_unsupported_rule_type_and_missing_target():
    """引擎级校验：Stash 不支持的规则类型、指向不存在出站的规则必须报错。"""
    from app.compiler import validate
    text = (
        "mode: rule\n"
        "rules:\n"
        "- UID,0,节点选择\n"
        "- DOMAIN-SUFFIX,a.com,不存在的组\n"
    )
    errors = validate.validate_rendered(text, "stash")
    assert any("UID" in e and "不被 stash 支持" in e for e in errors)
    assert any("不存在的出站" in e for e in errors)
    # Mihomo 支持 UID，但同样不允许指向不存在的出站
    errors = validate.validate_rendered(text, "mihomo")
    assert not any("不被 mihomo 支持" in e for e in errors)
    assert any("不存在的出站" in e for e in errors)


def test_mihomo_android_keeps_process_rules():
    """Mihomo 在 Android 上 PROCESS-NAME 可匹配包名，不应被裁剪。"""
    from app.compiler import render
    snapshot = {
        "sources": [], "rule_providers": [], "snippets": [],
        "groups": [{"name": "节点选择", "type": "select", "proxies": ["DIRECT"],
                    "use_sources": [], "local_nodes": [], "filter": "", "hidden": False,
                    "url": "", "interval": 600, "timeout": 8000, "tolerance": 150,
                    "lazy": True, "strategy": "", "targets": ["*"], "devices": ["*"]}],
        "rules": [{"type": "PROCESS-NAME", "value": "com.tencent.mm", "target": "节点选择",
                   "enabled": True, "targets": ["*"], "devices": ["*"]},
                  {"type": "MATCH", "value": "", "target": "节点选择", "enabled": True,
                   "targets": ["*"], "devices": ["*"]}],
    }
    warnings = []
    text = render.render_target(
        snapshot, {"name": "mihomo-android", "engine": "mihomo", "platform": "android"},
        warnings)
    assert "PROCESS-NAME,com.tencent.mm,节点选择" in text
    # Stash + Android：官方文档未收录该平台的早期版本，不做裁剪也不告警
    warnings = []
    text2 = render.render_target(
        snapshot, {"name": "stash-android", "engine": "stash", "platform": "android"},
        warnings)
    assert "PROCESS-NAME,com.tencent.mm" in text2
    assert not any("没有" in w for w in warnings)
    # Stash + iOS：官方明确说明会被忽略，裁掉是等价且更干净的做法
    warnings = []
    text3 = render.render_target(
        snapshot, {"name": "stash-ios", "engine": "stash", "platform": "ios"},
        warnings)
    assert "PROCESS-NAME,com.tencent.mm" not in text3
    assert any("剔除" in w for w in warnings)


def test_base_config_merge_semantics():
    """层级合并语义：键级并集，同键后者覆盖；字典递归、列表整体替换。"""
    from app.services import base_config as bc
    base = {
        "mode": "rule",
        "log-level": "warning",
        "dns": {"nameserver": ["a", "b"], "ipv6": False},
        "filter": ["x"],
    }
    over = {
        "mode": "global",
        "dns": {"nameserver": ["c"]},
        "filter": ["y"],
        "extra": 1,
    }
    merged = bc.merge_docs(base, over)
    # 同键后者覆盖
    assert merged["mode"] == "global"
    # 字典递归合并：dns.ipv6 保留，dns.nameserver 被整体替换
    assert merged["dns"] == {"nameserver": ["c"], "ipv6": False}
    # 列表整体替换，不拼接
    assert merged["filter"] == ["y"]
    # 只在上层出现的键保留
    assert merged["log-level"] == "warning"
    # 上层没有的键新增
    assert merged["extra"] == 1
    # 不修改入参
    assert base["dns"]["nameserver"] == ["a", "b"]
    assert base["mode"] == "rule"
    # 空覆盖 / 空基础
    assert bc.merge_docs(base, {}) == base
    assert bc.merge_docs({}, over) == over


def test_base_config_diff_overlay_keeps_only_changes():
    """本层只保存与上层不同的差异，其余键继续跟随上层。"""
    from app.services import base_config as bc
    inherited = {"mode": "rule", "log-level": "warning",
                 "dns": {"nameserver": ["a"], "ipv6": False}}
    effective = {"mode": "global", "log-level": "warning",
                 "dns": {"nameserver": ["b"], "ipv6": False}, "new": 2}
    overlay = bc.diff_overlay(inherited, effective)
    assert overlay == {"mode": "global", "dns": {"nameserver": ["b"]}, "new": 2}
    # 合并回去与编辑结果一致
    assert bc.merge_docs(inherited, overlay) == effective


def test_base_config_cascade_sources():
    """多级联动：生效值来自最高优先级的那一层。"""
    from app.services import base_config as bc
    docs = {
        ("stash", "ios", 0): {"mode": "global", "log-level": "info"},
        ("stash", "ios", 7): {"mode": "rule"},
    }
    layers = bc.scope_layers("stash", "ios", 7, docs)
    effective, sources = bc.cascade(layers)
    assert effective["mode"] == "rule"          # 设备独立配置覆盖引擎平台配置
    assert effective["log-level"] == "info"     # 引擎平台配置覆盖引擎默认配置
    assert sources["mode"] == "设备独立配置"
    assert sources["log-level"] == "引擎平台配置"
    assert sources["ipv6"] == "引擎默认配置"


def test_target_rename_keeps_group_and_rule_references(client):
    """引擎平台改名后，策略组与规则的"适用平台"引用要跟着改。

    否则引用指向不存在的引擎平台，对应的组与规则会在构建时被静默剔除。
    """
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    t = client.post("/api/v1/targets", headers=h, json={
        "name": "stash-old", "engine": "stash", "platform": "macos"}).json()
    g = client.post("/api/v1/groups", headers=h, json={
        "name": "手动组", "type": "select", "proxies": ["节点选择"],
        "targets": ["stash-old"]}).json()
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "renamed.example.com", "target": "手动组",
        "targets": ["stash-old"]})
    assert r.status_code == 201, r.text
    rule_id = r.json()["id"]

    # 改名
    r = client.put(f"/api/v1/targets/{t['id']}", headers=h, json={
        "name": "Stash-macOS", "engine": "stash", "platform": "macos"})
    assert r.status_code == 200, r.text

    groups = client.get("/api/v1/groups", headers=h).json()
    hit = next(g for g in groups if g["name"] == "手动组")
    assert hit["targets"] == ["Stash-macOS"]
    rules = client.get("/api/v1/rules", headers=h).json()
    hit = next(r for r in rules if r["id"] == rule_id)
    assert hit["targets"] == ["Stash-macOS"]

    # 改名后产物里该组仍要出现
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/Stash-macOS").json()["content"]
    assert "手动组" in art


def test_target_delete_cleans_references(client):
    """删除引擎平台时，引用它的策略组与规则要清理掉失效引用。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    t = client.post("/api/v1/targets", headers=h, json={
        "name": "stash-temp", "engine": "stash", "platform": "tvos"}).json()
    client.post("/api/v1/groups", headers=h, json={
        "name": "临时组", "type": "select", "proxies": ["节点选择"],
        "targets": ["stash-temp"]})
    r = client.delete(f"/api/v1/targets/{t['id']}", headers=h)
    assert r.status_code == 200, r.text
    groups = client.get("/api/v1/groups", headers=h).json()
    hit = next(g for g in groups if g["name"] == "临时组")
    assert hit["targets"] == []


def test_login_rate_limit_blocks_brute_force(client):
    """连续登录失败后应暂时拒绝，避免在线爆破。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    ok = client.post("/api/v1/auth/login",
                     json={"username": "admin", "password": "admin-pass-1"})
    assert ok.status_code == 200, ok.text

    for _ in range(6):
        bad = client.post("/api/v1/auth/login",
                          json={"username": "admin", "password": "wrong-pass"})
    assert bad.status_code == 429, bad.text
    # 正确口令此时也被挡住
    good = client.post("/api/v1/auth/login",
                       json={"username": "admin", "password": "admin-pass-1"})
    assert good.status_code == 429, good.text


def test_session_cookie_is_secure_over_https(client):
    """HTTPS 下的会话 Cookie 必须带 Secure，避免明文传输。"""
    csrf = setup_admin(client)
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "admin-pass-1"},
                    headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 200, r.text
    cookie = r.headers.get("set-cookie", "")
    assert "Secure" in cookie, cookie
    assert "HttpOnly" in cookie, cookie


def test_retention_prunes_old_artifacts_and_audit(client):
    """留存清理：过期构建产物目录与超量审计日志要被回收。"""
    from app import config, db
    from app.services import retention

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build

    with db.tx() as conn:
        # 造一个很旧的构建产物目录（不在保留窗口内）
        old_dir = config.BUILDS_DIR / "999999"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "x.yaml").write_text("x: 1", encoding="utf-8")
        # 审计日志塞到超过上限
        conn.execute("INSERT INTO audit(at, actor, action, object_type, object_id, detail) "
                     "SELECT at, actor, action, object_type, object_id, detail FROM audit")
        total = db.one(conn, "SELECT COUNT(*) AS c FROM audit")["c"]
    if total <= config.AUDIT_LOG_KEEP:
        with db.tx() as conn:
            for _ in range(config.AUDIT_LOG_KEEP + 10):
                conn.execute("INSERT INTO audit(at, actor, action, object_type, "
                             "object_id, detail) VALUES(?,?,?,?,?,?)",
                             (db.now(), "t", "a", "o", "1", ""))

    result = retention.run_once()
    assert result["artifacts"] >= 1
    assert not old_dir.exists()
    with db.connect() as conn:
        kept = db.one(conn, "SELECT COUNT(*) AS c FROM audit")["c"]
    assert kept <= config.AUDIT_LOG_KEEP


def test_fetcher_blocks_ssrf_targets():
    """抓取必须挡住内网/保留地址，包括域名解析到内网的情况。"""
    from app.services import fetcher

    # 字面内网地址
    for url in ("http://127.0.0.1:8080/x", "http://169.254.169.254/latest/meta-data/",
                "http://10.0.0.1/x", "http://[::1]/x"):
        with pytest.raises(fetcher.FetchError):
            fetcher._check_url(url, allow_private=False)
    # 非 http 协议
    with pytest.raises(fetcher.FetchError):
        fetcher._check_url("file:///etc/passwd", allow_private=False)
    with pytest.raises(fetcher.FetchError):
        fetcher._check_url("gopher://127.0.0.1/", allow_private=False)
    # 显式允许内网时放行
    fetcher._check_url("http://127.0.0.1:8080/x", allow_private=True)


def test_fetcher_rejects_redirect_to_private_address(monkeypatch):
    """重定向到内网地址必须被拒绝（防止借跳转绕过内网限制）。"""
    from app.services import fetcher

    def fake_stream(self, method, url, **kwargs):
        class Resp:
            status_code = 302
            headers = {"location": "http://127.0.0.1:9/secret"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    monkeypatch.setattr(httpx.Client, "stream", fake_stream)
    with pytest.raises(fetcher.FetchError):
        fetcher.fetch("http://example.com/x")


def test_audit_pagination_and_keyword(client):
    """审计日志支持分页与关键字搜索（否则记录多了翻不到更早的内容）。"""
    from app import db
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    with db.tx() as conn:
        for i in range(30):
            conn.execute("INSERT INTO audit(at, actor, action, object_type, object_id, detail) "
                         "VALUES(?,?,?,?,?,?)",
                         (db.now(), "tester", f"动作{i}", "source", str(i), "细节"))
    data = client.get("/api/v1/audit?limit=10&offset=0", headers=h).json()
    assert data["total"] >= 30
    assert len(data["items"]) == 10
    assert data["items"][0]["id"] > data["items"][9]["id"]   # 按 id 倒序
    page2 = client.get("/api/v1/audit?limit=10&offset=10", headers=h).json()
    assert page2["items"][0]["id"] < data["items"][-1]["id"]
    hit = client.get("/api/v1/audit?keyword=动作7", headers=h).json()
    assert hit["total"] >= 1
    assert all("动作7" in (i["action"] or "") for i in hit["items"])


def test_overview_reports_health_snapshot(client):
    """概览要给出运行状态自检：磁盘、备份、未拉取设备、核心。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    data = client.get("/api/v1/overview", headers=h).json()
    health = data["health"]
    assert "ok" in health and "issues" in health
    assert isinstance(health["issues"], list)
    assert health["disk_free_mb"] >= 0
    assert "core_available" in health
    # 没有任何备份时应该被点出来
    assert any("备份" in i for i in health["issues"]) or health["last_backup_at"]


def test_retention_prunes_builds_with_release_rows(client, monkeypatch):
    """留存清理按生命周期状态区分处理：

    * 从未发布过（BUILT）的构建：超出窗口整行删除；
    * 曾发布过（OFFLINE）的构建：超出「保留最近 N 个」窗口后**彻底清理**
      （记录、产物与发布历史一起删），避免历史构建无限堆积；
    * 生效中（PRODUCTION / TESTING）的构建：永不清理。

    同时发布历史里的外键行必须一起删，否则整轮清理回滚。
    """
    from app import config, db
    from app.services import retention

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    # 把两个留存窗口都调到最小，才能在用例里触发清理：
    # 未发布过的构建留 1 个，曾发布过的留 1 个
    monkeypatch.setattr(config, "BUILD_ARTIFACT_KEEP", 1)
    monkeypatch.setattr(config, "PUBLISHED_BUILD_KEEP", 1)

    first = client.post("/api/v1/builds", headers=h, json={}).json()
    assert first["verify_status"] == "success", first
    second = client.post("/api/v1/builds", headers=h, json={}).json()
    third = client.post("/api/v1/builds", headers=h, json={}).json()
    fourth = client.post("/api/v1/builds", headers=h, json={}).json()

    # 第二个构建上线后再被第三个替换 → 变成"已下线"归档
    publish_to_prod(client, h, second["id"])
    publish_to_prod(client, h, third["id"])

    with db.connect() as conn:
        assert db.one(conn, "SELECT COUNT(*) AS c FROM releases")["c"] >= 1

    result = retention.run_once()
    assert "artifacts" in result
    assert "builds" in result

    with db.connect() as conn:
        # 从未发布过的构建被整行删除
        assert db.one(conn, "SELECT COUNT(*) AS c FROM builds WHERE id=?",
                      (first["id"],))["c"] == 0
        # 已发布过但超出保留窗口的构建被彻底清理
        assert db.one(conn, "SELECT COUNT(*) AS c FROM builds WHERE id=?",
                      (second["id"],))["c"] == 0
        # 生效中的构建不受影响
        row = db.one(conn, "SELECT * FROM builds WHERE id=?", (third["id"],))
        assert row["status"] == "PRODUCTION" and row["snapshot"]
        # 清理后外键仍然一致
        broken = db.one(conn, "SELECT COUNT(*) AS c FROM releases r "
                              "LEFT JOIN builds b ON b.id = r.build_id "
                              "WHERE b.id IS NULL")["c"]
        assert broken == 0
        # 被清理掉的构建，其发布历史一并清掉
        assert db.one(conn, "SELECT COUNT(*) AS c FROM releases "
                            "WHERE build_id=?", (second["id"],))["c"] == 0

    # 彻底清理后连归档行都查不到
    assert client.get(f"/api/v1/builds/{second['id']}", headers=h).status_code == 404


def test_retention_keeps_recent_published_builds(client, monkeypatch):
    """已发布过的构建保留最近 N 个，超出的才彻底清理。"""
    from app import config, db
    from app.services import retention

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    monkeypatch.setattr(config, "PUBLISHED_BUILD_KEEP", 3)
    monkeypatch.setattr(config, "BUILD_ARTIFACT_KEEP", 50)

    ids = []
    for _ in range(5):
        build = client.post("/api/v1/builds", headers=h, json={}).json()
        assert build["verify_status"] == "success", build
        ids.append(build["id"])
        publish_to_prod(client, h, build["id"])

    retention.run_once()

    with db.connect() as conn:
        alive = {int(r["id"]) for r in conn.execute("SELECT id FROM builds")}
    # 只剩最近 3 个已发布过的构建（含当前生产版本）
    assert alive == set(ids[-3:])
    # 被清理掉的老构建连发布历史也没了
    with db.connect() as conn:
        assert db.one(conn, "SELECT COUNT(*) AS c FROM releases "
                            "WHERE build_id=?", (ids[0],))["c"] == 0


def test_paged_list_endpoints(client):
    """列表接口分页：超过一页时能翻页，且总数正确。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    for i in range(25):
        r = client.post("/api/v1/groups", headers=h, json={
            "name": f"分页组{i:02d}", "type": "select", "proxies": ["DIRECT"]})
        assert r.status_code == 201, r.text

    data = client.get("/api/v1/groups/page?limit=10&offset=0", headers=h).json()
    assert data["total"] == 25
    assert len(data["items"]) == 10
    assert data["limit"] == 10 and data["offset"] == 0
    first_page = [g["id"] for g in data["items"]]

    data2 = client.get("/api/v1/groups/page?limit=10&offset=10", headers=h).json()
    assert len(data2["items"]) == 10
    assert not set(first_page) & {g["id"] for g in data2["items"]}
    data3 = client.get("/api/v1/groups/page?limit=10&offset=20", headers=h).json()
    assert len(data3["items"]) == 5
    # 关键字过滤
    hit = client.get("/api/v1/groups/page?keyword=分页组0", headers=h).json()
    assert hit["total"] >= 1
    # 其它列表端点同样可用
    for path in ("/api/v1/rules/page", "/api/v1/sources/page",
                 "/api/v1/rule-providers/page", "/api/v1/targets/page",
                 "/api/v1/devices/page", "/api/v1/snippets/page",
                 "/api/v1/builds/page"):
        r = client.get(path + "?limit=5&offset=0", headers=h)
        assert r.status_code == 200, (path, r.text)
        body = r.json()
        assert "items" in body and "total" in body


def test_local_first_puts_local_nodes_before_group_members(client):
    """策略组开启「本地节点排在最前」后，产物里本地节点排在其它成员之前。"""
    import yaml as _yaml
    from app import db

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    node = client.post("/api/v1/local-nodes", headers=h, json={
        "name": "本地甲", "protocol": "http", "server": "1.2.3.4", "port": 80}).json()
    gid = client.post("/api/v1/groups", headers=h, json={
        "name": "机房优先组", "type": "fallback", "proxies": ["DIRECT"],
        "local_nodes": [node["id"]], "local_first": True}).json()
    assert gid["local_first"] is True
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    cfg = _yaml.safe_load(art)
    group = next(g for g in cfg["proxy-groups"] if g["name"] == "机房优先组")
    members = group["proxies"]
    # 空组保护在前（占位），其后应是本地节点，再往后才是普通成员
    assert "本地甲 (本地)" in members
    assert members.index("本地甲 (本地)") < members.index("DIRECT")


def test_fallback_rule_is_moved_to_end_of_artifact(client):
    """兜底规则排在中间时，产物里必须被提到末尾——否则它后面的规则永远不生效。"""
    import yaml as _yaml
    from app import db

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    # 在兜底规则之后再插一条规则（界面允许任意顺序）
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "late.example.com", "target": "节点选择"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    rules = _yaml.safe_load(art)["rules"]
    assert rules[-1].split(",")[0] in ("MATCH", "FINAL")
    # 兜底之后不允许再有普通规则
    first_final = next(i for i, r in enumerate(rules)
                       if r.split(",")[0] in ("MATCH", "FINAL"))
    assert all(r.split(",")[0] in ("MATCH", "FINAL") for r in rules[first_final + 1:])


def test_guard_proxy_is_last_member_of_auto_groups(client):
    """「空组保护」占位节点必须排在组末尾：它是 127.0.0.1:1 的死节点，
    排在前面会被不做健康检查的客户端选成首选。"""
    import yaml as _yaml

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    cfg = _yaml.safe_load(art)
    auto = [g for g in cfg["proxy-groups"]
            if g.get("type") in ("url-test", "fallback", "load-balance")]
    assert auto, "产物里应至少有一个自动组"
    for g in auto:
        members = g.get("proxies") or []
        if "空组保护" in members:
            assert members[-1] == "空组保护", (g["name"], members)


def test_batch_update_and_delete_groups(client):
    """策略组批量修改 / 批量删除。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    ids = []
    for i in range(3):
        r = client.post("/api/v1/groups", headers=h, json={
            "name": f"批组{i}", "type": "select", "proxies": ["DIRECT"]})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    # 批量改：只提交 use_sources 与 hidden，其余不动
    r = client.patch("/api/v1/groups/batch", headers=h, json={
        "ids": ids[:2], "use_sources": ["测试机场"], "hidden": True})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    g = client.get("/api/v1/groups", headers=h).json()
    by_name = {x["name"]: x for x in g}
    assert by_name["批组0"]["use_sources"] == ["测试机场"]
    assert by_name["批组0"]["hidden"] is True
    assert by_name["批组2"]["use_sources"] == ["*"]   # 没选中的不动（默认包含所有）
    assert by_name["批组2"]["hidden"] is False
    # 空列表 = 清空
    r = client.patch("/api/v1/groups/batch", headers=h, json={
        "ids": ids[:2], "use_sources": []})
    assert r.status_code == 200, r.text
    g = client.get("/api/v1/groups", headers=h).json()
    assert {x["name"]: x for x in g}["批组0"]["use_sources"] == []
    # relay 组不接受节点来源 → 跳过并说明
    relay = client.post("/api/v1/groups", headers=h, json={
        "name": "链组", "type": "relay", "proxies": ["DIRECT", "REJECT"]}).json()
    r = client.patch("/api/v1/groups/batch", headers=h, json={
        "ids": [relay["id"]], "use_sources": ["测试机场"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 0
    assert body["skipped"] and "relay" in body["skipped"][0]["reason"]
    # 批量删除：被规则引用的保留
    r = client.post("/api/v1/groups/batch/delete", headers=h, json={
        "ids": [ids[0], ids[2]]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == [ids[0], ids[2]]
    # 字段全空 → 400
    assert client.patch("/api/v1/groups/batch", headers=h, json={
        "ids": ids[:2]}).status_code == 400


def test_batch_update_and_delete_rules(client):
    """分流规则批量修改 / 批量删除（兜底规则不删）。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    ids = []
    for i in range(3):
        r = client.post("/api/v1/rules", headers=h, json={
            "type": "DOMAIN-SUFFIX", "value": f"batch{i}.example.com",
            "target": "节点选择"})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    # 批量改目标 + 停用
    r = client.patch("/api/v1/rules/batch", headers=h, json={
        "ids": ids[:2], "target": "地区自动", "enabled": False, "note": "批量备注"})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    rules = client.get("/api/v1/rules", headers=h).json()
    by_value = {x["value"]: x for x in rules}
    assert by_value["batch0.example.com"]["target"] == "地区自动"
    assert by_value["batch0.example.com"]["enabled"] is False
    assert by_value["batch0.example.com"]["note"] == "批量备注"
    assert by_value["batch2.example.com"]["target"] == "节点选择"   # 未选中不动
    # 目标不存在 → 跳过
    r = client.patch("/api/v1/rules/batch", headers=h, json={
        "ids": ids[:1], "target": "不存在的组"})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 0
    assert r.json()["skipped"]
    # 批量删除：MATCH 兜底不删
    final_id = next(x["id"] for x in rules if x["type"] == "MATCH")
    r = client.post("/api/v1/rules/batch/delete", headers=h, json={
        "ids": ids + [final_id]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["deleted"]) == set(ids)
    assert any(b["id"] == final_id for b in body["blocked"])


def test_batch_group_update_drops_self_reference(client):
    """批量修改包含策略时，不能把组自己加进自己的成员里。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    gid = client.post("/api/v1/groups", headers=h, json={
        "name": "自环组", "type": "select", "proxies": ["DIRECT"]}).json()["id"]
    r = client.patch("/api/v1/groups/batch", headers=h, json={
        "ids": [gid], "proxies": ["自环组", "DIRECT"]})
    assert r.status_code == 200, r.text
    g = client.get("/api/v1/groups", headers=h).json()
    members = next(x for x in g if x["name"] == "自环组")["proxies"]
    assert "自环组" not in members
    assert "DIRECT" in members


def test_device_reorder_and_batch(client):
    """设备排序、批量修改、批量删除。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    t1 = client.post("/api/v1/targets", headers=h, json={
        "name": "t-one", "engine": "stash", "platform": "ios"}).json()
    t2 = client.post("/api/v1/targets", headers=h, json={
        "name": "t-two", "engine": "stash", "platform": "macos"}).json()
    ids = []
    for i in range(3):
        r = client.post("/api/v1/devices", headers=h, json={
            "name": f"dev{i}", "platform": "ios", "target_id": t1["id"],
            "env": "production", "note": f"note{i}"})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    # 排序
    r = client.post("/api/v1/devices/reorder", headers=h, json=list(reversed(ids)))
    assert r.status_code == 200, r.text
    rows = client.get("/api/v1/devices", headers=h).json()
    assert [d["id"] for d in rows] == list(reversed(ids))
    # 批量修改：换目标（平台应跟随目标）、换订阅环境、改备注
    r = client.patch("/api/v1/devices/batch", headers=h, json={
        "ids": ids[:2], "target_id": t2["id"], "env": "testing", "note": "批量"})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    rows = client.get("/api/v1/devices", headers=h).json()
    by_id = {d["id"]: d for d in rows}
    assert by_id[ids[0]]["target_id"] == t2["id"]
    assert by_id[ids[0]]["platform"] == "macos"     # 平台跟随目标
    assert by_id[ids[0]]["env"] == "testing"
    assert by_id[ids[0]]["note"] == "批量"
    assert by_id[ids[2]]["note"] == "note2"          # 未选中的不动
    # 非法环境值被拒绝
    assert client.patch("/api/v1/devices/batch", headers=h, json={
        "ids": ids[:1], "env": "beta"}).status_code == 400
    # 空字段 → 400
    assert client.patch("/api/v1/devices/batch", headers=h, json={
        "ids": ids[:1]}).status_code == 400
    # 批量删除：设备独立配置一并清理
    r = client.post("/api/v1/devices/batch/delete", headers=h, json={"ids": ids[:2]})
    assert r.status_code == 200, r.text
    assert set(r.json()["deleted"]) == set(ids[:2])
    assert len(client.get("/api/v1/devices", headers=h).json()) == 1


def test_base_config_scopes_follow_target_and_device_order(client):
    """产物配置页的作用域顺序跟着引擎平台页、设备管理页走，名称也一致。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    t1 = client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-iOS", "engine": "stash", "platform": "ios"}).json()
    t2 = client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-macOS", "engine": "stash", "platform": "macos"}).json()
    # 把 macOS 排到前面
    assert client.post("/api/v1/targets/reorder", headers=h,
                       json=[t2["id"], t1["id"]]).status_code == 200
    d1 = client.post("/api/v1/devices", headers=h, json={
        "name": "MacBook", "platform": "macos", "target_id": t2["id"]}).json()
    d2 = client.post("/api/v1/devices", headers=h, json={
        "name": "iPhone", "platform": "ios", "target_id": t1["id"]}).json()
    assert client.post("/api/v1/devices/reorder", headers=h,
                       json=[d2["id"], d1["id"]]).status_code == 200
    scopes = client.get("/api/v1/base-config/scopes", headers=h).json()["scopes"]
    general = [s for s in scopes if s["kind"] == "general"]
    assert [s["label"] for s in general][:2] == ["Stash-macOS", "Stash-iOS"]
    device = [s for s in scopes if s["kind"] == "device"]
    assert [s["label"] for s in device] == ["iPhone（设备独立配置）", "MacBook（设备独立配置）"]


def test_base_config_scope_labels_match_engine_platforms(client):
    """引擎平台配置的名字一律是引擎平台名。

    同一「引擎 + 平台」只允许一个引擎平台（个性化落在设备上），
    所以这一层的名字就是那一个引擎平台的名字。
    """
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-Android", "engine": "stash", "platform": "android"})
    client.post("/api/v1/targets", headers=h, json={
        "name": "Mihomo-macOS", "engine": "mihomo", "platform": "macos"})

    scopes = client.get("/api/v1/base-config/scopes", headers=h).json()["scopes"]
    general = [s for s in scopes if s["kind"] == "general"]
    labels = [s["label"] for s in general]
    assert "Stash-Android" in labels
    assert "Mihomo-macOS" in labels
    assert not any("·" in label for label in labels)
    # 唯一对应时直接用引擎平台名
    # 说明行里也写清对应的引擎平台
    shared = next(s for s in general if s["label"].startswith("Stash-Android"))
    assert "Stash-Android" in shared["detail"]


def test_base_config_leaf_sources(client):
    """叶子级来源：dns.nameserver 与 dns.enable 可以来自不同层级。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-iOS", "engine": "stash", "platform": "ios"})
    content = (
        "mode: rule\n"
        "dns:\n"
        "  enable: true\n"
        "  nameserver:\n"
        "    - 1.1.1.1\n"
    )
    r = client.put("/api/v1/base-config?engine=stash&platform=ios", headers=h,
                   json={"content": content, "updated_at": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    leaf = body["leaf_sources"]
    assert leaf["dns.nameserver"] == "引擎平台配置"
    assert leaf["mode"] == "引擎默认配置"


def test_portal_pin_is_four_digits(client):
    """门户 PIN 统一 4 位：新建必须是 4 位数字；历史 6 位仍能校验通过。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 新建必须是 4 位
    assert client.post("/api/v1/portal/my-pin", headers=h,
                       json={"pin": "12345"}).status_code == 422
    assert client.post("/api/v1/portal/my-pin", headers=h,
                       json={"pin": "123456"}).status_code == 422
    r = client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "2468"})
    assert r.status_code == 201, r.text
    # 门户页用该 PIN 打开（匿名访问：清掉会话，已登录维护者本来就免 PIN）
    client.cookies.clear()
    r = client.post("/api/v1/portal/data", json={"pin": "2468"})
    assert r.status_code == 200, r.text
    assert "devices" in r.json()
    # 错误 PIN 被拒（403 = PIN 不正确；401 会误导为"会话问题"）
    assert client.post("/api/v1/portal/data", json={"pin": "1111"}).status_code == 403


def test_target_engine_platform_must_be_unique(client):
    """同一「引擎 + 平台」只能有一个引擎平台。

    引擎平台代表"本项目支持的某引擎在某平台上的产物"，不是给某个人用的；
    个性化应该落在设备上，而不是复制一份引擎平台。
    """
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-macOS", "engine": "stash", "platform": "macos"})
    assert r.status_code == 201, r.text
    # 同名不行
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-macOS-2", "engine": "stash", "platform": "macos"})
    assert r.status_code == 409, r.text
    assert "macos" in r.json()["detail"]
    # 换引擎或换平台都可以
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "Mihomo-macOS", "engine": "mihomo", "platform": "macos"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-tvOS", "engine": "stash", "platform": "tvos"})
    assert r.status_code == 201, r.text
    # 改名不能撞上已有的引擎 + 平台
    r = client.put(f"/api/v1/targets/{r.json()['id']}", headers=h, json={
        "name": "Stash-tvOS-2", "engine": "stash", "platform": "macos"})
    assert r.status_code == 409, r.text


def test_device_scope_produces_per_device_artifact(client):
    """设备专属的策略组与规则只出现在这台设备的产物里。

    引擎平台共享产物里不含这些条目；构建会另外产出一份设备专属产物，
    设备拉取时优先用自己的那份。
    """
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    target = client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-macOS", "engine": "stash", "platform": "macos"}).json()
    other = client.post("/api/v1/targets", headers=h, json={
        "name": "Mihomo-macOS", "engine": "mihomo", "platform": "macos"}).json()
    dev_a = client.post("/api/v1/devices", headers=h, json={
        "name": "设备A", "platform": "macos", "target_id": target["id"]}).json()
    dev_b = client.post("/api/v1/devices", headers=h, json={
        "name": "设备B", "platform": "macos", "target_id": target["id"]}).json()

    r = client.post("/api/v1/groups", headers=h, json={
        "name": "专属组", "type": "select", "proxies": ["DIRECT"],
        "devices": ["设备A"]})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "only-a.com", "target": "专属组",
        "devices": ["设备A"]})
    assert r.status_code == 201, r.text
    # 设备名写错必须报错，不能静默失效
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "x.com", "target": "专属组",
        "devices": ["不存在的设备"]})
    assert r.status_code == 400, r.text

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    shared = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/Stash-macOS").json()["content"])
    assert not any(g["name"] == "专属组" for g in shared["proxy-groups"])
    assert "DOMAIN-SUFFIX,only-a.com,专属组" not in shared["rules"]
    # 设备 A 有自己的产物
    own = yaml.safe_load(client.get(
        f"/api/v1/builds/{build['id']}/artifact/设备A").json()["content"])
    assert any(g["name"] == "专属组" for g in own["proxy-groups"])
    assert "DOMAIN-SUFFIX,only-a.com,专属组" in own["rules"]
    # 设备 B 没有专属条目，仍用共享产物
    assert "设备B" not in build["results"]
    assert dev_b["id"] and dev_a["id"]


def test_device_config_layer_appends_lists_like_the_other_layers(client):
    """设备独立配置是"个性化"语义：列表追加，界面看到的就是下发的。

    引擎默认配置 / 引擎平台配置是"这一层的完整配置"语义：列表整体替换；
    设备独立配置只表达"这台设备额外要的"，因此列表记新增项并追加。
    """
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    target = client.post("/api/v1/targets", headers=h, json={
        "name": "Stash-macOS", "engine": "stash", "platform": "macos"}).json()
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "我的Mac", "platform": "macos", "target_id": target["id"]}).json()

    # 引擎平台配置：一份带过滤列表的 DNS
    r = client.put("/api/v1/base-config", headers=h, json={
        "content": "dns:\n  fake-ip-filter:\n  - +.lan\n  - +.local\n"},
        params={"engine": "stash", "platform": "macos"})
    assert r.status_code == 200, r.text
    # 设备独立配置：把过滤列表换成自己的一份
    r = client.put("/api/v1/base-config", headers=h, json={
        "content": "dns:\n  fake-ip-filter:\n  - +.lan\n  - +.local\n  - my.example\n"},
        params={"engine": "stash", "platform": "macos", "device_id": dev["id"]})
    assert r.status_code == 200, r.text
    # 差异里只保存新增的那一条
    assert r.json()["overlay"]["dns"]["fake-ip-filter"] == ["my.example"]
    # 界面里的生效值 = 上层 + 新增
    assert r.json()["effective"]["dns"]["fake-ip-filter"] == [
        "+.lan", "+.local", "my.example"]

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    art = client.get(
        f"/api/v1/builds/{build['id']}/artifact/Stash-macOS").json()["content"]
    shared = yaml.safe_load(art)
    # 平台产物里是平台层那份（设备层在分发时叠加，不进产物）
    assert shared["dns"]["fake-ip-filter"] == ["+.lan", "+.local"]


def test_device_config_follows_its_target(client):
    """设备独立配置必须跟着设备所在的引擎平台走（换键而不是静默失效）。

    设备迁移到别的引擎平台、或引擎平台改了引擎/平台之后，
    旧键下的配置既不下发也不显示，属于静默失效——必须自动换键。
    """
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    t1 = client.post("/api/v1/targets", headers=h, json={
        "name": "Mihomo-Windows", "engine": "mihomo", "platform": "windows"}).json()
    t2 = client.post("/api/v1/targets", headers=h, json={
        "name": "Mihomo-macOS", "engine": "mihomo", "platform": "macos"}).json()
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "我的电脑", "platform": "windows", "target_id": t1["id"]}).json()
    r = client.put("/api/v1/base-config", headers=h, json={
        "content": "log-level: info\n"},
        params={"engine": "mihomo", "platform": "windows", "device_id": dev["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["overlay"] == {"log-level": "info"}

    # 设备迁移到别的引擎平台：这一层要跟着走
    r = client.put(f"/api/v1/devices/{dev['id']}", headers=h, json={
        "name": "我的电脑", "platform": "macos", "target_id": t2["id"]})
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/base-config", headers=h, params={
        "engine": "mihomo", "platform": "macos", "device_id": dev["id"]})
    assert r.json()["overlay"] == {"log-level": "info"}, r.json()["overlay"]
    # 设备作用域只有一个（按设备定位），换键后这里仍能读到，且只有一份
    r = client.get("/api/v1/base-config", headers=h, params={
        "engine": "mihomo", "platform": "macos", "device_id": dev["id"]})
    assert r.json()["overlay"] == {"log-level": "info"}
    assert r.json()["is_default"] is False


def test_target_engine_change_rekeys_device_configs(client):
    """引擎平台改了引擎/平台，它下面设备的独立配置也要跟着换键。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    t = client.post("/api/v1/targets", headers=h, json={
        "name": "some-platform", "engine": "mihomo", "platform": "windows"}).json()
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "设备一", "platform": "windows", "target_id": t["id"]}).json()
    r = client.put("/api/v1/base-config", headers=h, json={
        "content": "log-level: debug\n"},
        params={"engine": "mihomo", "platform": "windows", "device_id": dev["id"]})
    assert r.status_code == 200, r.text
    # 引擎平台改平台
    r = client.put(f"/api/v1/targets/{t['id']}", headers=h, json={
        "name": "some-platform", "engine": "mihomo", "platform": "macos"})
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/base-config", headers=h, params={
        "engine": "mihomo", "platform": "macos", "device_id": dev["id"]})
    assert r.json()["overlay"] == {"log-level": "debug"}, r.json()["overlay"]
