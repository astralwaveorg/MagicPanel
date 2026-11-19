"""网络体检：统一服务判定，分别记录服务器出口和指定节点。"""
import json
import threading
import time
import logging

logger = logging.getLogger("magicpanel.unlock_check")
from pathlib import Path

import httpx

from .. import config, db

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CHECK_TIMEOUT = 8.0

# 检测目录：id 稳定（作为缓存键），icon 用 emoji（门户无外链资源依赖）
CHECKS = [
    {"id": "gemini", "name": "Google Gemini", "icon": "✦", "category": "ai",
     "url": "https://gemini.google.com/"},
    {"id": "chatgpt", "name": "ChatGPT", "icon": "◎", "category": "ai",
     "url": "https://chatgpt.com/"},
    {"id": "claude", "name": "Claude", "icon": "✳", "category": "ai",
     "url": "https://claude.ai/"},
    {"id": "grok", "name": "Grok", "icon": "𝕏", "category": "ai",
     "url": "https://grok.com/"},
    {"id": "perplexity", "name": "Perplexity", "icon": "◈", "category": "ai",
     "url": "https://www.perplexity.ai/"},
    {"id": "copilot", "name": "Copilot", "icon": "⌘", "category": "ai",
     "url": "https://copilot.microsoft.com/"},
    {"id": "netflix", "name": "Netflix", "icon": "N", "category": "stream",
     "url": "https://www.netflix.com/title/81280792"},
    {"id": "netflix_premium", "name": "Netflix 高级版", "icon": "N", "category": "stream",
     "url": "https://www.netflix.com/regions"},
    {"id": "disney", "name": "Disney+", "icon": "D", "category": "stream",
     "url": "https://www.disneyplus.com/"},
    {"id": "youtube_premium", "name": "YouTube Premium", "icon": "▶", "category": "stream",
     "url": "https://www.youtube.com/premium"},
    {"id": "spotify", "name": "Spotify", "icon": "♫", "category": "stream",
     "url": "https://www.spotify.com/"},
    {"id": "tiktok", "name": "TikTok", "icon": "♪", "category": "stream",
     "url": "https://www.tiktok.com/"},
    {"id": "dazn", "name": "Dazn", "icon": "▮", "category": "stream",
     "url": "https://www.dazn.com/"},
    {"id": "biliintl", "name": "Bilibili 海外版", "icon": "B", "category": "stream",
     "url": "https://www.bilibili.tv/"},
    {"id": "hbo", "name": "HBO Max", "icon": "▣", "category": "stream",
     "url": "https://play.max.com/"},
    {"id": "tvbanywhere", "name": "TVBAnywhere", "icon": "T", "category": "region",
     "url": "https://www.tvbanywhere.com/"},
    {"id": "viu", "name": "Viu.com", "icon": "V", "category": "region",
     "url": "https://www.viu.com/"},
    {"id": "google_search", "name": "Google 搜索", "icon": "G", "category": "web",
     "url": "https://www.google.com/search?q=example.org"},
    {"id": "gmail_web", "name": "Gmail", "icon": "M", "category": "web",
     "url": "https://mail.google.com/mail/"},
    {"id": "youtube_web", "name": "YouTube", "icon": "▶", "category": "web",
     "url": "https://www.youtube.com/"},
    {"id": "reddit", "name": "Reddit", "icon": "R", "category": "web",
     "url": "https://www.reddit.com/"},
    {"id": "wikipedia", "name": "维基百科可编辑", "icon": "W", "category": "web",
     "url": "https://zh.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json"},
]
CHECK_BY_ID = {c["id"]: c for c in CHECKS}
CATEGORY_NAMES = {"ai": "海外 AI", "stream": "流媒体", "region": "服务地区检测", "web": "网站服务"}

_CACHE_PATH = config.DATA_DIR / "unlock_cache.json"


def _client(proxy: str | None) -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=CHECK_TIMEOUT,
                        follow_redirects=True, proxy=proxy or None,
                        headers={"User-Agent": UA})


# 区分旧状态码缓存、公开结果和管理员的线路信息。
PANEL_EVIDENCE_CACHE = "panel-evidence-v2"
PORTAL_EVIDENCE_CACHE = "public-panel-evidence-v2"
WEB_ONLY_CHECKS = frozenset({"google_search", "gmail_web", "youtube_web"})


def _observe_checks(ids, *, proxy=None, reader=None):
    from .probes import detect_platforms, detector_by_id, make_client_factory, ProbeResult
    from .probes.base import Detector, Markers, classify_page
    from .probes.route_evidence import RoutedDetector

    class GoogleWebCheck(Detector):
        follow_redirects = False
        body_limit = 8192

        def __init__(self, check):
            self.platform_id = check["id"]
            self.url = check["url"]

        def probe(self, client):
            response = self.fetch(client)
            cls = classify_page(response, Markers())
            if cls.state == "reachable" and self.platform_id == "gmail_web":
                cls.detail = "入口有响应，未验证登录或收发邮件"
            return ProbeResult(self.platform_id, cls.state, response.status,
                               detail=cls.detail, extra={"reason": cls.reason})

    checks = [check for check in CHECKS if not ids or check["id"] in ids]
    aliases = {"biliintl": "bilibili_intl", "netflix_premium": "netflix"}
    requested = list(dict.fromkeys(aliases.get(check["id"], check["id"]) for check in checks))
    detectors = [GoogleWebCheck(CHECK_BY_ID[pid]) if pid in WEB_ONLY_CHECKS else detector_by_id(pid)
                 for pid in requested]
    detectors = [RoutedDetector(d, reader) if reader else d for d in detectors if d]
    observed = {r.platform: r for r in detect_platforms(
        detectors=detectors, client_factory=make_client_factory(proxy),
        max_workers=4, timeout=CHECK_TIMEOUT, retry=0)}
    results = []
    for check in checks:
        pid = check["id"]
        result = observed.get(aliases.get(pid, pid)) or ProbeResult(pid, "unknown", None)
        item = {"id": pid, **result.to_dict()}
        if pid == "netflix_premium":
            confirmed = result.extra.get("licensed_sample") is True
            if result.state == "unlocked" and not confirmed:
                item["state"] = "unknown"
            if confirmed:
                item["detail"] = "非自制剧样本可见；未验证播放"
        results.append(item)
    return results


def _resolve_node(exit_id, candidates):
    exact = [node for node in candidates if node["name"] == exit_id]
    if exact:
        return exact[0]
    # 兼容旧客户端提交本地节点 ID 或原名；同名时必须明确选择。
    with db.connect() as conn:
        names = {row["emit_name"] for row in conn.execute(
            "SELECT nc.emit_name FROM node_catalog nc "
            "LEFT JOIN local_nodes ln ON ln.id=nc.local_node_id "
            "WHERE nc.enabled=1 AND nc.retired=0 "
            "AND (nc.raw_name=? OR ln.name=? OR CAST(ln.id AS TEXT)=?)",
            (exit_id, exit_id, exit_id))}
    matches = [node for node in candidates if node["name"] in names]
    if len(matches) != 1:
        raise LookupError("找不到唯一的检测节点，请重新选择")
    return matches[0]


def run_checks(exit_id: str = "panel", ids: list[str] | None = None,
               operator: str = "") -> dict:
    """指定节点用独立 Mihomo，读取请求实际走过的线路；门户不公开线路信息。"""
    from . import scheduler
    from .probe_engine import EngineError, NodeEngine
    from .probes.route_evidence import ConnectionReader

    if exit_id in ("panel", ""):
        entry = {"checked_at": int(time.time()), "exit": "panel",
                 "results": _observe_checks(ids), "ip": exit_ip()}
        _save_cache(PORTAL_EVIDENCE_CACHE, entry, merge=bool(ids))
        return entry

    node = _resolve_node(exit_id, scheduler._collect_probe_proxies())
    name = node["name"]
    try:
        with NodeEngine([node]) as engine:
            if not engine.select(name):
                raise RuntimeError("无法确认检测节点")
            reader = ConnectionReader(endpoint=f"http://127.0.0.1:{engine.controller_port}", isolated=True)
            proxy = engine.proxy_url()
            results = _observe_checks(ids, proxy=proxy, reader=reader)
            ip = exit_ip(proxy)
    except EngineError as exc:
        raise RuntimeError(str(exc)) from None
    entry = {"checked_at": int(time.time()), "exit": name, "results": results, "ip": ip}
    _save_cache(name, entry, merge=bool(ids))
    return entry


def run_panel_evidence(ids: list[str] | None = None) -> dict:
    """服务器网络用与节点质量一致的判定口径，不启动代理核心。"""
    from .probes.route_evidence import ConnectionReader
    entry = {"checked_at": int(time.time()), "exit": "panel",
             "results": _observe_checks(ids, reader=ConnectionReader()), "ip": exit_ip()}
    _save_cache(PANEL_EVIDENCE_CACHE, entry, merge=bool(ids))
    return entry


def _load_all() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


_cache_write_lock = threading.Lock()


def _save_cache_entries(entries: dict, *, merge: bool) -> None:
    if not entries:
        return
    with _cache_write_lock:
        try:
            all_cache = json.loads(_CACHE_PATH.read_text())
        except FileNotFoundError:
            all_cache = {}
        for exit_id, entry in entries.items():
            prev = all_cache.get(exit_id) or {}
            if merge and prev.get("results"):
                merged = {r["id"]: r for r in prev["results"]}
                merged.update((r["id"], r) for r in entry["results"])
                entry = {**entry, "results": list(merged.values())}
            all_cache[exit_id] = entry
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_cache, ensure_ascii=False))
        tmp.replace(_CACHE_PATH)


def _save_cache(exit_id: str, entry: dict, merge: bool) -> None:
    _save_cache_entries({exit_id: entry}, merge=merge)


def last_results(exit_id: str = "panel") -> dict:
    return _load_all().get(exit_id or "panel") or {}


def exit_ip(proxy: str | None = None) -> dict:
    """出口 IP 与归属：面板直连用 ipinfo.io，经节点检测同走代理。"""
    try:
        with _client(proxy) as client:
            resp = client.get("https://ipinfo.io/json")
            data = resp.json()
        return {"ip": data.get("ip", ""), "country": data.get("country", ""),
                "org": data.get("org", ""), "city": data.get("city", "")}
    except Exception as exc:
        return {"ip": "", "country": "", "org": "", "city": "",
                "error": type(exc).__name__}


# ---------------------------------------------------------------- 节点解锁能力
# 「节点重命名一致性」的数据源（2026-11-18）：能力分类决定节点名上的徽章。
# 徽章单向变化：未测与被拒都不加，名字不会因解锁状态抖动而来回变。

# ---- 能力分类（构建期重命名用）------------------------------------
# 节点的「解锁能力」是多维的，不是一个是非题：
#   🔓  AI 六项全部解锁
#   🎬  流媒体解锁（Netflix 标准版 / Disney+ / Spotify / YouTube Premium）
#   📺  Netflix 高级版目录可达
# 徽章只加不减（未测/被拒都不加），名字不会因检测结果抖动而变化。

AI_CHECK_IDS = [c["id"] for c in CHECKS if c["category"] == "ai"]
STREAM_CHECK_IDS = [c["id"] for c in CHECKS if c["category"] == "stream"]

BADGE_AI = "🔓"
BADGE_STREAM = "🎬"
BADGE_NF_PREMIUM = "📺"

# 流媒体主项：这几项解锁才算「流媒体可用」（Netflix 高级版单独算 📺）
STREAM_CORE_IDS = [i for i in STREAM_CHECK_IDS
                   if i not in ("netflix_premium",)]


def _states_of(node_name: str) -> dict[str, str]:
    entry = _load_all().get(node_name)
    if not entry or not entry.get("results"):
        return {}
    return {r["id"]: r["state"] for r in entry["results"]}


# 维度判定口径（2026-11-18）：
# Claude / Perplexity 等站点对无头请求返回 403 + Cloudflare 人机校验，
# 这是**检测手段的局限**，不是节点被区域拒绝。若要求"全部 unlocked"，
# 🔓 徽章永远不会出现（实测每个节点都有 2 项 error）。
# 口径改为：维度内**没有一项被明确区域拒绝**，且**确认解锁的项过半**。
# 人机校验项算"无法判定"，不计入通过，也不算拒绝。

AI_CONFIRM_MIN = 4          # AI 维度共 6 项，至少 4 项确认解锁
STREAM_CONFIRM_MIN = 5      # 流媒体核心共 8 项，至少 5 项确认解锁


def _dimension_ok(states: dict, ids: list[str], confirm_min: int) -> bool:
    """维度内无明确拒绝，且确认解锁项达到下限。"""
    values = [states.get(i) for i in ids]
    if any(v == "blocked" for v in values):
        return False
    confirmed = sum(1 for v in values if v == "unlocked")
    return confirmed >= confirm_min


def ai_unlocked(node_name: str) -> bool:
    """该节点最近一次缓存检测结果里，AI 类是否可用。

    未检测过 → False（不加徽章，保守不冒充）。
    """
    states = _states_of(node_name)
    if not states:
        return False
    return _dimension_ok(states, AI_CHECK_IDS, AI_CONFIRM_MIN)


def capability_badges(node_name: str) -> str:
    """该节点的能力徽章串（可为空串）。

    * 🔓  AI 六项全解锁
    * 🎬  流媒体主项全解锁
    * 📺  Netflix 高级版目录可达
    """
    states = _states_of(node_name)
    if not states:
        return ""
    badges = ""
    if _dimension_ok(states, AI_CHECK_IDS, AI_CONFIRM_MIN):
        badges += BADGE_AI
    if _dimension_ok(states, STREAM_CORE_IDS, STREAM_CONFIRM_MIN):
        badges += BADGE_STREAM
    if states.get("netflix_premium") == "unlocked":
        badges += BADGE_NF_PREMIUM
    return badges


def capability_lookup() -> callable:
    """给 node_rename.rename_batch 用的徽章判定函数（返回徽章串）。"""
    return capability_badges


def coverage() -> dict:
    """解锁能力缓存覆盖率（构建流程与页面提示用）。

    covered = 有检测结果的节点数；total = 候选节点总数。
    """
    nodes = detectable_nodes()
    cache = _load_all()
    covered = [n for n in nodes if _states_of(n)]
    return {"total": len(nodes), "covered": len(covered),
            "missing": len(nodes) - len(covered),
            "ratio": round(len(covered) / len(nodes), 4) if nodes else 0.0}


def detectable_nodes() -> list[str]:
    from . import scheduler
    return sorted(node["name"] for node in scheduler._collect_probe_proxies())


# 批量检测进度（内存态；检测结果落 unlock_cache.json）
_batch_state: dict = {
    "running": False, "done": 0, "total": 0, "current": "",
    "started_at": "", "finished_at": "", "trigger": "", "error": "",
    "unlocked": 0,
}
_batch_lock = threading.Lock()


def batch_state() -> dict:
    return dict(_batch_state)


def run_batch(qty: int = 3, ids: list[str] | None = None,
              operator: str = "") -> dict:
    """对队列中的下一批节点做 AI 解锁检测（阻塞调用，放进后台线程跑）。

    节点队列 = detectable_nodes() 排序后按 cursor 轮转，游标存 settings；
    结果按启用节点的稳定标识保存。
    """
    if not _batch_lock.acquire(blocking=False):
        return {"skipped": "已有批量检测在进行中"}
    _batch_state.update(running=True, done=0, error="", trigger=operator or "manual")
    try:
        all_nodes = ids if ids else detectable_nodes()
        with db.connect() as conn:
            cursor = int(db.get_setting(conn, "unlock_batch_cursor", "0") or 0)
        queue = all_nodes[cursor % len(all_nodes):] + all_nodes[:cursor % len(all_nodes)]             if all_nodes else []
        batch = queue[:max(1, qty)]
        _batch_state["total"] = len(batch)
        unlocked = 0
        failures = 0
        _batch_state["started_at"] = db.now()
        for node in batch:
            if not _batch_state["running"]:
                break
            _batch_state["current"] = node
            try:
                # 检测全部服务项：AI + 流媒体 + Netflix 高级版，
                # 徽章分类才有完整数据（只测 AI 只能给出 🔓）
                run_checks(node, ids=None, operator=operator or "batch")
                if capability_badges(node):
                    unlocked += 1
            except Exception as exc:
                failures += 1
                logger.warning("节点解锁批量检测失败 %s：%s", node, exc)
            _batch_state["done"] += 1
            cursor += 1
        if batch:
            with db.tx() as conn:
                db.set_setting(conn, "unlock_batch_cursor", str(cursor % len(all_nodes)))
        _batch_state.update(running=False, finished_at=db.now(), current="",
                            unlocked=unlocked)
        result = {"ok": True, "done": _batch_state["done"], "unlocked": unlocked}
        if failures and failures == _batch_state["done"]:
            result.update(ok=False, error="本批节点检测均失败")
        return result
    finally:
        _batch_state.update(running=False, current="")
        _batch_lock.release()
