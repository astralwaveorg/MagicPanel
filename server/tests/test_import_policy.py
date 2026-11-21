"""导入回填与分发资源非空门禁的回归。

2026-11-21 线上事故：import_policy.py 整表导入保留了 `inline_content`，
却丢掉了分发处理器读取的 `content`，三个内联规则来源 404，客户端订阅
更新失败。本文件锁住两道防线：
1. 导出 → 导入后，内联来源的 content / sha256 / rule_count 自动回填；
2. 构建期校验把「被规则/DNS 引用但正文为空」的来源判为错误，不再静默放行。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import import_policy  # noqa: E402
import export_policy  # noqa: E402

INLINE_BODY = ("# 名称: my-inline\npayload:\n"
               "  - +.example.com\n  - +.sample.org\n")


def _setup(client) -> dict:
    csrf = client.post("/api/v1/setup", json={
        "username": "admin", "password": "admin-pass-1"}).json()["csrf_token"]
    return {"X-CSRF-Token": csrf}


def _make_inline_source(client) -> int:
    """经面板 API 建一个内联规则来源，返回 id（与线上事故同形态）。"""
    headers = _setup(client)
    resp = client.post("/api/v1/rule-providers", json={
        "name": "my-inline", "behavior": "domain", "format": "yaml",
        "kind": "inline", "inline_content": INLINE_BODY,
        "interval": 86400, "client_interval": 0, "enabled": True,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _fresh_db(tmp_path) -> Path:
    """在独立数据目录建一个全新库（import 的目标库）。"""
    os.environ["MAGICPANEL_DATA_DIR"] = str(tmp_path / "data2")
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]
    from app import db as app_db
    app_db.init_db()
    return app_db.config.DB_PATH


def test_export_import_refills_inline_content(client, tmp_path):
    _make_inline_source(client)

    from app import config as app_config
    db_path = app_config.DB_PATH
    assert db_path.is_file()

    out = tmp_path / "snap.json"
    assert export_policy.main(["--db", str(db_path), "--out", str(out)]) == 0
    new_db = _fresh_db(tmp_path)
    assert import_policy.main(["--db", str(new_db), "--in", str(out)]) == 0

    conn = sqlite3.connect(new_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM rule_providers WHERE name='my-inline'").fetchone()
    conn.close()
    assert row["kind"] == "inline"
    assert row["content"] == row["inline_content"] == INLINE_BODY, "分发正文必须回填"
    assert row["sha256"] == hashlib.sha256(INLINE_BODY.encode()).hexdigest()
    assert row["rule_count"] == 2, "payload 条目计数（注释与 payload: 行不计）"
    assert row["last_status"] == "ok"


def test_validate_blocks_empty_distribution_content(client):
    """被规则引用的来源正文为空 → 构建校验必须报错（不再静默放行）。"""
    from app.compiler import validate
    from app import config as app_config
    from app.routers import builds as builds_router

    _make_inline_source(client)
    conn = sqlite3.connect(app_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # 引用该来源的规则（sort 置于 MATCH 之后不影响本断言：只看错误集合）
    conn.execute(
        "INSERT INTO rules(variant_id, sort, type, value, target, enabled, "
        "created_at, updated_at) VALUES(0, 900, 'RULE-SET', 'my-inline', "
        "'DIRECT', 1, datetime('now'), datetime('now'))")
    conn.commit()

    snap, _ = builds_router.current_policy(conn)
    # 模拟导入事故：把该来源的 content_sha 换成空正文指纹
    empty_sha = hashlib.sha256(b"").hexdigest()
    for p in snap["rule_providers"]:
        if p["name"] == "my-inline":
            p["content_sha"] = empty_sha
    conn.close()

    result = validate.validate_policy(snap)
    all_errors = [e for errors, _ in result.values() for e in errors]
    assert any("分发正文为空" in e for e in all_errors), all_errors


def test_roundtrip_content_sha_changes(client, tmp_path):
    """导入回填后 content_sha 与空指纹不同——门禁放行正常导入。"""
    _make_inline_source(client)

    from app import config as app_config
    out = tmp_path / "snap.json"
    assert export_policy.main(["--db", str(app_config.DB_PATH), "--out", str(out)]) == 0
    new_db = _fresh_db(tmp_path)
    assert import_policy.main(["--db", str(new_db), "--in", str(out)]) == 0

    conn = sqlite3.connect(new_db)
    sha = conn.execute(
        "SELECT sha256 FROM rule_providers WHERE name='my-inline'").fetchone()[0]
    conn.close()
    empty_sha = hashlib.sha256(b"").hexdigest()
    assert sha and sha != empty_sha
