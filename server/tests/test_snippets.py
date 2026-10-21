"""功能模块：CRUD 校验与构建合并。"""
import yaml
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
    assert "dns" not in stash                # mihomo 专用片段不进 stash
    assert "fallback" not in stash.get("dns", {})

    mih = yaml.safe_load(client.get(
        f"/api/v1/builds/{bid}/artifact/mihomo-android").json()["content"])
    assert "panel" not in mih                # stash 专用片段不进 mihomo
    assert mih["dns"]["fallback"] == ["https://dns.google/dns-query"]
    assert mih["dns"]["enhanced-mode"] == "fake-ip"  # 与默认 dns 深度合并

    # 门户按分类返回启用模块的元信息（不含内容）
    client.post("/api/v1/portal/my-pin", headers=h, json={"pin": "1357"})
    data = client.post("/api/v1/portal/data", json={"pin": "1357"}).json()
    cats = {(s["name"], s["category"]) for s in data["snippets"]}
    assert ("首页面板", "panel") in cats and ("统一日志", "general") in cats
    assert all("content" not in s for s in data["snippets"])
    assert all(s["name"] != "停用模块" for s in data["snippets"])
