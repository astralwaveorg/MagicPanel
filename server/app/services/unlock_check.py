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
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .. import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CHECK_TIMEOUT = 8.0

# 检测目录：id 稳定（作为缓存键），icon 用 emoji（门户无外链资源依赖）
CHECKS = [
    {"id": "gemini", "name": "Google Gemini", "icon": "✦", "category": "ai",
     "url": "https://gemini.google.com/", "unlock": {200, 302, 301}},
    {"id": "chatgpt", "name": "ChatGPT", "icon": "◎", "category": "ai",
     "url": "https://chat.openai.com/", "unlock": {200, 302, 301}, "blocked": {403}},
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
        region = ""
        if status in check.get("unlock", {200, 302, 301}):
            state = "unlocked"
            rx = check.get("region_regex")
            if rx:
                m = re.search(rx, body_head)
                if m:
                    region = m.group(1).upper()
        else:
            # 403/503 带 Cloudflare 人机校验特征时，无法区分区域拒绝还是
            # 数据中心 IP 被拦（常见误判），如实标记「无法判定」。
            if status in (403, 503) and _CF_CHALLENGE_PATTERN.search(body_head):
                return {"id": check["id"], "status": status, "state": "error",
                        "region": "", "latency_ms": latency,
                        "detail": "Cloudflare 人机校验，无法判定"}
            marker = check.get("region_marker")
            if marker and re.search(marker, body_head, re.IGNORECASE):
                state = "blocked"
            elif marker and status in (403, 503):
                # 声明了区域标记却没有命中：多半是人机校验/风控，如实标记无法判定
                return {"id": check["id"], "status": status, "state": "error",
                        "region": "", "latency_ms": latency,
                        "detail": "403 无区域特征，无法判定"}
            elif status in check.get("blocked", {403}):
                state = "blocked"
            elif status in check.get("unsupported", set()):
                state = "unsupported"
            elif status in {429}:
                state = "blocked"
            else:
                state = "error"
        return {"id": check["id"], "status": status, "state": state,
                "region": region, "latency_ms": latency, "detail": ""}
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
                proxies = source_nodes.extract(security.decrypt_text(r["snapshot_enc"]))
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
        shutil.rmtree(wd, ignore_errors=True)
        raise RuntimeError("解锁检测核心启动超时")

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
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
    _save_cache(exit_id or "panel", entry, merge=not ids)
    return entry


def _load_all() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(exit_id: str, entry: dict, merge: bool) -> None:
    all_cache = _load_all() if merge else {}
    prev = all_cache.get(exit_id) or {}
    if merge and prev.get("results"):
        merged = {r["id"]: r for r in prev["results"]}
        for r in entry["results"]:
            merged[r["id"]] = r
        entry["results"] = list(merged.values())
    all_cache[exit_id] = entry
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_cache, ensure_ascii=False))
    tmp.replace(_CACHE_PATH)


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
