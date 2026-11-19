"""节点质量漏斗与分类输出的回归测试（2026-11-19）。

漏斗的三级门禁与分类输出是「检测 → 分类 → 重命名 → 产物」的中枢，
这里用假数据验证判定逻辑，不发真实网络请求。
"""
import pytest

from app.services import node_classes, quality_funnel
from app.services.node_rename import normalize_name, rename_batch


# ---------------------------------------------------------------- 门禁判定
def test_dimension_ok_requires_no_rejection_and_enough_confirmed():
    """维度判定：无明确拒绝 + 确认解锁过半（人机校验不算拒绝）。"""
    from app.services import unlock_check
    ok = unlock_check._dimension_ok
    ids = ["a", "b", "c", "d"]
    # 四项全解锁 → 通过
    assert ok({"a": "unlocked", "b": "unlocked", "c": "unlocked", "d": "unlocked"},
              ids, 4) is True
    # 三项解锁 + 一项人机校验（unknown）：确认项不足 → 不通过
    assert ok({"a": "unlocked", "b": "unlocked", "c": "unlocked", "d": "unknown"},
              ids, 4) is False
    # 下限放宽到 3 → 通过
    assert ok({"a": "unlocked", "b": "unlocked", "c": "unlocked", "d": "unknown"},
              ids, 3) is True
    # 有一项明确区域拒绝 → 不通过
    assert ok({"a": "unlocked", "b": "unlocked", "c": "unlocked", "d": "blocked"},
              ids, 3) is False


def test_badges_from_probes():
    """由探测结果算徽章：AI / 流媒体 / Netflix 高级版。"""
    from app.services import unlock_check

    probes = {}
    for pid in unlock_check.AI_CHECK_IDS:
        probes[pid] = {"state": "unlocked"}
    for pid in unlock_check.STREAM_CORE_IDS:
        probes[pid] = {"state": "unlocked"}
    probes["netflix"] = {"state": "unlocked", "extra": {"licensed_sample": True}}
    badges = quality_funnel.badges_from_probes(probes)
    assert "🔓" in badges and "🎬" in badges and "📺" in badges

    # AI 里有一项被区域拒绝 → 不给 AI 徽章，其它不受影响
    probes["gemini"] = {"state": "blocked"}
    badges2 = quality_funnel.badges_from_probes(probes)
    assert "🔓" not in badges2
    assert "🎬" in badges2


def test_temporary_service_failure_does_not_refresh_or_erase_unexpired_proof(tmp_path, monkeypatch):
    from app.services import quality_funnel as q, routing_planner as r

    monkeypatch.setattr(q, "RESULT_PATH", tmp_path / "quality.json")
    success = {"state": "unlocked", "status": 200, "region": "JP",
               "extra": {"catalog": "licensed_sample"}}
    challenge = {"state": "unknown", "status": 403, "extra": {"reason": "challenge"}}
    def save(when, probe, revision="r1", stage="probed"):
        q.save_results([q.NodeQuality("JP", delay_ms=100, checked_at=when, revision=revision,
                                      stage=stage, probes={"netflix": probe})], keep_seconds=100)
        return q.load_results()["nodes"]["JP"]

    save(100, success)
    row = save(175, challenge)
    assert row["probes"]["netflix"] == challenge
    proof = r.service_proofs(row, earliest=80, latest=180)["netflix"]
    assert proof["checked_at"] == 100 and proof["result"] == success
    assert r.service_candidates([row], "netflix", earliest=80, latest=180) == [row]
    row = save(199, challenge)
    assert not r.verified_service_ids(row, earliest=101, latest=201)
    blocked = {"state": "blocked", "status": 403, "extra": {"reason": "region"}}
    assert "retained_proofs" not in save(200, blocked)
    save(250, success)
    assert "retained_proofs" not in save(260, challenge, revision="r2")
    save(270, success)
    assert "retained_proofs" not in save(280, challenge, stage="speed_failed")


def test_region_from_probes_prefers_netflix():
    probes = {"netflix": {"region": "HK"}, "youtube_premium": {"region": "US"}}
    assert quality_funnel.region_from_probes(probes) == "HK"
    assert quality_funnel.region_from_probes({}) == ""


# ---------------------------------------------------------------- 命名摘要
def test_name_includes_speed_and_delay():
    alloc = {}
    out = normalize_name("美国01 Hyper", source="机场A", alloc=alloc,
                         speed_bps=12 * 1024 * 1024, delay_ms=45)
    assert out == "🇺🇸 [机] 美国 01 12M/45ms"


def test_name_without_perf_has_no_suffix():
    out = normalize_name("美国01 Hyper", source="机场A")
    assert out == "🇺🇸 [机] 美国 01"


def test_rename_batch_accepts_perf_lookup():
    mapping = rename_batch(["US 01"], source="机场A",
                            perf_lookup=lambda n: {"speed_bps": 3 * 1024 * 1024,
                                                   "delay_ms": 88})
    assert mapping["US 01"] == "🇺🇸 [机] 美国 01 3M/88ms"


# ---------------------------------------------------------------- 分类输出
def _proxy(name: str) -> dict:
    return {"name": name, "type": "ss", "server": "192.0.2.1", "port": 8388,
            "cipher": "aes-128-gcm", "password": "x"}


def test_classify_splits_qualified_and_rejected():
    results = {
        "节点A": {"stage": "probed", "delay_ms": 50, "speed_bps": 10 << 20,
                  "badges": "🔓🎬", "region": "US"},
        "节点B": {"stage": "speed_failed", "delay_ms": 100,
                  "speed_bps": 1 << 20, "badges": "", "region": ""},
    }
    groups = node_classes.classify(results, {"节点A": _proxy("节点A"),
                                             "节点B": _proxy("节点B")})
    assert [p["name"] for p in groups["qualified"]] == ["节点A 10.5 MB/s / 50 ms"]
    assert [p["name"] for p in groups["rejected"]] == ["节点B 1.0 MB/s / 100 ms"]
    assert groups["ai"] == groups["stream"] == groups["qualified"]


def test_write_yaml_is_atomic_and_validates(tmp_path):
    path = tmp_path / "qualified.yaml"
    node_classes.write_yaml(path, [_proxy("节点A")], header="test")
    text = path.read_text(encoding="utf-8")
    assert "proxies:" in text
    assert not (tmp_path / "qualified.yaml.tmp").exists()


def test_write_yaml_rejects_bad_nodes_and_keeps_old_file(tmp_path):
    path = tmp_path / "qualified.yaml"
    node_classes.write_yaml(path, [_proxy("节点A")])
    before = path.read_text(encoding="utf-8")
    # 缺 server → 校验失败，旧文件必须保持原样
    with pytest.raises(node_classes.ClassifyError):
        node_classes.write_yaml(path, [{"name": "坏节点", "type": "ss",
                                        "port": 8388}])
    assert path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "qualified.yaml.tmp").exists()


def test_write_yaml_rejects_duplicate_names(tmp_path):
    path = tmp_path / "d.yaml"
    with pytest.raises(node_classes.ClassifyError):
        node_classes.write_yaml(path, [_proxy("同名"), _proxy("同名")])


def test_safe_name_strips_illegal_chars_and_dedupes():
    used: set[str] = set()
    first = node_classes._safe_name("香港,节点 #1", used)
    assert "," not in first and "#" not in first
    second = node_classes._safe_name("香港,节点 #1", used)
    assert second != first and second.endswith("-02")


def test_batch_selects_uncached_nodes_before_applying_limit(client, monkeypatch):
    import time
    from app.services import quality_funnel

    now = int(time.time())
    from app import db, security
    with db.connect() as conn:
        cfg = quality_funnel._settings(conn)
    key = security.derive_subkey(security.load_master_material(), purpose="node-quality")
    names = [f"完成{i}" for i in range(10)] + ["刚失败"]
    previous = {name: {"stage": "probed" if name != "刚失败" else "speed_failed",
                       "checked_at": now, "revision": quality_funnel._fingerprint(_proxy(name), key, cfg)}
                for name in names}
    monkeypatch.setattr(quality_funnel, "load_results", lambda: {"nodes": previous})
    saved = []
    monkeypatch.setattr(quality_funnel, "save_results",
                        lambda results, operator, **kwargs: saved.extend(r.name for r in results))

    class Engine:
        def __init__(self, proxies):
            assert [p["name"] for p in proxies] == ["未测"]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def delay_of(self, *args, **kwargs):
            return -1

    monkeypatch.setattr(quality_funnel.probe_engine, "NodeEngine", Engine)
    quality_funnel.run_funnel([*(_proxy(n) for n in previous),
                               {**_proxy("下批"), "source_id": 1}, _proxy("未测")], max_nodes=1)
    assert saved == ["未测"]
    assert "完成0" in quality_funnel.current_results([_proxy("完成0")])
    changed = {**_proxy("完成0"), "port": 9443}
    assert not quality_funnel.current_results([changed])
    previous["完成0"]["checked_at"] -= 48 * 3600
    assert not quality_funnel.current_results([_proxy("完成0")])


def test_engine_start_failure_removes_workdir(tmp_path, monkeypatch):
    import subprocess
    from app.services.probe_engine import EngineError, NodeEngine

    engine = NodeEngine([_proxy("节点")])
    engine.workdir = tmp_path / "leaked"
    engine.workdir.mkdir()

    class Process:
        killed = False
        reaped = False

        def terminate(self):
            pass

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("mihomo", timeout)
            self.reaped = True

        def kill(self):
            self.killed = True

    process = engine.proc = Process()

    def fail_start():
        raise EngineError("探测核心启动超时")

    monkeypatch.setattr(engine, "start", fail_start)
    with pytest.raises(EngineError):
        with engine:
            pytest.fail("核心未启动")
    assert process.reaped
    assert not (tmp_path / "leaked").exists()


def test_download_speed_uses_selected_proxy(monkeypatch):
    import httpx
    from app.services import probe_engine

    engine = probe_engine.NodeEngine([_proxy("节点")])
    engine.controller = object()
    engine._current = "节点"

    def factory(**kwargs):
        assert kwargs == {"trust_env": False, "proxy": engine.proxy_url()}
        return original_client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=httpx.ByteStream(b"12345678"))))

    original_client = httpx.Client
    monkeypatch.setattr(probe_engine.httpx, "Client", factory)
    ticks = iter((10.0, 11.0, 11.5, 12.0))
    with monkeypatch.context() as ctx:
        ctx.setattr(probe_engine, "time", type("Clock", (), {"monotonic": staticmethod(lambda: next(ticks))}))
        sample = engine.download_speed("节点", "https://example.test/", size_bytes=8)
    assert (sample.speed_bps, sample.received_bytes, sample.response_ms) == (8, 8, 1_000)
    short = engine.download_speed("节点", "https://example.test/", size_bytes=9)
    assert (short.speed_bps, short.received_bytes, short.error) == (0, 8, "short_body")
    assert engine.download_speed("另一节点", "https://example.test/", size_bytes=4).error == "wrong_node"


def test_export_only_replaces_verified_pool(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setattr(node_classes, "OUTPUT_DIR", tmp_path)
    candidates = [_proxy("甲"), _proxy("乙"), _proxy("丙")]
    results = {"甲": {"stage": "probed", "delay_ms": 100, "speed_bps": 2_000_000,
                     "region": "JP", "probes": {"netflix": {"state": "unlocked"}}},
               "乙": {"stage": "speed_failed"}, "丙": {"stage": "inconclusive"}}

    def validate(text):
        doc = yaml.safe_load(text)
        assert [p["name"] for p in doc["proxies"]] == ["甲 JP"]
        assert all(g["proxies"] == ["甲 JP"] for g in doc["proxy-groups"])
        return True, ""

    text = node_classes.export_pools(results, candidates, validate, template="{original} {region}")
    path = tmp_path / "node-pools.yaml"
    assert path.read_text() == text
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(node_classes.ClassifyError):
        node_classes.export_pools(results, candidates, lambda text: (True, "校验失败"))
    assert path.read_text() == text
    assert list(tmp_path.iterdir()) == [path]
    assert not node_classes.valid_name_template("{name.__class__}")
