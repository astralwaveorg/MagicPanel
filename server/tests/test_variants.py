"""分流方案：多套策略组与规则、逐方案构建与按方案分发。

每个方案 = 一套完整、独立的组与规则副本；默认方案（id=0）是系统方案，
行为与历史版本一致。构建对每个启用方案各出一份产物；订阅地址用
?variant=<方案名> 选择方案。
"""
import pytest

from conftest import auth_headers, setup_admin


def _policy(client, h):
    """最小策略：来源 + 组 + 兜底规则 + 目标 + 设备。返回设备令牌。"""
    client.post("/api/v1/sources", headers=h, json={
        "name": "机场A", "url": "https://a.example.com/sub?token=x"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "节点选择", "type": "select", "proxies": ["DIRECT"]})
    client.post("/api/v1/groups", headers=h, json={
        "name": "地区自动", "type": "url-test", "hidden": True})
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "example.com", "target": "节点选择"})
    client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "DIRECT"})
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    r = client.post("/api/v1/devices", headers=h, json={
        "name": "iPhone", "platform": "ios", "target_id": 1})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _variant(client, h, name, copy_from=0, **kw):
    r = client.post("/api/v1/variants", headers=h,
                    json={"name": name, "copy_from": copy_from, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _build(client, h):
    r = client.post("/api/v1/builds", headers=h, json={})
    assert r.status_code == 201, r.text
    return r.json()


def test_system_variant_protected(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    variants = client.get("/api/v1/variants", headers=h).json()
    assert [v["name"] for v in variants] == ["默认"]
    assert variants[0]["id"] == 0 and variants[0]["is_system"]
    # 默认方案禁改名、禁停用、禁删除
    assert client.put("/api/v1/variants/0", headers=h,
                      json={"name": "别的"}).status_code == 400
    assert client.put("/api/v1/variants/0", headers=h,
                      json={"enabled": False}).status_code == 400
    assert client.delete("/api/v1/variants/0", headers=h).status_code == 400
    # 同名方案 409；非法字符 400
    assert client.post("/api/v1/variants", headers=h,
                       json={"name": "默认"}).status_code == 409
    assert client.post("/api/v1/variants", headers=h,
                       json={"name": "a/b"}).status_code == 400
    assert client.post("/api/v1/variants", headers=h,
                       json={"name": "含@符号"}).status_code == 400


def test_copy_variant_and_scope_filtering(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _policy(client, h)
    v = _variant(client, h, "自建美日", copy_from=0, use_sources_empty=True)
    assert v["id"] != 0

    items = client.get("/api/v1/groups?variant=0", headers=h).json() \
        + client.get("/api/v1/groups?variant=%d" % v["id"], headers=h).json()
    # 默认方案与复制方案同名共存：ids 不同、内容一致（use_sources 已清空）
    by_name = {}
    for g in items:
        by_name.setdefault(g["name"], []).append(g)
    assert all(len(rows) == 2 for rows in by_name.values())
    for g in items:
        if g["variant_id"] == v["id"]:
            assert g["use_sources"] == []

    # 列表按方案过滤
    only_default = client.get("/api/v1/groups/page?variant=0", headers=h).json()
    only_new = client.get("/api/v1/groups/page?variant=%d" % v["id"], headers=h).json()
    assert only_default["total"] == 2 and only_new["total"] == 2
    sorts = [g["sort"] for g in only_new["items"]]
    assert all(s >= 10000 for s in sorts), sorts

    # 同方案同名 409；跨方案同名允许（上面已验证）
    assert client.post("/api/v1/groups", headers=h, json={
        "name": "节点选择", "variant_id": v["id"],
        "type": "select", "proxies": ["DIRECT"],
    }).status_code == 409

    # 规则目标在方案内解析：跨方案引用被拒绝
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "x.com", "target": "节点选择",
        "variant_id": v["id"]})
    assert r.status_code == 201, r.text
    # 规则不能跨方案移动
    rid = r.json()["id"]
    assert client.put(f"/api/v1/rules/{rid}", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "x.com", "target": "节点选择",
        "variant_id": 0}).status_code == 400
    # 不存在的方案 400
    assert client.get("/api/v1/groups?variant=999", headers=h).status_code == 400


def _publish(client, h, bid):
    """构建发布到生产（生命周期要求先测试再生产）。"""
    client.post(f"/api/v1/builds/{bid}/publish-to-test", headers=h,
                json={"reason": ""})
    client.post(f"/api/v1/builds/{bid}/publish-to-prod", headers=h,
                json={"reason": ""})


def test_variant_build_and_feed(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    device_token = _policy(client, h)
    # 方案 B 只保留兜底（删掉 example.com 规则的副本），规则数应少一条
    v = _variant(client, h, "精简", copy_from=0)
    rules = [r for r in client.get("/api/v1/rules?variant=%d" % v["id"],
                                   headers=h).json()
             if r["type"] != "MATCH"]
    assert rules, "复制后应有非兜底规则"
    assert client.delete(f"/api/v1/rules/{rules[0]['id']}",
                         headers=h).status_code == 200

    build = _build(client, h)
    assert build["verify_status"] == "success", build["results"]
    keys = set(build["results"])
    # 没有设备专属内容时不出设备产物；方案产物与目标产物一一对应
    assert "stash-ios" in keys and "stash-ios@精简" in keys
    assert build["results"]["stash-ios"].get("variant", "") == ""
    assert build["results"]["stash-ios@精简"]["variant"] == "精简"

    art = client.get(f"/api/v1/builds/{build['id']}/artifact/stash-ios",
                     headers=h).json()["content"]
    art_b = client.get(f"/api/v1/builds/{build['id']}/artifact/stash-ios@精简",
                       headers=h).json()["content"]
    assert "example.com" in art
    assert "example.com" not in art_b
    assert "MATCH,DIRECT" in art_b

    # 下载：无参数 = 默认；?variant=精简 = 方案产物（要先发布）
    _publish(client, h, build["id"])
    token = device_token
    r = client.get(f"/feed/{token}/config.yaml")
    assert r.status_code == 200 and "example.com" in r.text
    r = client.get(f"/feed/{token}/config.yaml?variant=精简")
    assert r.status_code == 200 and "example.com" not in r.text
    # 预览与方案参数可组合
    r = client.get(f"/feed/{token}/config.yaml?variant=精简&preview=1")
    assert r.status_code == 200 and "example.com" not in r.text
    # 未知方案 404
    assert client.get(f"/feed/{token}/config.yaml?variant=不存在").status_code == 404


def test_variant_delete_guard_and_removal(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _policy(client, h)
    v = _variant(client, h, "临时", copy_from=0)
    build = _build(client, h)
    # 生效构建里有该方案 → 删除被拦（测试环境也算）
    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": ""})
    r = client.delete(f"/api/v1/variants/{v['id']}", headers=h)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "variant_in_use"
    assert any("stash-ios@临时" in x["artifact"] for x in detail["references"])

    # 换一个没构建过发布过的方案可以直接删，组与规则一并消失；
    # 再查它的列表会因方案不存在而 400
    v2 = _variant(client, h, "一次性", copy_from=0)
    assert client.delete(f"/api/v1/variants/{v2['id']}", headers=h).status_code == 200
    left = client.get("/api/v1/variants", headers=h).json()
    assert all(x["id"] != v2["id"] for x in left)
    assert client.get(f"/api/v1/groups?variant={v2['id']}",
                      headers=h).status_code == 400


def test_disabled_variant_excluded_from_new_build(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _policy(client, h)
    v = _variant(client, h, "停用我", copy_from=0)
    _build(client, h)
    assert client.put(f"/api/v1/variants/{v['id']}", headers=h,
                      json={"enabled": False}).status_code == 200
    build = _build(client, h)
    assert all("@停用我" not in k for k in build["results"])


def test_portal_lists_variants_per_device(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _policy(client, h)
    _variant(client, h, "自建美日", copy_from=0)
    _publish(client, h, _build(client, h)["id"])

    # 维护者已登录（setup_admin 的会话），门户数据免 PIN
    data = client.post("/api/v1/portal/data", json={"pin": ""}).json()
    assert [v["name"] for v in data["variants"]] == ["默认", "自建美日"]
    dev = next(d for d in data["devices"] if d["name"] == "iPhone")
    # 该设备按生产构建计算可用方案（两个方案的目标产物都在）
    assert dev["variants"] == ["默认", "自建美日"]


def test_deleting_group_in_one_variant_keeps_other_variants_rules(client):
    """回归：删方案里的组不能误删其它方案指向同名组的规则。

    2026-11-13 线上事故：refs.detach_group 漏传方案，删「自建美日」的
    港台组时把默认方案里指向同名组的 8 条规则一并删了。
    """
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _policy(client, h)
    # 默认方案加一条指向「节点选择」的规则；方案 1 复制后也有同名组与同目标规则
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "keepme.example", "target": "节点选择"})
    v = _variant(client, h, "副本", copy_from=0)
    gid = next(g["id"] for g in
               client.get("/api/v1/groups?variant=%d" % v["id"], headers=h).json()
               if g["name"] == "节点选择")
    # 组被副本里的规则引用，force 解绑删除（只应影响本方案）
    assert client.delete(f"/api/v1/groups/{gid}?force=1",
                         headers=h).status_code == 200
    # 默认方案的规则必须完好
    targets = [r["target"] for r in
               client.get("/api/v1/rules?variant=0", headers=h).json()]
    assert targets.count("节点选择") == 2
    # 副本里指向该组的规则已随组删除
    targets_v1 = [r["target"] for r in
                  client.get(f"/api/v1/rules?variant={v['id']}", headers=h).json()]
    assert "节点选择" not in targets_v1
