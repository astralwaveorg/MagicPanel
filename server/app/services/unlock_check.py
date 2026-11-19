"""网络解锁检测：参考 RegionRestrictionCheck / Unlock Check 的思路，
把常用海外 AI 与流媒体的解锁判定搬到面板里，支持两种出口：

* ``panel`` —— 从面板（NAS）所在网络直接检测，即路由器代理链的真实出口；
* ``指定节点`` —— 用测速核心临时启动一个只含该节点的实例，把 HTTP 请求
  经该节点转发出去，衡量「这个节点能否解锁该服务」。

判定口径：HTTP 状态码 + 响应体里的地区特征。状态码语义参考 check.sh 的
经验值（200/302 = 解锁，403 = 区域拒绝，404 = 不支持）。
检测只反映「服务器看到的出口」；浏览器侧的体验还受客户端分流影响。
"""
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
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
     "url": "https://gemini.google.com/", "unlock": {200, 302, 301}, "blocked": {403}},
    # chat.openai.com 已整体迁移到 chatgpt.com（旧域 301 跟随；直接测新域，
    # 数据中心 IP 会被 Cloudflare 403——RegionCheck 同款判定）
    {"id": "chatgpt", "name": "ChatGPT", "icon": "◎", "category": "ai",
     "url": "https://chatgpt.com/", "unlock": {200, 302, 301}, "blocked": {403}},
    {"id": "claude", "name": "Claude", "icon": "✳", "category": "ai",
     "url": "https://claude.ai/", "unlock": {200, 302, 301},
     "region_marker": r"not available in your region|无法在您所在地区使用"},
    {"id": "grok", "name": "Grok", "icon": "𝕏", "category": "ai",
     "url": "https://grok.com/", "unlock": {200, 302, 301}},
    {"id": "perplexity", "name": "Perplexity", "icon": "◈", "category": "ai",
     "url": "https://www.perplexity.ai/", "unlock": {200, 302, 301},
     "region_marker": r"unavailable in your region|not available in your region"},
    {"id": "copilot", "name": "Copilot", "icon": "⌘", "category": "ai",
     "url": "https://copilot.microsoft.com/", "unlock": {200, 302, 301}},
    {"id": "netflix", "name": "Netflix", "icon": "N", "category": "stream",
     "url": "https://www.netflix.com/title/81280792",
     "unlock": {200}, "blocked": {403}, "unsupported": {404}},
    # Netflix 高级版目录：能访问说明该出口在高级版 IP 名单里（📺 徽章）。
    # 标准版与高级版是两套目录，只测 title 页区分不出来。
    {"id": "netflix_premium", "name": "Netflix 高级版", "icon": "N", "category": "stream",
     "url": "https://www.netflix.com/regions",
     "unlock": {200}, "blocked": {403}, "unsupported": {404}},
    {"id": "disney", "name": "Disney+", "icon": "D", "category": "stream",
     "url": "https://www.disneyplus.com/", "unlock": {200, 302, 301},
     "blocked": {403}, "unsupported": {404, 429}},
    {"id": "youtube_premium", "name": "YouTube Premium", "icon": "▶", "category": "stream",
     "url": "https://www.youtube.com/premium", "unlock": {200, 302, 301},
     "region_regex": r'"countryCode":"(\w\w)"'},
    {"id": "spotify", "name": "Spotify", "icon": "♫", "category": "stream",
     "url": "https://www.spotify.com/", "unlock": {200, 302, 301}},
    {"id": "tiktok", "name": "TikTok", "icon": "♪", "category": "stream",
     "url": "https://www.tiktok.com/", "unlock": {200, 302, 301}, "blocked": {403}},
    {"id": "dazn", "name": "Dazn", "icon": "▮", "category": "stream",
     "url": "https://www.dazn.com/", "unlock": {200, 302, 301}, "blocked": {403}},
    {"id": "biliintl", "name": "Bilibili 海外版", "icon": "B", "category": "stream",
     "url": "https://www.bilibili.tv/", "unlock": {200, 302, 301}},
    {"id": "hbo", "name": "HBO Max", "icon": "▣", "category": "stream",
     "url": "https://play.max.com/", "unlock": {200, 302, 301}, "blocked": {403}},
    {"id": "tvbanywhere", "name": "TVBAnywhere", "icon": "T", "category": "region",
     "url": "https://www.tvbanywhere.com/", "unlock": {200, 302, 301}},
    {"id": "viu", "name": "Viu.com", "icon": "V", "category": "region",
     "url": "https://www.viu.com/", "unlock": {200, 302, 301}, "blocked": {403}},
    {"id": "reddit", "name": "Reddit", "icon": "R", "category": "web",
     "url": "https://www.reddit.com/", "unlock": {200, 302, 301}, "blocked": {403}},
    {"id": "wikipedia", "name": "维基百科可编辑", "icon": "W", "category": "web",
     "url": "https://zh.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json",
     "unlock": {200}},
]
CHECK_BY_ID = {c["id"]: c for c in CHECKS}
CATEGORY_NAMES = {"ai": "海外 AI", "stream": "流媒体", "region": "服务地区检测", "web": "网站服务"}

_CACHE_PATH = config.DATA_DIR / "unlock_cache.json"


def _client(proxy: str | None) -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=CHECK_TIMEOUT,
                        follow_redirects=True, proxy=proxy or None,
                        headers={"User-Agent": UA})


_CF_CHALLENGE_PATTERN = re.compile(
    r"Just a moment|challenge-platform|cf-chl|Attention Required|请完成以下操作",
    re.IGNORECASE)


def _run_single(check: dict, proxy: str | None) -> dict:
    started = time.monotonic()
    status, body_head = None, ""
    try:
        with _client(proxy) as client:
            resp = client.get(check["url"])
        status = resp.status_code
        body_head = resp.text[:60000]
        latency = int((time.monotonic() - started) * 1000)
        region, detail = "", ""
        marker = check.get("region_marker")
        cf_challenge = (getattr(resp, "headers", {}).get("cf-mitigated") == "challenge"
                        or (status in (403, 503) and _CF_CHALLENGE_PATTERN.search(body_head)))
        if cf_challenge:
            state, detail = "error", "Cloudflare 人机校验"
        elif marker and re.search(marker, body_head, re.IGNORECASE):
            state, detail = "blocked", "服务提示地区限制"
        elif status == 429:
            state, detail = "error", "请求频率受限"
        elif status in check.get("unlock", {200, 302, 301}):
            state = "unlocked"
            rx = check.get("region_regex")
            if rx:
                m = re.search(rx, body_head)
                if m:
                    region = m.group(1).upper()
        elif marker and status in (403, 503):
            state, detail = "error", f"HTTP {status}，未确认限制原因"
        elif status in check.get("blocked", {403}):
            state, detail = "blocked", f"HTTP {status}，未确认限制原因"
        elif status in check.get("unsupported", set()):
            state, detail = "unsupported", f"HTTP {status}"
        else:
            state, detail = "error", f"HTTP {status}"
        return {"id": check["id"], "status": status, "state": state,
                "region": region, "latency_ms": latency, "detail": detail}
    except httpx.HTTPStatusError as exc:
        return {"id": check["id"], "status": exc.response.status_code,
                "state": "blocked", "region": "", "latency_ms": int((time.monotonic() - started) * 1000),
                "detail": ""}
    except Exception as exc:
        return {"id": check["id"], "status": None, "state": "error", "region": "",
                "latency_ms": int((time.monotonic() - started) * 1000),
                "detail": type(exc).__name__}


def _exit_proxy(exit_id: str) -> tuple[str | None, str]:
    """解析检测出口：panel = 直连（NAS 网络即路由器代理链出口）；
    其它 = 节点名，起一次性核心经该节点转发。返回 (proxy, 核心清理回调)。"""
    if exit_id in ("panel", ""):
        return None, None
    from . import tester, local_nodes, source_nodes  # 延迟导入避免循环
    import sqlite3
    import subprocess, tempfile, time, os, shutil
    from app import db as appdb, security

    conn = appdb.connect()
    conn.row_factory = sqlite3.Row
    proxy_dict = None
    row = conn.execute("SELECT * FROM local_nodes WHERE id=?", (exit_id,)).fetchone() \
        if exit_id.isdecimal() else None
    if row:
        node = {"name": row["name"], "node_type": row["node_type"] or "",
                "protocol": row["protocol"], "server": row["server"], "port": row["port"],
                "params": json.loads(security.decrypt_text(row["params_enc"]) or "{}"),
                "extra_yaml": security.decrypt_text(row["extra_yaml_enc"])
                if row["extra_yaml_enc"] else None}
        proxy_dict = local_nodes.render_proxy(node, "mihomo")
        proxy_dict["name"] = "unlock-probe"
    else:
        # 按节点名在来源快照里找（含被测速过滤掉的节点——检测允许复活它）
        for r in conn.execute(
                "SELECT name, snapshot_enc FROM sources WHERE snapshot_enc IS NOT NULL"):
            try:
                # extract 收 bytes（快照密文解密出来是文本）
                raw = security.decrypt_text(r["snapshot_enc"]) or ""
                proxies = source_nodes.extract(raw.encode("utf-8", "replace"))
            except Exception:
                continue
            hit = next((p for p in proxies if isinstance(p, dict) and p.get("name") == exit_id),
                       None)
            if hit:
                proxy_dict = dict(hit)
                proxy_dict["name"] = "unlock-probe"
                break
    conn.close()
    if not proxy_dict:
        raise LookupError(f"找不到检测出口节点：{exit_id}")

    import yaml
    wd = tempfile.mkdtemp(prefix="unlock-", dir=config.DATA_DIR)
    port = tester._free_port()
    mixed = tester._free_port()
    cfg = {"mixed-port": mixed, "allow-lan": False, "mode": "global",
           "log-level": "error", "external-controller": f"127.0.0.1:{port}",
           "proxies": [proxy_dict]}
    (Path(wd) / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    proc = subprocess.Popen(
        [str(tester.core_path()), "-d", wd, "-f", str(Path(wd) / "config.yaml")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=tester.direct_env(), text=True, errors="replace")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("解锁检测核心启动失败（节点配置可能无法解析）")
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        proc.wait()
        shutil.rmtree(wd, ignore_errors=True)
        raise RuntimeError("解锁检测核心启动超时")

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        proc.wait()
        shutil.rmtree(wd, ignore_errors=True)

    return f"http://127.0.0.1:{mixed}", cleanup


def run_checks(exit_id: str = "panel", ids: list[str] | None = None,
               operator: str = "") -> dict:
    """执行一批检测并写入缓存。返回 {checked_at, exit, results, ip}。"""
    checks = [CHECK_BY_ID[i] for i in (ids or [c["id"] for c in CHECKS]) if i in CHECK_BY_ID]
    proxy, cleanup = _exit_proxy(exit_id) if exit_id not in ("panel", "") else (None, None)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda c: _run_single(c, proxy), checks))
        ip = exit_ip(proxy)
    finally:
        if cleanup:
            cleanup()
    entry = {"checked_at": int(time.time()), "exit": exit_id or "panel",
             "results": results, "ip": ip}
    _save_cache(exit_id or "panel", entry, merge=bool(ids))
    return entry


# 管理页与旧门户分开保存，避免读取旧判定后展示为本次证据。
PANEL_EVIDENCE_CACHE = "panel-evidence-v2"


def run_panel_evidence(ids: list[str] | None = None) -> dict:
    """服务器网络用与节点质量一致的判定口径，不启动代理核心。"""
    from .probes import detect_platforms, detector_by_id, make_client_factory, ProbeResult
    from .probes.route_evidence import ConnectionReader, RoutedDetector

    checks = [check for check in CHECKS if not ids or check["id"] in ids]
    aliases = {"biliintl": "bilibili_intl", "netflix_premium": "netflix"}
    requested = list(dict.fromkeys(aliases.get(check["id"], check["id"]) for check in checks))
    reader = ConnectionReader()
    detectors = [RoutedDetector(d, reader) for pid in requested if (d := detector_by_id(pid))]
    observed = {r.platform: r for r in detect_platforms(
        detectors=detectors, client_factory=make_client_factory(),
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
    entry = {"checked_at": int(time.time()), "exit": "panel", "results": results, "ip": exit_ip()}
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


def _db_row_factory(conn):
    import sqlite3
    conn.row_factory = sqlite3.Row
    return conn


def detectable_nodes() -> list[str]:
    """可检测的节点原始名：来源快照里的全部节点（含被测速过滤的）+ 本地节点。

    与 _exit_proxy 的出口解析同一个口径（按原始名找）。
    """
    from .. import security
    from . import source_nodes

    names: list[str] = []
    with _db_row_factory(db.connect()) as conn:
        for r in conn.execute("SELECT snapshot_enc FROM sources WHERE snapshot_enc IS NOT NULL"):
            try:
                # extract 收 bytes；快照密文解密出来是文本，要编码回去
                raw = security.decrypt_text(r["snapshot_enc"]) or ""
                proxies = source_nodes.extract(raw.encode("utf-8", "replace"))
            except Exception as exc:
                logger.warning("来源快照解析失败（跳过该来源的节点）：%s", exc)
                continue
            for p in proxies:
                if isinstance(p, dict) and p.get("name"):
                    names.append(str(p["name"]))
        for r in conn.execute("SELECT name FROM local_nodes ORDER BY id"):
            names.append(r["name"])
    return sorted(set(names))


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
    每个节点独立起核心检测 AI 类，结果写 unlock_cache.json（exit_id=原始名）。
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
