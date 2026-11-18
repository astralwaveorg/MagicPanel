"""解锁检测引擎：状态映射、Cloudflare 判别、地区标记、缓存合并。"""
import json

import pytest

from app.services import unlock_check as u


class _StubResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


class _StubClient:
    def __init__(self, responses):
        self.responses = responses

    def __get__(self, *a):  # 支持 with
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return self.responses[url]


def _patch(monkeypatch, responses):
    def fake_client(proxy):
        return _StubClient(responses)
    monkeypatch.setattr(u, "_client", fake_client)


def test_unlocked_and_region_extraction(monkeypatch):
    check = {"id": "yt", "url": "https://www.youtube.com/premium",
             "unlock": {200}, "region_regex": r'"countryCode":"(\w\w)"'}
    _patch(monkeypatch, {"https://www.youtube.com/premium":
                         _StubResp(200, '{"countryCode":"US"}')})
    r = u._run_single(check, None)
    assert r["state"] == "unlocked" and r["region"] == "US"


def test_cloudflare_challenge_is_error_not_blocked(monkeypatch):
    check = {"id": "cf", "url": "https://x.example/", "unlock": {200}}
    _patch(monkeypatch, {"https://x.example/": _StubResp(
        403, "Just a moment... challenge-platform verification")})
    r = u._run_single(check, None)
    assert r["state"] == "error"
    assert "Cloudflare" in r["detail"]


def test_region_marker_overrides_default_blocked(monkeypatch):
    check = {"id": "claude", "url": "https://claude.ai/", "unlock": {200},
             "region_marker": r"not available in your region"}
    _patch(monkeypatch, {"https://claude.ai/": _StubResp(
        403, "Claude is not available in your region.")})
    assert u._run_single(check, None)["state"] == "blocked"
    _patch(monkeypatch, {"https://claude.ai/": _StubResp(
        403, "Rate limited challenge")})
    r = u._run_single(check, None)
    assert r["state"] == "error"


def test_unsupported_only_when_declared(monkeypatch):
    check = {"id": "a", "url": "https://a.example/", "unlock": {200},
             "unsupported": {404}}
    _patch(monkeypatch, {"https://a.example/": _StubResp(404)})
    assert u._run_single(check, None)["state"] == "unsupported"
    check2 = {"id": "b", "url": "https://b.example/", "unlock": {200}}
    _patch(monkeypatch, {"https://b.example/": _StubResp(404)})
    assert u._run_single(check2, None)["state"] == "error"


def test_timeout_is_error(monkeypatch):
    class _Boom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            raise u.httpx.ConnectTimeout("boom")
    monkeypatch.setattr(u, "_client", lambda proxy: _Boom())
    check = {"id": "t", "url": "https://t.example/", "unlock": {200}}
    r = u._run_single(check, None)
    assert r["state"] == "error" and r["status"] is None


def test_cache_merge_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "_CACHE_PATH", tmp_path / "cache.json")
    full = {"checked_at": 1, "exit": "panel",
            "results": [{"id": "a", "state": "unlocked", "status": 200},
                        {"id": "b", "state": "blocked", "status": 403}]}
    u._save_cache("panel", full, merge=False)
    partial = {"checked_at": 2, "exit": "panel",
               "results": [{"id": "a", "state": "blocked", "status": 403}]}
    u._save_cache("panel", partial, merge=True)
    merged = u.last_results("panel")
    states = {r["id"]: r["state"] for r in merged["results"]}
    assert states == {"a": "blocked", "b": "blocked"}
    assert merged["checked_at"] == 2


def test_catalog_integrity():
    ids = [c["id"] for c in u.CHECKS]
    assert len(ids) == len(set(ids)), "检测 id 必须唯一"
    for c in u.CHECKS:
        assert c["category"] in u.CATEGORY_NAMES
        assert c["url"].startswith("https://")


def test_unlock_routes_registered(tmp_path, monkeypatch):
    """unlock 路由必须真正注册进 app（曾发生 import 了却没 include 的回归）。"""
    import os, sys
    monkeypatch.setenv("MAGICPANEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAGICPANEL_SCHEDULER", "0")
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]
    from app import config as mp_config, security as mp_security
    mp_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    mp_security.load_master_material(require_existing=False)  # 全新空目录：生成密钥文件
    from app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as tc:
        # 已注册且带鉴权的路径返回 401；未注册会 404
        # （新 FastAPI 把路由包进 _IncludedRouter，无法按 path 断言，用语义断言）
        assert tc.get("/api/v1/unlock/catalog").status_code == 401
        assert tc.get("/api/v1/unlock/last").status_code == 401
        assert tc.post("/api/v1/unlock/run").status_code == 401
        # 门户公开端点匿名可达
        assert tc.get("/api/v1/portal/unlock").status_code == 200


def test_capability_badges_multidimensional():
    """能力徽章多维：🔓 AI 全解锁 / 🎬 流媒体 / 📺 Netflix 高级版。

    2026-11-18：节点能力分类属于构建流程（检测 → 分类 → 重命名 → 产物），
    页面只做两网络环境的对照。
    """
    from app.services import unlock_check

    ai_ids = unlock_check.AI_CHECK_IDS
    stream_ids = unlock_check.STREAM_CORE_IDS
    assert "gemini" in ai_ids and "netflix" in stream_ids

    entry = {"checked_at": 1, "exit": "节点A", "results": [
        {"id": i, "state": "unlocked", "status": 200, "region": "",
         "latency_ms": 1, "detail": ""} for i in ai_ids + stream_ids
    ] + [{"id": "netflix_premium", "state": "unlocked", "status": 200, "region": "",
          "latency_ms": 1, "detail": ""}]}
    orig = unlock_check._load_all
    unlock_check._load_all = lambda: {"节点A": entry}
    try:
        badges = unlock_check.capability_badges("节点A")
        assert unlock_check.BADGE_AI in badges
        assert unlock_check.BADGE_STREAM in badges
        assert unlock_check.BADGE_NF_PREMIUM in badges
        assert unlock_check.ai_unlocked("节点A") is True
        # 明确区域拒绝 → 不给对应徽章
        entry["results"][0]["state"] = "blocked"
        badges2 = unlock_check.capability_badges("节点A")
        assert unlock_check.BADGE_AI not in badges2
        # 未测过的节点没有任何徽章
        assert unlock_check.capability_badges("从未测过") == ""
    finally:
        unlock_check._load_all = orig


def test_node_rename_accepts_multi_badge():
    """重命名支持多徽章串（🔓🎬），并兼容旧的布尔返回。"""
    from app.services import node_rename

    alloc = {}
    out = node_rename.normalize_name("美国01 Hyper", source="机场A", alloc=alloc,
                                     badge="🔓🎬")
    assert out == "🇺🇸 [机场A] 美国 🔓🎬 01"

    mapping = node_rename.rename_batch(["美国02 Hyper"], source="机场A",
                                       badge_lookup=lambda n: "🎬")
    assert mapping["美国02 Hyper"] == "🇺🇸 [机场A] 美国 🎬 01"

    # 旧的布尔语义：True → 单个 AI 徽章
    legacy = node_rename.rename_batch(["美国03 Hyper"], source="机场A",
                                       badge_lookup=lambda n: True)
    assert legacy["美国03 Hyper"] == "🇺🇸 [机场A] 美国 🔓 01"


def test_build_uses_capability_badges(client, monkeypatch):
    """构建期用多维能力徽章重命名（检测 → 分类 → 重命名 → 产物）。"""
    import base64
    import yaml
    from conftest import auth_headers, setup_admin
    from test_api import make_policy
    from app.services import unlock_check

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    snap_text = (
        "proxies:\n"
        "  - name: 'US 01'\n"
        "    type: ss\n    server: 192.0.2.10\n    port: 8388\n"
        "    cipher: aes-128-gcm\n    password: 'x'\n"
    )
    r = client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "原始机场",
        "content_b64": base64.b64encode(snap_text.encode()).decode(),
        "mode": "inline"})
    assert r.status_code == 201, r.text

    # 造缓存：AI 全解锁 + 流媒体全解锁 + Netflix 高级版
    results = [{"id": i, "state": "unlocked", "status": 200, "region": "",
                "latency_ms": 1, "detail": ""}
               for i in unlock_check.AI_CHECK_IDS + unlock_check.STREAM_CHECK_IDS]
    unlock_check._save_cache("US 01", {"checked_at": 1, "exit": "US 01",
                                      "results": results, "ip": {}}, merge=False)
    client.put("/api/v1/settings", headers=h, json={"values": {
        "node_name_unlock_badge": "1"}})

    build = client.post("/api/v1/builds", headers=h, json={}).json()
    # 节点可能在顶层 proxies（inline）或 provider 快照（provider 模式）：
    # 两种下发路径都要带上能力徽章
    found = False
    for name in build["results"]:
        content = client.get(
            f"/api/v1/builds/{build['id']}/artifact/{name}").json()["content"]
        if "🇺🇸 [原始机场] 美国 🔓🎬📺 01" in content:
            found = True
            break
    assert found, "产物里应出现带多维能力徽章的节点名"


def test_detectable_nodes_reads_source_snapshots(client):
    """候选节点要包含来源快照里的节点（机场节点才是主体）。

    2026-11-18 线上缺陷：快照密文解密后是文本，而 source_nodes.extract
    收 bytes → 抛 AttributeError 被 except 吞掉 → 候选节点只剩本地节点，
    补测与能力徽章覆盖不到机场节点。
    """
    import base64
    from app import db, security
    from app.services import unlock_check
    from conftest import auth_headers, setup_admin
    from test_api import make_policy

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    snap = (
        "proxies:\n"
        "  - name: '机场节点A'\n    type: ss\n    server: 192.0.2.11\n"
        "    port: 8388\n    cipher: aes-128-gcm\n    password: 'x'\n"
        "  - name: '机场节点B'\n    type: ss\n    server: 192.0.2.12\n"
        "    port: 8388\n    cipher: aes-128-gcm\n    password: 'x'\n"
    )
    with db.tx() as conn:
        conn.execute("UPDATE sources SET snapshot_enc=? WHERE name='测试机场'",
                     (security.encrypt_text(snap),))
    nodes = unlock_check.detectable_nodes()
    assert "机场节点A" in nodes, nodes[:5]
    assert "机场节点B" in nodes


def test_cloudflare_challenge_does_not_block_ai_badge(client):
    """人机校验（403 + Cloudflare）不算区域拒绝：确认解锁项过半仍给 🔓。

    2026-11-18 线上实测：Claude / Perplexity 对无头请求一律 403 + 人机校验，
    若要求"六项全部 unlocked"，🔓 永远不会出现。
    """
    from app.services import unlock_check

    states = {i: "unlocked" for i in unlock_check.AI_CHECK_IDS}
    states["claude"] = "error"        # 人机校验：无法判定
    states["perplexity"] = "error"
    entry = {"checked_at": 1, "exit": "节点B", "results": [
        {"id": i, "state": s, "status": 200 if s == "unlocked" else 403,
         "region": "", "latency_ms": 1, "detail": ""}
        for i, s in states.items()]}
    orig = unlock_check._load_all
    unlock_check._load_all = lambda: {"节点B": entry}
    try:
        assert unlock_check.ai_unlocked("节点B") is True
        # 其中一项明确被区域拒绝 → 不给
        states["gemini"] = "blocked"
        entry["results"][0]["state"] = "blocked"
        assert unlock_check.ai_unlocked("节点B") is False
    finally:
        unlock_check._load_all = orig
