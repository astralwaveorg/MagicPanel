"""节点质量漏斗：延迟 → 吞吐 → 解锁矩阵。

设计（2026-11-19 审计）：
* **一级·连通与延迟**：Mihomo delay API。延迟 ≥ 阈值或不可达 → 直接淘汰。
* **二级·下载吞吐**：只对一级达标的节点测速，平均速度 < 阈值 → 归入备用池
  （不参与解锁探测，省时间也降低目标站点风控压力）。
* **三级·解锁矩阵**：只对一二级都达标的节点跑平台探测，产出结构化能力标签。

所有阈值、并发、超时、重试都是配置项（settings 表），代码里只放默认值。
"""
import json
import logging
import time
from dataclasses import dataclass, field

from .. import config, db
from . import probe_engine

logger = logging.getLogger("magicpanel.quality_funnel")

# ---- 默认阈值（可被 settings 覆盖）----
DEFAULT_MAX_DELAY_MS = 600          # 一级：延迟上限
DEFAULT_MIN_SPEED_BPS = 2 * 1024 * 1024   # 二级：2 MB/s
DEFAULT_SPEED_TEST_BYTES = 5 * 1024 * 1024  # 测速文件大小
DEFAULT_SPEED_TEST_URL = "https://speed.cloudflare.com/__down?bytes=5242880"
DEFAULT_PROBE_TIMEOUT = 8.0         # 单请求超时
DEFAULT_PROBE_CONCURRENCY = 4       # 探测并发
DEFAULT_ROUND_LIMIT = 200           # 单轮最多探测多少节点
DEFAULT_PROBE_RETRY = 1

# 结果落盘位置
RESULT_PATH = config.DATA_DIR / "node_quality.json"
FAILED_RECHECK_SECONDS = 6 * 3600


@dataclass
class NodeQuality:
    """一个节点的质量结论（漏斗三级 + 能力标签）。"""
    name: str
    delay_ms: int = -1
    speed_bps: float = 0.0
    stage: str = "unknown"          # unknown / latency_failed / speed_failed / probed
    probes: dict = field(default_factory=dict)     # {平台id: ProbeResult.to_dict()}
    badges: str = ""                # 能力徽章串（🔓🎬📺）
    region: str = ""                # 识别出的地区码
    checked_at: int = 0

    @property
    def qualified(self) -> bool:
        """是否进入主可用池（一级 + 二级都达标）。"""
        return self.stage in ("probed",) or (
            self.delay_ms >= 0 and self.delay_ms < DEFAULT_MAX_DELAY_MS
            and self.speed_bps >= DEFAULT_MIN_SPEED_BPS)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "delay_ms": self.delay_ms,
            "speed_bps": round(self.speed_bps), "stage": self.stage,
            "probes": self.probes, "badges": self.badges, "region": self.region,
            "checked_at": self.checked_at,
        }


def _settings(conn) -> dict:
    def num(key: str, default: int) -> int:
        try:
            return int(db.get_setting(conn, key, str(default)) or default)
        except (TypeError, ValueError):
            return default
    return {
        "max_delay_ms": num("probe_max_delay_ms", DEFAULT_MAX_DELAY_MS),
        "min_speed_bps": num("probe_min_speed_bps", DEFAULT_MIN_SPEED_BPS),
        "speed_bytes": max(1, min(DEFAULT_SPEED_TEST_BYTES,
                                 num("probe_speed_bytes", DEFAULT_SPEED_TEST_BYTES))),
        "speed_url": db.get_setting(conn, "probe_speed_url", DEFAULT_SPEED_TEST_URL),
        "timeout": float(num("probe_timeout_ms", int(DEFAULT_PROBE_TIMEOUT * 1000))) / 1000,
        "concurrency": num("probe_concurrency", DEFAULT_PROBE_CONCURRENCY),
        "round_limit": num("probe_round_limit", DEFAULT_ROUND_LIMIT),
        "retry": num("probe_retry", DEFAULT_PROBE_RETRY),
    }


def run_funnel(proxies: list[dict], operator: str = "系统",
               only_missing: bool = True, *, max_nodes: int | None = None) -> dict:
    """跑一轮漏斗，返回 {results: [...], stats: {...}}。

    proxies：Mihomo 节点字典列表（含 name/server/port/type）。
    only_missing=True 时跳过已有完整结果的节点（增量跑）。
    """
    from .probes import registry

    with db.connect() as conn:
        cfg = _settings(conn)
    previous = load_results().get("nodes", {})
    detectors = registry.detectors_for()

    from . import node_rename

    pending = []
    now = time.time()
    for proxy in proxies:
        name = str(proxy.get("name") or "")
        if not name:
            continue
        # 占位节点（剩余流量/到期时间…）不是真节点，跳过
        if node_rename.is_info_node(name) or node_rename.is_prompt_node(name):
            continue
        if only_missing:
            old = previous.get(name)
            if old and (old.get("stage") == "probed" or
                        now - (old.get("checked_at") or 0) < FAILED_RECHECK_SECONDS):
                continue
        pending.append(proxy)
    limit = max(1, min(cfg["round_limit"], DEFAULT_ROUND_LIMIT))
    if max_nodes is not None:
        limit = min(limit, max_nodes)
    pending = pending[:limit]
    if not pending:
        return {"results": [], "stats": {"skipped": "没有待测节点"}}

    stats = {"total": len(proxies), "pending": len(pending),
             "latency_failed": 0, "speed_failed": 0, "probed": 0,
             "qualified": 0, "started_at": int(time.time())}
    results: list[NodeQuality] = []
    started = time.monotonic()
    try:
        with probe_engine.NodeEngine(pending) as engine:
            for proxy in pending:
                name = str(proxy.get("name"))
                quality = NodeQuality(name=name, checked_at=int(time.time()))
                # 一级：延迟
                delay = engine.delay_of(name, timeout_ms=cfg["max_delay_ms"] + 2000)
                quality.delay_ms = delay
                if delay < 0 or delay >= cfg["max_delay_ms"]:
                    quality.stage = "latency_failed"
                    stats["latency_failed"] += 1
                    results.append(quality)
                    continue
                # 二级：吞吐
                if not engine.select(name):
                    quality.stage = "latency_failed"
                    stats["latency_failed"] += 1
                    results.append(quality)
                    continue
                speed = engine.download_speed(
                    name, cfg["speed_url"], size_bytes=cfg["speed_bytes"])
                quality.speed_bps = speed
                if speed < cfg["min_speed_bps"]:
                    quality.stage = "speed_failed"
                    stats["speed_failed"] += 1
                    results.append(quality)
                    continue
                # 三级：解锁矩阵
                probes = {}
                for detector in detectors:
                    item = engine.probe_via_local(detector, cfg["timeout"])
                    probes[detector.platform_id] = item
                quality.probes = probes
                quality.stage = "probed"
                quality.badges = badges_from_probes(probes)
                quality.region = region_from_probes(probes)
                stats["probed"] += 1
                if quality.qualified:
                    stats["qualified"] += 1
                results.append(quality)
    except probe_engine.EngineError as exc:
        logger.warning("漏斗执行失败：%s", exc)
        stats["error"] = str(exc)

    stats["elapsed_sec"] = int(time.monotonic() - started)
    if results:
        save_results(results, operator)
    return {"results": [r.to_dict() for r in results], "stats": stats}


def badges_from_probes(probes: dict) -> str:
    """由探测结果算能力徽章（🔓 AI / 🎬 流媒体 / 📺 Netflix 高级版）。

    口径与 unlock_check.capability_badges 一致：无明确区域拒绝 + 确认解锁过半；
    人机校验（unknown）不算拒绝也不算通过。
    """
    from . import unlock_check

    ai_ids = unlock_check.AI_CHECK_IDS
    stream_ids = unlock_check.STREAM_CORE_IDS
    states = {pid: (item or {}).get("state", "") for pid, item in probes.items()}
    badges = ""
    if unlock_check._dimension_ok(states, ai_ids, unlock_check.AI_CONFIRM_MIN):
        badges += unlock_check.BADGE_AI
    if unlock_check._dimension_ok(states, stream_ids, unlock_check.STREAM_CONFIRM_MIN):
        badges += unlock_check.BADGE_STREAM
    nf = (probes.get("netflix_premium") or {})
    if nf.get("state") == "unlocked":
        badges += unlock_check.BADGE_NF_PREMIUM
    return badges


def region_from_probes(probes: dict) -> str:
    """从各平台结果里取一个可信的地区码（优先 Netflix / YouTube）。"""
    for pid in ("netflix", "youtube_premium", "disney", "tiktok", "spotify"):
        item = probes.get(pid) or {}
        region = (item.get("region") or "").strip().upper()
        if len(region) == 2:
            return region
    return ""


def load_results() -> dict:
    try:
        return json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"nodes": {}}


def save_results(results: list[NodeQuality], operator: str = "系统") -> None:
    """合并写入结果文件（原子替换），并保留一份时间戳快照。

    probed 节点同时写一份汇总进 unlock_cache.json（键=emit_name）：
    构建期的能力徽章判定（unlock_check.capability_badges）读的是那份缓存，
    两个缓存不打通时徽章永远出不来（2026-11-19 实证）。
    """
    from . import unlock_check

    data = load_results()
    nodes = data.get("nodes", {})
    for quality in results:
        nodes[quality.name] = quality.to_dict()
    payload = {"updated_at": int(time.time()), "operator": operator,
               "nodes": nodes}
    # 同步 unlock 缓存：probed 节点的 19 项结果按 unlock_check 的缓存结构写入
    entries = {}
    for quality in results:
        if quality.stage != "probed" or not quality.probes:
            continue
        # unlock_check._states_of 按结果项的 "id" 键索引平台，键名必须一致
        results_list = [
            {"id": pid, **{k: v for k, v in (item or {}).items()
                           if k not in ("id", "platform")}}
            for pid, item in quality.probes.items()]
        entry = {"checked_at": quality.checked_at, "exit": quality.name,
                 "results": results_list, "ip": {}}
        entries[quality.name] = entry
    unlock_check._save_cache_entries(entries, merge=False)
    _atomic_write(RESULT_PATH, json.dumps(payload, ensure_ascii=False, indent=1))
    snapshot = RESULT_PATH.parent / f"snapshot-{int(time.time())}.json"
    _atomic_write(snapshot, json.dumps(payload, ensure_ascii=False, indent=1))
    # 快照只留最近 20 份
    try:
        for old in sorted(RESULT_PATH.parent.glob("snapshot-*.json"))[:-20]:
            old.unlink()
    except OSError:
        pass


def _atomic_write(path, text: str) -> None:
    """临时文件 → 校验 → 原子替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        if path.suffix == ".json":
            json.loads(tmp.read_text(encoding="utf-8"))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
