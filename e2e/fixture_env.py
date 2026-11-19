"""本地验收环境：临时数据目录 + 管理员 + 样例数据 + 启动服务。

用途：前端/页面验收与截图巡检（e2e/screenshot_all.mjs 依赖本环境）。
数据形状与生产一致（来源→组→规则→目标→构建→发布→设备→能力缓存）。
"""
import os
import sys
from pathlib import Path

DATA = Path(os.environ.get("MP_FIXTURE_DIR", "/tmp/mp-screenshot-data"))
DATA.mkdir(parents=True, exist_ok=True)
os.environ["MAGICPANEL_DATA_DIR"] = str(DATA)
os.environ["MAGICPANEL_SCHEDULER"] = "0"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import db, security  # noqa: E402
from app.main import create_app  # noqa: E402

app = create_app()

with db.tx() as conn:
    if not db.one(conn, "SELECT 1 FROM users LIMIT 1"):
        pwd_hash, pwd_salt = security.hash_password("Screenshot-2026")
        conn.execute(
            "INSERT INTO users(id, username, password_hash, salt, role, display_name, "
            "created_at) VALUES(1, 'admin', ?, ?, 'admin', '截图验证', ?)",
            (pwd_hash, pwd_salt, db.now()))

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)
r = client.post("/api/v1/auth/login",
                json={"username": "admin", "password": "Screenshot-2026"})
assert r.status_code == 200, r.text
csrf = r.json()["csrf_token"]
h = {"X-CSRF-Token": csrf}

import base64  # noqa: E402

snap = """proxies:
  - name: '🇭🇰 香港01 Hyper'
    type: ss
    server: 192.0.2.11
    port: 8388
    cipher: aes-128-gcm
    password: 'x'
  - name: '🇺🇸 美国01 IEPL'
    type: ss
    server: 192.0.2.12
    port: 8388
    cipher: aes-128-gcm
    password: 'x'
  - name: '剩余流量：100GB'
    type: ss
    server: 127.0.0.1
    port: 53
    cipher: aes-128-gcm
    password: 'x'
"""
client.post("/api/v1/sources/import-file", headers=h, json={
    "name": "示例机场",
    "content_b64": base64.b64encode(snap.encode()).decode(),
    "mode": "inline"})

from app.services import unlock_check  # noqa: E402
from app.services import quality_funnel  # noqa: E402

for name, ai_ok in (("🇭🇰 香港01 Hyper", True), ("🇺🇸 美国01 IEPL", False)):
    states = {i: "unlocked" for i in
              unlock_check.AI_CHECK_IDS + unlock_check.STREAM_CORE_IDS}
    states["netflix_premium"] = "unlocked"
    if not ai_ok:
        states["claude"] = "error"
        states["perplexity"] = "error"
    unlock_check._save_cache(name, {"checked_at": 1, "exit": name,
                                   "results": [{"id": i, "state": s, "status": 200,
                                                "region": "HK" if ai_ok else "US",
                                                "latency_ms": 200, "detail": ""}
                                               for i, s in states.items()],
                                   "ip": {"ip": "203.0.113.7", "country": "HK"}},
                          merge=False)

quality_funnel.save_results([
    quality_funnel.NodeQuality(name="🇭🇰 香港01 Hyper", delay_ms=387,
                              speed_bps=6.3 * 1024 * 1024, stage="probed",
                              badges="🔓🎬📺", region="HK", checked_at=1)],
    "截图夹具")

for name, gtype, kw in (("🚀 默认代理", "select", {}),
                        ("🧠 人工智能", "fallback", {}),
                        ("🇭🇰 香港", "select", {"filter": r"(?i)🇭🇰|香港"})):
    body = {"name": name, "type": gtype, "proxies": ["DIRECT"]}
    body.update(kw)
    client.post("/api/v1/groups", headers=h, json=body)
client.post("/api/v1/rules", headers=h, json={"type": "MATCH", "target": "🚀 默认代理"})
for name, engine, platform in (("Stash-iOS", "stash", "ios"),
                               ("Mihomo-macOS", "mihomo", "macos")):
    client.post("/api/v1/targets", headers=h,
                json={"name": name, "engine": engine, "platform": platform})

from app.routers import builds as builds_router  # noqa: E402
from app.services import releases  # noqa: E402

bid, _status = builds_router.create_build("截图夹具", note="截图验证夹具")
with db.tx(immediate=True) as conn:
    build = builds_router._get_build(conn, bid)
    releases.publish_to_testing(conn, build, "截图夹具", "测试")
with db.tx(immediate=True) as conn:
    build = builds_router._get_build(conn, bid)
    releases.publish_to_production(conn, build, "截图夹具", "生产")

client.post("/api/v1/devices", headers=h, json={
    "name": "iPhone", "platform": "ios", "target_id": 1})
client.post("/api/v1/rule-providers", headers=h, json={
    "name": "magic-direct", "behavior": "domain", "format": "yaml",
    "kind": "inline", "inline_content": "payload:\n  - '+.example.com'\n"})
client.post("/api/v1/snippets", headers=h, json={
    "name": "示例模块", "category": "panel",
    "content": "profile:\n  store-selected: true\n", "enabled": True})

print("=== 验收环境就绪 ===", flush=True)

import uvicorn  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=7101, log_level="warning")
