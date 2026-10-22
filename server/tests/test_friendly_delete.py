"""友好删除：被引用的对象也能删，引用关系由后台自动处理。

统一约定：
  - 删除接口在对象仍被引用时返回 409 + 结构化引用明细
    （code / message / references），前端据此弹二次确认；
  - 带 force=1 时后台自动解绑后删除：
      节点来源 → 从策略组的 use_sources 里摘掉
      本地节点 → 从策略组的 local_nodes 里摘掉
      规则来源 → 删除引用它的 RULE-SET 规则
      策略组   → 其它组的成员引用摘掉 + 删除指向它的分流规则
      引擎平台 → 使用它的设备迁移到指定平台
"""
import pytest

from conftest import auth_headers, setup_admin


def _source(client, h, name="机场A"):
    r = client.post("/api/v1/sources", headers=h, json={
        "name": name, "url": "https://a.example.com/sub?token=abc123"})
    assert r.status_code == 201, r.text
    return r.json()


def _second_source(client, h):
    """再补一个来源：只有"选了一部分"的组才会被当成引用了具体来源。

    选满全部来源的组会被归一成"包含所有"，那是不绑定具体来源的。
    """
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "机场B", "url": "https://b.example.com/sub?token=def456"})
    assert r.status_code == 201, r.text
    return r.json()


def _group(client, h, name, **kw):
    body = {"name": name, "type": "select", "proxies": ["DIRECT"], **kw}
    r = client.post("/api/v1/groups", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _local_node(client, h, name="HK-01"):
    r = client.post("/api/v1/local-nodes", headers=h, json={
        "name": name, "node_type": "本地", "protocol": "ss",
        "server": "hk.example.com", "port": 8388,
        "params": {"cipher": "aes-256-gcm", "password": "pw", "udp": True}})
    assert r.status_code == 201, r.text
    return r.json()


def _rule_provider(client, h, name="rules-a"):
    r = client.post("/api/v1/rule-providers", headers=h, json={
        "name": name, "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - a.example.com\n"})
    assert r.status_code == 201, r.text
    return r.json()


def _rule(client, h, **kw):
    body = {"type": "DOMAIN-SUFFIX", "value": "example.com", "target": "DIRECT", **kw}
    r = client.post("/api/v1/rules", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _target(client, h, name, platform="ios"):
    r = client.post("/api/v1/targets", headers=h, json={
        "name": name, "engine": "mihomo", "platform": platform})
    assert r.status_code == 201, r.text
    return r.json()


# ---- 节点来源 ----

def test_source_delete_reports_references_then_force_detaches(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h)
    _second_source(client, h)
    _group(client, h, "组一", use_sources=[src["name"]])
    _group(client, h, "组二", use_sources=[src["name"]])

    r = client.delete(f"/api/v1/sources/{src['id']}", headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "source_in_use"
    assert {x["name"] for x in detail["references"]} == {"组一", "组二"}
    assert detail["source"]["name"] == src["name"]
    # 拒绝时不动数据
    assert client.get("/api/v1/sources", headers=h).json()[0]["name"] == src["name"]

    r = client.delete(f"/api/v1/sources/{src['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert set(r.json()["detached_groups"]) == {"组一", "组二"}
    # 另一个来源还在（组只引用了其中一个，不算"包含所有"）
    assert [x["name"] for x in client.get("/api/v1/sources", headers=h).json()] == ["机场B"]
    groups = {g["name"]: g for g in client.get("/api/v1/groups", headers=h).json()}
    assert groups["组一"]["use_sources"] == []
    assert groups["组二"]["use_sources"] == []


def test_source_delete_force_warns_when_group_becomes_empty(client):
    """组里只有这一个来源时，删掉它组就空了——构建会报错，要提前警告。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h)
    _second_source(client, h)
    _group(client, h, "空组", use_sources=[src["name"]], proxies=[])
    r = client.delete(f"/api/v1/sources/{src['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert any("将变为空" in w for w in r.json()["warnings"])


def test_source_batch_delete_force(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h)
    _second_source(client, h)
    _group(client, h, "组一", use_sources=[src["name"]])

    r = client.post("/api/v1/sources/batch/delete", headers=h,
                    json={"ids": [src["id"]]})
    assert r.status_code == 200
    assert r.json()["deleted"] == []
    assert r.json()["blocked"][0]["references"][0]["name"] == "组一"

    r = client.post("/api/v1/sources/batch/delete", headers=h,
                    json={"ids": [src["id"]], "force": True})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == [src["id"]]
    groups = client.get("/api/v1/groups", headers=h).json()
    assert groups[0]["use_sources"] == []


# ---- 本地节点 ----

def test_local_node_delete_force_detaches_from_group(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _local_node(client, h)
    _group(client, h, "本地组", local_nodes=[node["id"]])

    r = client.delete(f"/api/v1/local-nodes/{node['id']}", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "local_node_in_use"

    r = client.delete(f"/api/v1/local-nodes/{node['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["detached_groups"] == ["本地组"]
    groups = client.get("/api/v1/groups", headers=h).json()
    assert groups[0]["local_nodes"] == []
    assert client.get("/api/v1/local-nodes", headers=h).json() == []


# ---- 规则来源 ----

def test_rule_provider_delete_force_removes_rules(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    rp = _rule_provider(client, h)
    rule = _rule(client, h, type="RULE-SET", value=rp["name"])

    r = client.delete(f"/api/v1/rule-providers/{rp['id']}", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "rule_provider_in_use"
    assert r.json()["detail"]["references"][0]["id"] == rule["id"]

    r = client.delete(f"/api/v1/rule-providers/{rp['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()["deleted_rules"]] == [rule["id"]]
    assert client.get(f"/api/v1/rules/{rule['id']}", headers=h).status_code == 404


# ---- 策略组 ----

def test_group_delete_force_detaches_members_and_rules(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    inner = _group(client, h, "子组")
    outer = _group(client, h, "父组", proxies=["子组", "DIRECT"])
    rule = _rule(client, h, target="子组")

    r = client.delete(f"/api/v1/groups/{inner['id']}", headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "group_in_use"
    kinds = {x["type"] for x in detail["references"]}
    assert kinds == {"策略组", "分流规则"}

    r = client.delete(f"/api/v1/groups/{inner['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["detached_groups"] == ["父组"]
    assert [x["id"] for x in r.json()["removed_rules"]] == [rule["id"]]
    groups = {g["name"]: g for g in client.get("/api/v1/groups", headers=h).json()}
    assert groups["父组"]["proxies"] == ["DIRECT"]
    assert client.get(f"/api/v1/rules/{rule['id']}", headers=h).status_code == 404


def test_group_delete_force_warns_when_relay_loses_member(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    node = _local_node(client, h)
    relay = _group(client, h, "转发链", type="relay",
                   proxies=["DIRECT"], local_nodes=[node["id"]])
    r = client.delete(f"/api/v1/local-nodes/{node['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text
    assert any("relay" in w for w in r.json()["warnings"])


# ---- 引擎平台 ----

def test_target_delete_requires_migration_for_devices(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    t1 = _target(client, h, "ios-a", platform="ios")
    t2 = _target(client, h, "ios-b", platform="macos")
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "iPhone", "platform": "ios", "target_id": t1["id"]}).json()

    r = client.delete(f"/api/v1/targets/{t1['id']}", headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "target_in_use"
    assert detail["references"][0]["name"] == "iPhone"
    assert [c["id"] for c in detail["candidates"]] == [t2["id"]]

    # 指定迁移目标后才可以删
    r = client.delete(f"/api/v1/targets/{t1['id']}?force=1", headers=h)
    assert r.status_code == 400
    r = client.delete(f"/api/v1/targets/{t1['id']}?force=1&move_to={t2['id']}",
                      headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["moved_devices"] == ["iPhone"]
    devices = client.get("/api/v1/devices", headers=h).json()
    assert devices[0]["target_id"] == t2["id"]


# ---- 一致性 ----

def test_force_delete_leaves_no_dangling_references(client):
    """强制删除后，库里不能留下指向已删对象的引用。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h)
    node = _local_node(client, h)
    rp = _rule_provider(client, h)
    _group(client, h, "混合组", use_sources=[src["name"]],
           local_nodes=[node["id"]], proxies=["DIRECT"])
    _rule(client, h, type="RULE-SET", value=rp["name"], target="混合组")

    client.delete(f"/api/v1/sources/{src['id']}?force=1", headers=h)
    client.delete(f"/api/v1/local-nodes/{node['id']}?force=1", headers=h)
    client.delete(f"/api/v1/rule-providers/{rp['id']}?force=1", headers=h)

    # 必须在用例内部导入 app.db：模块级导入拿到的是采集阶段的旧实例，
    # 里面的数据目录指向仓库的 data/，不是本用例的临时目录
    from app import db

    with db.connect() as conn:
        # 规则来源没了，RULE-SET 规则也不该残留
        assert db.one(conn, "SELECT COUNT(*) AS c FROM rules "
                            "WHERE type='RULE-SET' AND value=?", (rp["name"],))["c"] == 0
        # 策略组里的来源/本地节点引用都要清干净
        groups = db.all_(conn, "SELECT name, use_sources, local_nodes FROM proxy_groups")
        for g in groups:
            assert src["name"] not in json.loads(g["use_sources"] or "[]")
            assert node["id"] not in json.loads(g["local_nodes"] or "[]")
        # 规则指向的策略组仍然存在
        dangling = db.one(
            conn,
            "SELECT COUNT(*) AS c FROM rules r LEFT JOIN proxy_groups g "
            "ON g.name = r.target WHERE r.target NOT IN ('DIRECT','REJECT') "
            "AND g.id IS NULL")["c"]
        assert dangling == 0


import json  # noqa: E402
