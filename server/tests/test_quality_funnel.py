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
    probes["netflix_premium"] = {"state": "unlocked"}
    badges = quality_funnel.badges_from_probes(probes)
    assert "🔓" in badges and "🎬" in badges and "📺" in badges

    # AI 里有一项被区域拒绝 → 不给 AI 徽章，其它不受影响
    probes["gemini"] = {"state": "blocked"}
    badges2 = quality_funnel.badges_from_probes(probes)
    assert "🔓" not in badges2
    assert "🎬" in badges2


def test_region_from_probes_prefers_netflix():
    probes = {"netflix": {"region": "HK"}, "youtube_premium": {"region": "US"}}
    assert quality_funnel.region_from_probes(probes) == "HK"
    assert quality_funnel.region_from_probes({}) == ""


# ---------------------------------------------------------------- 命名摘要
def test_name_includes_speed_and_delay():
    alloc = {}
    out = normalize_name("美国01 Hyper", source="机场A", alloc=alloc,
                         speed_bps=12 * 1024 * 1024, delay_ms=45)
    assert out == "🇺🇸 [机场A] 美国 01 12M/45ms"


def test_name_without_perf_has_no_suffix():
    out = normalize_name("美国01 Hyper", source="机场A")
    assert out == "🇺🇸 [机场A] 美国 01"


def test_rename_batch_accepts_perf_lookup():
    mapping = rename_batch(["US 01"], source="机场A",
                            perf_lookup=lambda n: {"speed_bps": 3 * 1024 * 1024,
                                                   "delay_ms": 88})
    assert mapping["US 01"] == "🇺🇸 [机场A] 美国 01 3M/88ms"


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
    assert [p["name"] for p in groups["qualified"]] == ["节点A"]
    assert [p["name"] for p in groups["rejected"]] == ["节点B"]
    assert [p["name"] for p in groups["ai"]] == ["节点A"]
    assert [p["name"] for p in groups["stream"]] == ["节点A"]


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
