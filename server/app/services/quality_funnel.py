"""节点质量漏斗：延迟 → 吞吐 → 解锁矩阵。

设计（2026-11-19 审计）：
* **一级·连通与延迟**：Mihomo delay API。延迟 ≥ 阈值或不可达 → 直接淘汰。
* **二级·下载吞吐**：只对一级达标的节点测速，平均速度 < 阈值 → 归入备用池
  （不参与解锁探测，省时间也降低目标站点风控压力）。
* **三级·解锁矩阵**：只对一二级都达标的节点跑平台探测，产出结构化能力标签。

所有阈值、并发、超时、重试都是配置项（settings 表），代码里只放默认值。
"""
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field

from .. import config, db, security
from . import probe_engine

logger = logging.getLogger("magicpanel.quality_funnel")

# ---- 默认阈值（可被 settings 覆盖）----
DEFAULT_MAX_DELAY_MS = int(config.SETTINGS_DEFAULTS["probe_max_delay_ms"])          # 一级：延迟上限
DEFAULT_MIN_SPEED_BPS = 2_000_000          # 二级：2 MB/s（16 Mbps）
DEFAULT_SPEED_TEST_BYTES = 5 * 1024 * 1024  # 测速文件大小
DEFAULT_PROBE_CONCURRENCY = 4       # 探测并发
DEFAULT_PROBE_RETRY = 1

# 结果落盘位置
RESULT_PATH = config.DATA_DIR / "node_quality.json"
FAILED_RECHECK_SECONDS = 6 * 3600
RESULT_FORMAT = 5
DOWNLOAD_ERRORS = {
    "wrong_node": "无法确认测速节点",
    "http_status": "测速站返回 HTTP {status}",
    "encoded": "测速站返回压缩数据",
    "timeout": "下载测速超时",
    "transfer_error": "测速连接中断",
    "short_body": "测速站返回的数据不足",
}


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
    revision: str = ""
    reason: str = ""
    download: dict = field(default_factory=dict)

    @property
    def qualified(self) -> bool:
        """是否进入主可用池（一级 + 二级都达标）。"""
        return self.stage == "probed"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "delay_ms": self.delay_ms,
            "speed_bps": round(self.speed_bps), "stage": self.stage,
            "probes": self.probes, "badges": self.badges, "region": self.region,
            "checked_at": self.checked_at,
            "revision": self.revision, "reason": self.reason, "qualified": self.qualified,
            "download": self.download,
        }


def _settings(conn) -> dict:
    def num(key: str, default: int) -> int:
        try:
            return int(db.get_setting(conn, key, str(default)) or default)
        except (TypeError, ValueError):
            return default
    return {
        "max_delay_ms": max(1, min(5000, num("probe_max_delay_ms", DEFAULT_MAX_DELAY_MS))),
        "min_speed_bps": max(1, num("probe_min_speed_bps", DEFAULT_MIN_SPEED_BPS)),
        "speed_bytes": max(65536, min(DEFAULT_SPEED_TEST_BYTES,
                                 num("probe_speed_bytes", DEFAULT_SPEED_TEST_BYTES))),
        "timeout": max(1000, min(15000, num("probe_timeout_ms", 8000))) / 1000,
        "speed_timeout": max(3, min(20, num("probe_speed_timeout_sec", 12))),
        "concurrency": max(1, min(6, num("probe_concurrency", DEFAULT_PROBE_CONCURRENCY))),
        "round_limit": max(1, min(10, num("probe_round_limit", 10))),
        "retry": max(0, min(1, num("probe_retry", DEFAULT_PROBE_RETRY))),
        "refresh_seconds": max(12, min(168, num("probe_refresh_hours", 24))) * 3600,
        "platform_ids": [i.strip() for i in db.get_setting(conn, "probe_platform_ids", "").split(",") if i.strip()],
    }


def _fingerprint(proxy: dict, key: bytes, cfg: dict) -> str:
    """代理材料或判定配置变更时，不沿用旧的测量。"""
    material = {k: v for k, v in proxy.items() if k not in ("name", "source_id")}
    contract = {k: cfg[k] for k in ("max_delay_ms", "min_speed_bps", "speed_bytes", "platform_ids")}
    payload = json.dumps([RESULT_FORMAT, material, contract], sort_keys=True, ensure_ascii=False, default=str)
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def current_results(proxies: list[dict]) -> dict:
    return result_reader()(proxies)


def result_reader():
    """固定一份结果，整次构建用同一个版本。"""
    with db.connect() as conn:
        cfg = _settings(conn)
    results = load_results().get("nodes", {})
    key = (security.derive_subkey(security.load_master_material(), purpose="node-quality")
           if results else b"")
    return lambda proxies: _matching_results(proxies, results, cfg, key)


def _checked_at(item: dict) -> int:
    value = item.get("checked_at")
    return value if type(value) is int else 0


def _matching_results(proxies, results, cfg, key):
    if not results:
        return {}
    now = int(time.time())
    earliest = now - cfg["refresh_seconds"] - FAILED_RECHECK_SECONDS
    return {p["name"]: old for p in proxies
            if (old := results.get(p.get("name"))) and _checked_at(old) >= earliest
            and _checked_at(old) <= now
            and old.get("revision") == _fingerprint(p, key, cfg)}


def run_funnel(proxies: list[dict], operator: str = "系统",
               only_missing: bool = True, *, max_nodes: int | None = None) -> dict:
    """跑一轮漏斗，返回 {results: [...], stats: {...}}。

    proxies：Mihomo 节点字典列表（含 name/server/port/type）。
    only_missing=True 时跳过已有完整结果的节点（增量跑）。
    """
    from . import routing_planner
    from .probes import registry

    with db.connect() as conn:
        cfg = _settings(conn)
    previous = load_results().get("nodes", {})
    detectors = registry.detectors_for(cfg["platform_ids"] or None)
    if not cfg["platform_ids"]:
        # 先测参与构建的服务。预算不足时，少见平台可以留到复测。
        detectors.sort(key=lambda detector: detector.platform_id not in routing_planner.SERVICE_ALIAS_NAMES)
    key = security.derive_subkey(security.load_master_material(), purpose="node-quality")

    from . import node_rename

    pending = []
    revisions = {}
    now = time.time()
    for proxy in proxies:
        name = str(proxy.get("name") or "")
        if not name:
            continue
        # 占位节点（剩余流量/到期时间…）不是真节点，跳过
        if node_rename.is_info_node(name) or node_rename.is_prompt_node(name):
            continue
        revision = revisions[name] = _fingerprint(proxy, key, cfg)
        old = previous.get(name) or {}
        age = now - _checked_at(old)
        if only_missing:
            interval = cfg["refresh_seconds"] if old.get("stage") in ("probed", "unsupported") else FAILED_RECHECK_SECONDS
            if old.get("reason") == "部分平台等待复测":
                interval = FAILED_RECHECK_SECONDS
            if old.get("revision") == revision and 0 <= age < interval:
                continue
        pending.append(proxy)
    def queue_key(proxy: dict) -> tuple[int, bool]:
        name = proxy["name"]
        old = previous.get(name, {})
        last = _checked_at(old) if old.get("revision") == revisions[name] else 0
        # 同样缺测时先测本地节点。跑过的节点仍按上次检测时间排队，
        # 因此不会反复插队，订阅节点也能按批次完成。
        return last, proxy.get("source_id") is not None

    pending.sort(key=queue_key)
    limit = cfg["round_limit"]
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
    candidates = []
    for proxy in pending:
        name = proxy["name"]
        if proxy.get("type") in {"direct", "reject", "pass", "compatible", "dns"}:
            results.append(NodeQuality(name, stage="unsupported", checked_at=int(time.time()),
                                       revision=revisions[name], reason="这个条目没有独立代理出口"))
            stats["unsupported"] = stats.get("unsupported", 0) + 1
        else:
            candidates.append({k: v for k, v in proxy.items() if k != "source_id"})

    # 按核心返回的位置隔离坏配置，限制重复启动；普通运行故障交给调度退避。
    while candidates:
        try:
            with probe_engine.NodeEngine(candidates) as engine:
                _measure_nodes(engine, candidates, cfg, detectors, revisions, results, stats,
                               deadline=started + 180)
            break
        except probe_engine.EngineError as exc:
            rejected = [p for i, p in enumerate(candidates)
                        if i == exc.index or p.get("type") in exc.types]
            if not rejected:
                logger.warning("漏斗执行失败：%s", exc)
                stats["error"] = str(exc)
                break
            for p in rejected:
                name = p["name"]
                results.append(NodeQuality(name, stage="unsupported", checked_at=int(time.time()),
                                           revision=revisions[name], reason="Mihomo 无法加载该节点"))
            stats["unsupported"] = stats.get("unsupported", 0) + len(rejected)
            candidates = [p for p in candidates if p not in rejected]

    stats["elapsed_sec"] = int(time.monotonic() - started)
    if results:
        save_results(results, operator, active_names=set(revisions))
    return {"results": [r.to_dict() for r in results], "stats": stats}


def _measure_nodes(engine, candidates, cfg, detectors, revisions, results, stats, *, deadline):
    for proxy in candidates:
        if time.monotonic() >= deadline:
            stats["paused"] = "本轮已到时间预算，剩余节点留到下一轮"
            break
        name = str(proxy.get("name"))
        quality = NodeQuality(name=name, checked_at=int(time.time()), revision=revisions[name])
        # 一级：延迟
        delay_timeout = 8000 if proxy.get("type") in {"hysteria", "hysteria2", "tuic"} else 5000
        delay = engine.delay_of(name, timeout_ms=delay_timeout)
        if delay < 0 and cfg["retry"]:
            delay = engine.delay_of(name, timeout_ms=delay_timeout)
        quality.delay_ms = delay
        if delay < 0 or delay >= cfg["max_delay_ms"]:
            quality.stage = "latency_failed"
            quality.reason = "延迟超过上限" if delay >= 0 else "延迟探测无响应"
            stats["latency_failed"] += 1
            results.append(quality)
            continue
        # 二级：吞吐
        if not engine.select(name):
            quality.stage = "inconclusive"
            quality.reason = "无法确认选中的节点"
            results.append(quality)
            continue
        sample = engine.download_speed(
            name, f"https://speed.cloudflare.com/__down?bytes={cfg['speed_bytes']}",
            size_bytes=cfg["speed_bytes"], timeout=cfg["speed_timeout"])
        quality.download = {"bytes": sample.received_bytes, "response_ms": sample.response_ms,
                            "status": sample.status, "error": sample.error}
        speed = sample.speed_bps
        quality.speed_bps = speed
        if sample.error or speed < cfg["min_speed_bps"]:
            quality.stage = "inconclusive" if sample.error else "speed_failed"
            quality.reason = (DOWNLOAD_ERRORS[sample.error].format(status=sample.status)
                              if sample.error else "下载速度低于下限")
            if not sample.error:
                stats["speed_failed"] += 1
            results.append(quality)
            continue
        # 三级：解锁矩阵
        probes = engine.probe_via_local(detectors, cfg["timeout"],
                                       workers=cfg["concurrency"], retry=cfg["retry"],
                                       deadline=min(deadline, time.monotonic() + 110))
        quality.probes = probes
        if any((probe.get("extra") or {}).get("reason") == "budget" for probe in probes.values()):
            quality.reason = "部分平台等待复测"
            stats["partial"] = stats.get("partial", 0) + 1
        quality.stage = "probed"
        quality.badges = badges_from_probes(probes)
        quality.region = region_from_probes(probes)
        stats["probed"] += 1
        if quality.qualified:
            stats["qualified"] += 1
        results.append(quality)


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
    nf = probes.get("netflix") or {}
    if nf.get("state") == "unlocked" and (nf.get("extra") or {}).get("licensed_sample") is True:
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


def save_results(results: list[NodeQuality], operator: str = "系统", *, active_names=None) -> None:
    """保留当前质量状态及历史快照；旧解锁缓存只供手动网络体检。"""
    data = load_results()
    nodes = {name: value for name, value in data.get("nodes", {}).items()
             if active_names is None or name in active_names}
    for quality in results:
        nodes[quality.name] = quality.to_dict()
    payload = {"updated_at": int(time.time()), "operator": operator,
               "nodes": nodes}
    _atomic_write(RESULT_PATH, json.dumps(payload, ensure_ascii=False, indent=1))
    snapshot = RESULT_PATH.parent / "node-quality-history" / f"{time.time_ns()}.json"
    _atomic_write(snapshot, json.dumps(payload, ensure_ascii=False, indent=1))
    # 快照只留最近 20 份
    try:
        for old in sorted(snapshot.parent.glob("[0-9]*.json"))[:-20]:
            old.unlink()
    except OSError:
        pass


def _atomic_write(path, text: str) -> None:
    """临时文件 → 校验 → 原子替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        from pathlib import Path
        tmp = Path(handle.name)
        handle.write(text)
    try:
        if path.suffix == ".json":
            json.loads(tmp.read_text(encoding="utf-8"))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
