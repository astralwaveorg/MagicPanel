"""节点名称规范化：确定性、地区保留、占位丢弃、批内去重序号。"""
from app.services import node_rename


def test_info_nodes_are_dropped():
    for name in ("剩余流量：95.45 GB", "距离下次重置剩余：22 天", "套餐到期：2027-03-08",
                 "📢 大陆加速:shenlong66.com 官网", "Expire: 2027-01-01"):
        assert node_rename.normalize_name(name) is None, name


def test_region_detection_zh_en_flag():
    cases = {
        "🇺🇸 美国01 Hyper": ("🇺🇸", "美国"),
        "US Los Angeles x2": ("🇺🇸", "美国"),
        "🇯🇵 日本IPV6 移动": ("🇯🇵", "日本"),
        "Japan Tokyo IEPL": ("🇯🇵", "日本"),
        "🇭🇰 [Home] 香港 06": ("🇭🇰", "香港"),
        "新加坡 01": ("🇸🇬", "新加坡"),
        "SG-Lion-01": ("🇸🇬", "新加坡"),
        "韩国 [IEPL] | 5x": ("🇰🇷", "韩国"),
        "🇬🇧 London 2": ("🇬🇧", "英国"),
        "土耳其 [A]": ("🇹🇷", "土耳其"),
        "欧洲1": ("🌍", "欧洲"),
    }
    for name, want in cases.items():
        assert node_rename.detect_region(name) == want, name


def test_normalize_full_format():
    alloc = {}
    out = node_rename.normalize_name("🇺🇸 美国01 Hyper", source="神龙机场", alloc=alloc)
    assert out == "🇺🇸 [神龙机场] 美国 01"
    out2 = node_rename.normalize_name("US-LA 0.5x [A]", source="夜煞云", alloc=alloc)
    assert out2 == "🇺🇸 [0.5x·夜煞云] 美国 02"
    # 家宽进入地区名；IEPL 与运营商成为标签
    out3 = node_rename.normalize_name("日本家宽-01 Home", source="夜煞云", alloc=alloc)
    assert out3 == "🇯🇵 [夜煞云] 日本家宽 01"
    out4 = node_rename.normalize_name("韩国 [IEPL] | 5x 移动", source="夜煞云", alloc=alloc)
    assert out4 == "🇰🇷 [5x·IEPL·移动·夜煞云] 韩国 01"


def test_seq_alloc_is_deterministic_per_batch():
    names = ["🇭🇰 香港 01", "🇭🇰 香港 02", "HK/03", "🇭🇰 香港 01"]
    mapping = node_rename.rename_batch(names, source="夜煞云")
    assert mapping[names[0]] == "🇭🇰 [夜煞云] 香港 01"
    assert mapping[names[1]] == "🇭🇰 [夜煞云] 香港 02"
    assert mapping[names[2]] == "🇭🇰 [夜煞云] 香港 03"
    assert mapping[names[3]] == "🇭🇰 [夜煞云] 香港 01"
    # 同样的输入永远得到同样的输出（确定性）
    assert node_rename.rename_batch(names, source="夜煞云") == mapping


def test_unknown_region_keeps_name():
    assert node_rename.normalize_name("MyPrivate-Relay-01") == "MyPrivate-Relay-01"


def test_multiplier_normalization():
    assert node_rename._extract_multiplier("节点 2X") == "2x"
    assert node_rename._extract_multiplier("节点 0.5x") == "0.5x"
    assert node_rename._extract_multiplier("节点 5倍") == "5x"
    assert node_rename._extract_multiplier("节点 无倍率") is None


def test_snapshot_normalization_drops_info_and_renames():
    text = """
proxies:
  - name: "🇺🇸 美国01 Hyper"
    type: vless
    server: a
    port: 443
  - name: "剩余流量：100GB"
    type: ss
    server: 127.0.0.1
    port: 53
  - name: "US 02"
    type: ss
    server: b
    port: 443
"""
    out = node_rename.normalize_snapshot(text, source="神龙机场")
    import yaml
    data = yaml.safe_load(out)
    names = [p["name"] for p in data["proxies"]]
    assert names == ["🇺🇸 [神龙机场] 美国 01", "🇺🇸 [神龙机场] 美国 02"]


def test_settings_gate_controls_build_and_feed(client):
    """系统设置 node_name_normalize 是总开关（AGENTS.md 声明，此前零测试覆盖）。

    走真实 API 链：inline 来源 → 构建 → 产物，再验 feed 端 provider 下发。
    关闭时节点名保持来源原样；开启时统一规范化（本测试的来源节点不受
    「本地节点不动」豁免——那是另一类节点）。
    """
    import base64
    import yaml
    from conftest import auth_headers, setup_admin
    from test_api import make_policy

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    snap_text = (
        "proxies:\n"
        "  - name: '香港 IEPL 01'\n"
        "    type: ss\n    server: 192.0.2.10\n    port: 8388\n"
        "    cipher: aes-128-gcm\n    password: 'x'\n"
    )
    r = client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "原始机场",
        "content_b64": base64.b64encode(snap_text.encode()).decode(),
        "mode": "inline",
    })
    assert r.status_code == 201, r.text

    # 关闭开关：产物节点名原样
    client.put("/api/v1/settings", headers=h, json={"values": {"node_name_normalize": "0"}})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    content = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    cfg = yaml.safe_load(content)
    names = [p["name"] for p in cfg["proxies"]]
    assert "香港 IEPL 01" in names, names

    # 开启开关：重新构建，产物节点名规范化（带来源标签）
    client.put("/api/v1/settings", headers=h, json={"values": {"node_name_normalize": "1"}})
    build2 = client.post("/api/v1/builds", headers=h, json={}).json()
    content2 = client.get(
        f"/api/v1/builds/{build2['id']}/artifact/stash-ios").json()["content"]
    assert "香港 IEPL 01" not in content2, "开启后应规范化改名"
    assert "[IEPL·原始机场]" in content2, content2


def test_badge_position_and_gating():
    """新格式：国旗 [机场·标签] 国名 🔓 序号——徽章只在判定为真时加。"""
    from app.services import node_rename

    alloc = {}
    plain = node_rename.normalize_name("美国01 Hyper", source="神龙机场", alloc=alloc)
    assert plain == "🇺🇸 [神龙机场] 美国 01"
    badged = node_rename.normalize_name("美国02 Hyper", source="神龙机场",
                                        alloc=alloc, badge=True)
    assert badged == "🇺🇸 [神龙机场] 美国 🔓 02"
    assert node_rename.UNLOCK_BADGE == "🔓"

    # badge_lookup 只给判定为真的节点加徽章
    mapping = node_rename.rename_batch(
        ["美国01 Hyper", "美国02 Hyper"], source="神龙机场",
        badge_lookup=lambda n: n.endswith("02 Hyper"))
    assert mapping["美国01 Hyper"] == "🇺🇸 [神龙机场] 美国 01"
    assert mapping["美国02 Hyper"] == "🇺🇸 [神龙机场] 美国 🔓 02"


def test_ai_unlocked_requires_all_ai_checks():
    """AI 全解锁才给徽章：缺一项、有被拒、没测过都不算（保守不冒充）。"""
    from app.services import unlock_check

    results = [{"id": i, "state": "unlocked", "status": 200, "region": "",
                "latency_ms": 1, "detail": ""} for i in unlock_check.AI_CHECK_IDS]
    entry = {"checked_at": 1, "exit": "节点A", "results": results}
    monkey_cache = {"节点A": entry}
    orig = unlock_check._load_all
    unlock_check._load_all = lambda: monkey_cache
    try:
        assert unlock_check.ai_unlocked("节点A") is True
        # 有一项被拒 → 不给徽章
        results[0]["state"] = "blocked"
        assert unlock_check.ai_unlocked("节点A") is False
        # 没测过的节点 → 不给徽章
        assert unlock_check.ai_unlocked("从未测过") is False
    finally:
        unlock_check._load_all = orig


def test_batch_detect_api_and_settings_gate(client, monkeypatch):
    """批量检测 API：启动后台批、进度可查；徽章开关关闭时名字无徽章。"""
    import base64
    import yaml
    from conftest import auth_headers, setup_admin
    from test_api import make_policy

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)

    # 进度查询
    st = client.get("/api/v1/unlock/batch-status", headers=h).json()
    assert st["running"] is False

    # 批量检测：monkeypatch run_batch 立即完成（不真起测速核心）
    from app.services import unlock_check
    calls = []
    monkeypatch.setattr(unlock_check, "run_batch",
                        lambda qty=3, ids=None, operator="": calls.append(qty) or {
                            "ok": True, "done": 1, "unlocked": 0})
    r = client.post("/api/v1/unlock/batch-detect", headers=h,
                    json={"qty": 1, "ids": ["节点A"]})
    assert r.status_code == 200, r.text
    import time as _time
    for _ in range(20):
        if calls:
            break
        _time.sleep(0.1)
    assert calls == [1], "后台批应收到 qty=1"

    # 徽章开关默认关：inline 来源节点名无 🔓
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
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    content = client.get(
        f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    assert "🔓" not in content, "徽章开关关闭时产物不应有 🔓"
    assert "🇺🇸 [原始机场] 美国 01" in content, content

    # 打开徽章开关 + 该节点 AI 全解锁（写缓存）→ 重新构建带 🔓
    results = [{"id": i, "state": "unlocked", "status": 200, "region": "",
                "latency_ms": 1, "detail": ""} for i in unlock_check.AI_CHECK_IDS]
    unlock_check._save_cache("US 01",
                             {"checked_at": 1, "exit": "US 01",
                              "results": results, "ip": {}}, merge=False)
    client.put("/api/v1/settings", headers=h, json={"values": {
        "node_name_unlock_badge": "1"}})
    build2 = client.post("/api/v1/builds", headers=h, json={}).json()
    content2 = client.get(
        f"/api/v1/builds/{build2['id']}/artifact/stash-ios").json()["content"]
    assert "🇺🇸 [原始机场] 美国 🔓 01" in content2, content2
