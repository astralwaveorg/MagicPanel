"""列表页条件筛选：策略组 / 规则来源 / 节点来源的分页接口。

界面上的筛选栏直接落到这几个查询参数上，这里逐个筛一遍，
确保「筛不出东西」和「筛出不该在的东西」都能被挡住。
"""
from tests.conftest import auth_headers, setup_admin


def _page(client, h, path, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v != "")
    resp = client.get(f"{path}?{qs}", headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _names(client, h, path, **params):
    body = _page(client, h, path, limit=200, **params)
    return {item["name"] for item in body["items"]}


def test_groups_page_filters(client):
    """策略组：类型、可见性、适用范围、成员构成。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 造两个来源与两个平台：只选其中一个时不会被归一成「包含所有」
    for name in ("机场A", "机场B"):
        client.post("/api/v1/sources", headers=h, json={
            "name": name, "url": f"https://{name}.example.com/sub"})
    for name, engine, platform in (("stash-ios", "stash", "ios"),
                                   ("mihomo-android", "mihomo", "android")):
        client.post("/api/v1/targets", headers=h, json={
            "name": name, "engine": engine, "platform": platform})
    node = client.post("/api/v1/local-nodes", headers=h, json={
        "name": "本地甲", "protocol": "http", "server": "1.2.3.4",
        "port": 80}).json()

    def group(name, **body):
        r = client.post("/api/v1/groups", headers=h,
                        json={"name": name, **body})
        assert r.status_code == 201, r.text
        return r.json()

    group("全局手动组", type="select")
    group("全局自动组", type="url-test")
    group("隐藏组", type="select", hidden=True)
    group("限定平台组", type="select", targets=["stash-ios"])
    group("含来源组", type="select", use_sources=["机场A"])
    group("含本地组", type="select", local_nodes=[node["id"]])

    path = "/api/v1/groups/page"
    everything = _page(client, h, path, limit=200)
    assert everything["total"] == 6
    assert everything["total_all"] == 6

    assert _names(client, h, path, gtype="url-test") == {"全局自动组"}
    assert _names(client, h, path, hidden="1") == {"隐藏组"}
    visible = _names(client, h, path, hidden="0")
    assert visible == {"全局手动组", "全局自动组", "限定平台组", "含来源组", "含本地组"}
    assert _names(client, h, path, scope="platform") == {"限定平台组"}
    assert _names(client, h, path, scope="global") == {
        "全局手动组", "全局自动组", "隐藏组", "含来源组", "含本地组"}
    # 「包含所有来源」不算真的指定了来源
    assert _names(client, h, path, member="source") == {"含来源组"}
    assert _names(client, h, path, member="local") == {"含本地组"}
    assert _names(client, h, path, member="manual") == {
        "全局手动组", "全局自动组", "隐藏组", "限定平台组"}
    assert _names(client, h, path, keyword="自动") == {"全局自动组"}


def test_rule_providers_page_filters(client):
    """规则来源：类型、行为、启用状态、抓取结果、被引用。"""
    from app import db

    csrf = setup_admin(client)
    h = auth_headers(csrf)

    def provider(name, **body):
        r = client.post("/api/v1/rule-providers", headers=h,
                        json={"name": name, **body})
        assert r.status_code == 201, r.text
        return r.json()

    provider("远程域名集", kind="remote", behavior="domain",
             url="https://x.example.com/a.yaml")
    provider("远程IP集", kind="remote", behavior="ipcidr",
             url="https://x.example.com/b.yaml")
    provider("远程未抓集", kind="remote", behavior="domain",
             url="https://x.example.com/c.yaml")
    inline = provider("内联集", kind="inline", behavior="domain",
                      inline_content="payload:\n  - a.example.com\n")
    client.patch(f"/api/v1/rule-providers/{inline['id']}/enabled", headers=h,
                 json={"enabled": False})
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "RULE-SET", "value": "远程域名集", "target": "DIRECT"})
    assert r.status_code == 201, r.text

    # 抓取结果直接写库：这里只验筛选口径，不去跑真实抓取
    with db.tx() as conn:
        conn.execute("UPDATE rule_providers SET last_status='ok' "
                     "WHERE name='远程域名集'")
        conn.execute("UPDATE rule_providers SET last_status='failed' "
                     "WHERE name='远程IP集'")

    path = "/api/v1/rule-providers/page"
    everything = _page(client, h, path, limit=200)
    assert everything["total"] == 4
    assert everything["total_all"] == 4

    assert _names(client, h, path, kind="remote") == {
        "远程域名集", "远程IP集", "远程未抓集"}
    assert _names(client, h, path, kind="inline") == {"内联集"}
    assert _names(client, h, path, behavior="ipcidr") == {"远程IP集"}
    assert _names(client, h, path, enabled="0") == {"内联集"}
    assert _names(client, h, path, enabled="1") == {
        "远程域名集", "远程IP集", "远程未抓集"}
    # 抓取结果只对远程来源有意义，内联来源不参与
    assert _names(client, h, path, status="ok") == {"远程域名集"}
    assert _names(client, h, path, status="failed") == {"远程IP集"}
    assert _names(client, h, path, status="none") == {"远程未抓集"}
    assert _names(client, h, path, referenced="1") == {"远程域名集"}
    assert _names(client, h, path, referenced="0") == {
        "远程IP集", "远程未抓集", "内联集"}
    # 关键词同时匹配名称与 URL
    assert _names(client, h, path, keyword="b.yaml") == {"远程IP集"}
    assert _names(client, h, path, keyword="内联") == {"内联集"}


def test_sources_page_filters(client):
    """节点来源：下发方式、启用状态、自动抓取、抓取结果。"""
    from app import db

    csrf = setup_admin(client)
    h = auth_headers(csrf)

    def source(name, **body):
        r = client.post("/api/v1/sources", headers=h, json={
            "name": name, "url": f"https://{name}.example.com/sub", **body})
        assert r.status_code == 201, r.text
        return r.json()

    a = source("订阅机场")
    source("内联机场", mode="inline")
    source("快照机场", auto_fetch=False)
    client.patch(f"/api/v1/sources/{a['id']}/enabled", headers=h,
                 json={"enabled": False})

    with db.tx() as conn:
        conn.execute("UPDATE sources SET last_status='ok' WHERE name='订阅机场'")
        conn.execute("UPDATE sources SET last_status='failed' WHERE name='内联机场'")

    path = "/api/v1/sources/page"
    everything = _page(client, h, path, limit=200)
    assert everything["total"] == 3
    assert everything["total_all"] == 3

    assert _names(client, h, path, mode="inline") == {"内联机场"}
    assert _names(client, h, path, mode="provider") == {"订阅机场", "快照机场"}
    assert _names(client, h, path, enabled="0") == {"订阅机场"}
    assert _names(client, h, path, enabled="1") == {"内联机场", "快照机场"}
    assert _names(client, h, path, auto_fetch="0") == {"快照机场"}
    assert _names(client, h, path, auto_fetch="1") == {"订阅机场", "内联机场"}
    assert _names(client, h, path, status="ok") == {"订阅机场"}
    assert _names(client, h, path, status="failed") == {"内联机场"}
    assert _names(client, h, path, status="none") == {"快照机场"}
    assert _names(client, h, path, keyword="机场") == {
        "订阅机场", "内联机场", "快照机场"}
