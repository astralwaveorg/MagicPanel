"""拓展模块：CRUD 校验与构建合并。"""
import yaml
from app.services import base_config
from conftest import auth_headers, setup_admin
from test_api import make_policy


def test_snippet_crud_validation(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)

    # 内容必须是 YAML 映射
    r = client.post("/api/v1/snippets", headers=h, json={
        "name": "坏模块", "content": "- 只是列表"})
    assert r.status_code == 400
    r = client.post("/api/v1/snippets", headers=h, json={
        "name": "坏语法", "content": "a: [1,2"})
    assert r.status_code == 400

    r = client.post("/api/v1/snippets", headers=h, json={
        "name": "首页面板", "category": "panel", "engine": "stash",
        "content": "panel:\n  首页:\n    title: 家庭网络\n",
        "note": "Stash 首页展示"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post("/api/v1/snippets", headers=h, json={
        "name": "首页面板", "content": "a: 1"}).status_code == 409

    r = client.put(f"/api/v1/snippets/{sid}", headers=h, json={
        "name": "首页面板", "category": "panel", "engine": "all",
        "content": "panel:\n  首页:\n    title: 家庭网络 v2\n"})
    assert r.status_code == 200 and r.json()["engine"] == "all"
    assert client.delete(f"/api/v1/snippets/{sid}", headers=h).status_code == 200
    assert client.get("/api/v1/snippets", headers=h).json() == []


def test_snippet_paged_list(client):
    """分页列表要能正常返回（曾经缺 _public，整页 500）。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/snippets", headers=h, json={
        "name": "首页面板", "category": "panel", "engine": "stash",
        "content": "tiles:\n  - name: t1\n    title: '示例'\n"})

    r = client.get("/api/v1/snippets/page?limit=50&offset=0", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "首页面板"
    assert data["items"][0]["enabled"] is True


def test_snippet_remote_source(client, monkeypatch):
    """远程拓展模块：来源类型、内联/远程互斥、抓取失败保留旧内容。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)

    # 远程来源必须填 URL；内联来源不需要
    r = client.post("/api/v1/snippets", headers=h, json={
        "name": "远程片段", "source": "remote", "content": "log-level: info"})
    assert r.status_code == 400
    assert "URL" in r.json()["detail"]

    # 内联来源必须有内容
    r = client.post("/api/v1/snippets", headers=h, json={
        "name": "空内联", "source": "inline", "content": ""})
    assert r.status_code == 400

    # 来源类型只能是 inline / remote
    r = client.post("/api/v1/snippets", headers=h, json={
        "name": "坏来源", "source": "repo", "content": "a: 1"})
    assert r.status_code == 400

    # 远程来源允许先不带内容（内容由抓取填充）
    r = client.post("/api/v1/snippets", headers=h, json={
        "name": "远程片段", "source": "remote",
        "url": "https://example.com/frag.yaml", "format": "yaml",
        "interval": 3600, "client_interval": 0})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["source"] == "remote"
    assert r.json()["interval"] == 3600
    # 抓取代理不回显明文
    assert r.json()["proxy_url_masked"] == ""

    # 远程来源抓取失败：记状态、保留上一次可用内容
    r = client.post(f"/api/v1/snippets/{sid}/refresh", headers=h)
    assert r.status_code == 502, r.text
    assert "保留" in r.json()["detail"]
    row = client.get("/api/v1/snippets", headers=h).json()[0]
    assert row["last_status"] == "failed"
    assert row["last_error"]

    # 内联来源不能抓取
    inline = client.post("/api/v1/snippets", headers=h, json={
        "name": "内联片段", "content": "log-level: info"}).json()
    r = client.post(f"/api/v1/snippets/{inline['id']}/refresh", headers=h)
    assert r.status_code == 400

    # 抓取成功：内容进缓存，并进入产物
    monkeypatch.setattr("app.services.fetcher.fetch",
                        lambda *a, **k: b"log-level: debug\n")
    r = client.post(f"/api/v1/snippets/{sid}/refresh", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["last_status"] == "ok"
    assert "log-level: debug" in r.json()["content"]

    make_policy(client, csrf)
    # 内联片段与远程片段写同一个键，后合并的覆盖前面的；删掉内联的再验证产物
    assert client.delete(f"/api/v1/snippets/{inline['id']}", headers=h).status_code == 200
    build = client.post("/api/v1/builds", headers=h, json={})
    assert build.status_code == 201, build.text
    bid = build.json()["id"]
    stash = yaml.safe_load(client.get(
        f"/api/v1/builds/{bid}/artifact/stash-ios").json()["content"])
    assert stash["log-level"] == "debug"


def test_snippet_merge_into_build(client):
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    # Stash 专用面板 + 全引擎通用片段 + Mihomo 专用 DNS 追加
    client.post("/api/v1/snippets", headers=h, json={
        "name": "首页面板", "category": "panel", "engine": "stash",
        "content": "panel:\n  首页:\n    title: 家庭网络\n"})
    client.post("/api/v1/snippets", headers=h, json={
        "name": "统一日志", "category": "general", "engine": "all",
        "content": "log-level: info"})
    client.post("/api/v1/snippets", headers=h, json={
        "name": "备用 DNS", "category": "dns", "engine": "mihomo",
        "content": "dns:\n  fallback: [https://dns.google/dns-query]"})
    # 停用的模块不参与构建
    client.post("/api/v1/snippets", headers=h, json={
        "name": "停用模块", "engine": "all", "enabled": False,
        "content": "log-level: debug"})

    build = client.post("/api/v1/builds", headers=h, json={})
    assert build.status_code == 201, build.text
    assert build.json()["verify_status"] == "success"
    assert build.json()["status"] == "BUILT"
    bid = build.json()["id"]

    stash = yaml.safe_load(client.get(
        f"/api/v1/builds/{bid}/artifact/stash-ios").json()["content"])
    assert stash["panel"]["首页"]["title"] == "家庭网络"
    assert stash["log-level"] == "info"      # 启用模块覆盖默认值
    # mihomo 专用片段不进 stash；DNS 基线 2026-10-27 起不再带 fallback，
    # 片段写的键也不得漏进 stash 产物
    assert "fallback" not in stash["dns"]
    assert stash["dns"]["nameserver"] == base_config.default_doc("stash")["dns"]["nameserver"]

    mih = yaml.safe_load(client.get(
        f"/api/v1/builds/{bid}/artifact/mihomo-android").json()["content"])
    assert "panel" not in mih                # stash 专用片段不进 mihomo
    # 片段里的列表是「追加」语义（_merge：列表相加），不是替换；
    # 基线没有 fallback 时，追加结果就是片段自己那份
    assert mih["dns"]["fallback"] == ["https://dns.google/dns-query"]
    assert mih["dns"]["enhanced-mode"] == "fake-ip"  # 与默认 dns 深度合并

    # 门户按分类返回启用模块的元信息（不含内容）
    client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "1357"})
    data = client.post("/api/v1/portal/data", json={"pin": "1357"}).json()
    cats = {(s["name"], s["category"]) for s in data["snippets"]}
    assert ("首页面板", "panel") in cats and ("统一日志", "general") in cats
    assert all("content" not in s for s in data["snippets"])
    assert all(s["name"] != "停用模块" for s in data["snippets"])
