"""规则顺序：兜底规则永远在最后，新规则不能排到它后面。

客户端是"从上往下第一条命中即生效"，撞到兜底（MATCH/FINAL）就结束了，
排在其后的规则永远匹配不到。这组用例盯住这条约束的三处落点：
新增规则时的插入位、重复兜底、拖拽排序，以及产物里的兜底归位与告警。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from conftest import setup_admin, auth_headers  # noqa: E402


def make_group(client, csrf, name="节点选择"):
    h = auth_headers(csrf)
    r = client.post("/api/v1/groups", headers=h, json={
        "name": name, "type": "select", "proxies": ["DIRECT"], "use_sources": [],
    })
    assert r.status_code == 201, r.text


def rule_rows(client, csrf):
    h = auth_headers(csrf)
    resp = client.get("/api/v1/rules", headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_new_rule_inserted_before_fallback(client):
    """新增规则必须插在兜底规则之前，不能追加到末尾。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_group(client, csrf)
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT"})
    assert r.status_code == 201, r.text

    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "linux.do", "target": "节点选择"})
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    rows = rule_rows(client, csrf)
    types = [x["type"] for x in rows]
    # 兜底规则必须在最后
    assert types[-1] == "MATCH"
    assert [i for i, t in enumerate(types) if t == "MATCH"] == [len(types) - 1]
    # 新规则排在兜底之前
    idx = next(i for i, x in enumerate(rows) if x["id"] == new_id)
    assert idx < len(rows) - 1


def test_new_rule_keeps_relative_order_and_unique_sort(client):
    """插入新规则不改动其它规则的顺序，排序键不重复。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_group(client, csrf)
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "a.example.com", "target": "DIRECT"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "b.example.com", "target": "DIRECT"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT"})
    before = [x["value"] for x in rule_rows(client, csrf)]

    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "c.example.com", "target": "DIRECT"})

    rows = rule_rows(client, csrf)
    after = [x["value"] for x in rows]
    assert after == ["a.example.com", "b.example.com", "c.example.com", ""]
    assert before[:2] == after[:2]
    sorts = [x["sort"] for x in rows]
    assert len(sorts) == len(set(sorts))


def test_second_fallback_appended_at_end(client):
    """再加一条兜底规则：追加到末尾，客户端认的仍是第一条。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_group(client, csrf)
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT"})
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "节点选择"})
    assert r.status_code == 201, r.text

    rows = rule_rows(client, csrf)
    # 两条兜底都在末尾，第一条仍是客户端认的那条
    assert [x["type"] for x in rows][-2:] == ["MATCH", "MATCH"]
    assert rows[-2]["target"] == "DIRECT"


def test_reorder_keeps_fallback_last(client):
    """拖拽排序也不能把规则排到兜底后面。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_group(client, csrf)
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "a.example.com", "target": "DIRECT"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "b.example.com", "target": "DIRECT"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT"})

    rows = rule_rows(client, csrf)
    ids = [x["id"] for x in rows]
    # 把兜底拖到中间、普通规则拖到最后
    resp = client.post("/api/v1/rules/reorder", headers=h, json=ids)
    assert resp.status_code == 200, resp.text

    after = rule_rows(client, csrf)
    assert after[-1]["type"] == "MATCH"
    assert [x["value"] for x in after[:-1]] == ["a.example.com", "b.example.com"]


def test_artifact_moves_fallback_to_end_and_warns(client):
    """兜底之后遗留的规则，在产物里被挪到兜底前，并给出告警。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_group(client, csrf)
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "a.example.com", "target": "节点选择"})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT"})
    r = client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    assert r.status_code == 201, r.text

    # 历史脏数据：规则被追加到兜底之后（老版本新增规则是追加到末尾）
    from app import db as appdb
    with appdb.connect() as conn:
        conn.execute("UPDATE rules SET sort = -1 WHERE type = 'MATCH'")

    r = client.post("/api/v1/builds", headers=h, json={})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    detail = client.get(f"/api/v1/builds/{bid}", headers=h).json()
    warnings = []
    for res in detail["results"].values():
        warnings += res.get("warnings") or []
    assert any("现已生效" in w for w in warnings), warnings

    artifact = client.get(
        f"/api/v1/builds/{bid}/artifact/stash-ios", headers=h).json()["content"]
    lines = [x.strip() for x in artifact.splitlines() if x.strip().startswith("- ")]
    assert lines[-1].startswith("- MATCH,")
    assert any("a.example.com" in x for x in lines[:-1])
