"""解锁检测引擎：状态映射、Cloudflare 判别、地区标记、缓存合并。"""
import json


from app.services import unlock_check as u


def test_network_modes_share_service_verdicts_and_keep_portal_routes_private(tmp_path, monkeypatch):
    import httpx
    from app.services import scheduler
    from app.services import probe_engine
    from app.services.probes import base, route_evidence

    def reply(req):
        if req.url.host == "mail.google.com":
            return httpx.Response(301, headers={"location": "https://mail.google.com/mail/u/0/"})
        if req.url.host == "claude.ai":
            return httpx.Response(403, headers={"cf-mitigated": "challenge"}, text="Just a moment")
        raise AssertionError("不应跟随 Gmail 跳转")

    class IsolatedCore:
        controller_port = 32123

        def __init__(self, proxies):
            assert [item["name"] for item in proxies] == ["测线"]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def select(self, name):
            return name == "测线"

        def proxy_url(self):
            return "http://127.0.0.1:32124"

    monkeypatch.setattr(u, "_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(u, "exit_ip", lambda *args: {})
    monkeypatch.setattr(base, "make_client_factory", lambda *_: lambda timeout: httpx.Client(
        transport=httpx.MockTransport(reply), timeout=timeout))
    # 包导出的工厂和实际模块应使用同一个测试客户端。
    from app.services import probes
    monkeypatch.setattr(probes, "make_client_factory", base.make_client_factory)
    monkeypatch.setattr(probe_engine, "NodeEngine", IsolatedCore)
    monkeypatch.setattr(scheduler, "_collect_probe_proxies", lambda: [{"name": "测线"}])
    monkeypatch.setattr(route_evidence.ConnectionReader, "observe",
                        lambda self, _: ["测线", "mp-probe"] if self.isolated else ["现有线路"])

    ids = ["claude", "gmail_web"]
    private = u.run_panel_evidence(ids)
    node = u.run_checks("测线", ids)
    portal = u.run_checks("panel", ids)
    assert [{x["id"]: x["state"] for x in entry["results"]} for entry in (private, node, portal)] == [
        {"claude": "unknown", "gmail_web": "reachable"}] * 3
    assert private["results"][0]["extra"]["route"]["node"] == "现有线路"
    assert node["results"][0]["extra"]["route"] == {
        "node": "测线", "chain": ["测线", "mp-probe"], "domain": "claude.ai", "source": "probe_connection",
    }
    assert all("route" not in row["extra"] for row in portal["results"])
    assert u.last_results(u.PORTAL_EVIDENCE_CACHE) == portal


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
    assert out == "🇺🇸 [机] 美国 🔓🎬 01"

    mapping = node_rename.rename_batch(["美国02 Hyper"], source="机场A",
                                       badge_lookup=lambda n: "🎬")
    assert mapping["美国02 Hyper"] == "🇺🇸 [机] 美国 🎬 01"

    # 旧的布尔语义：True → 单个 AI 徽章
    legacy = node_rename.rename_batch(["美国03 Hyper"], source="机场A",
                                       badge_lookup=lambda n: True)
    assert legacy["美国03 Hyper"] == "🇺🇸 [机] 美国 🔓 01"


def test_regional_names_keep_badges_out_of_build_labels(client):
    """统一节点名不把性能和能力摘要写入基础节点名称。"""
    import base64
    import time
    from conftest import auth_headers, setup_admin
    from test_api import make_policy

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

    group = client.post("/api/v1/groups", headers=h, json={
        "name": "美区夹具", "use_sources": ["原始机场"], "proxies": ["DIRECT"],
    })
    assert group.status_code == 201, group.text

    from app import db, security
    from app.services import quality_funnel, scheduler
    with db.connect() as conn:
        cfg = quality_funnel._settings(conn)
    key = security.derive_subkey(security.load_master_material(), purpose="node-quality")
    node = scheduler._collect_probe_proxies()[0]
    quality_funnel.save_results([quality_funnel.NodeQuality(
        node["name"], stage="probed", badges="🔓🎬📺",
        checked_at=int(time.time()), revision=quality_funnel._fingerprint(node, key, cfg))])
    response = client.put("/api/v1/settings", headers=h, json={"values": {
        "node_name_unlock_badge": "1", "build_regional_node_names": "1"}})
    assert response.status_code == 200, response.text

    import yaml
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    found = False
    for name, result in build["results"].items():
        assert result["ok"], result["errors"]
        content = client.get(
            f"/api/v1/builds/{build['id']}/artifact/{name}").json()["content"]
        nodes = yaml.safe_load(content).get("proxies", [])
        if any(node.get("server") == "192.0.2.10" and node["name"] == "🇺🇸 [原] 美国" for node in nodes):
            found = True
        assert "🔓🎬📺" not in content
    assert found, "美区订阅节点使用简洁名称"


def test_detectable_nodes_reads_source_snapshots(client):
    """候选节点要包含来源快照里的节点（机场节点才是主体）。

    2026-11-18 线上缺陷：快照密文解密后是文本，而 source_nodes.extract
    收 bytes → 抛 AttributeError 被 except 吞掉 → 候选节点只剩本地节点，
    补测与能力徽章覆盖不到机场节点。
    """
    import base64
    from app import db, security
    from app.services import unlock_check, node_catalog, source_nodes
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
        sid = conn.execute("SELECT id FROM sources WHERE name='测试机场'").fetchone()[0]
        node_catalog.reconcile_source(conn, sid, source_nodes.extract(snap.encode()))
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


def test_map_emit_names_tolerates_duplicate_catalog_rows():
    """目录里同一原始名多条未退役记录时取 ordinal 最小，不再炸全部产物。

    2026-11-19 线上实证：夜煞云目录同一占位节点两条记录（ordinal 120/218），
    map_emit_names 抛 reference_ambiguous → 全部产物渲染失败 → 生产发布被卡。
    """
    from app.services import source_nodes

    catalog = [
        {"source_id": 9, "raw_name": "占位节点", "emit_name": "占位-120",
         "ordinal": 120, "retired": False},
        {"source_id": 9, "raw_name": "占位节点", "emit_name": "占位-218",
         "ordinal": 218, "retired": False},
        {"source_id": 9, "raw_name": "正常节点", "emit_name": "正常",
         "ordinal": 130, "retired": False},
    ]
    out = source_nodes.map_emit_names(
        [{"name": "占位节点"}, {"name": "正常节点"}],
        source_id=9, catalog=catalog)
    assert out[0]["name"] == "占位-120"
    assert out[1]["name"] == "正常"


def test_map_emit_names_still_rejects_missing():
    """原始名在目录里不存在仍然要报错（不能静默放行）。"""
    from app.services import source_nodes
    import pytest

    catalog = [{"source_id": 9, "raw_name": "别的", "emit_name": "x",
                "ordinal": 1, "retired": False}]
    with pytest.raises(ValueError, match="catalog_material_invalid"):
        source_nodes.map_emit_names([{"name": "不存在"}], source_id=9, catalog=catalog)


def test_full_node_updates_keep_other_cached_exits(tmp_path, monkeypatch):
    from app.services import unlock_check

    monkeypatch.setattr(unlock_check, "_CACHE_PATH", tmp_path / "cache.json")
    entry = {"results": [{"id": "netflix", "state": "unlocked"}]}
    unlock_check._save_cache("panel", entry, merge=False)
    unlock_check._save_cache_entries({"A": entry, "B": entry}, merge=False)
    unlock_check._save_cache("C", entry, merge=False)
    assert set(unlock_check._load_all()) == {"panel", "A", "B", "C"}
