"""数据库迁移回归测试。

状态机重构的迁移一旦出错，线上会直接不可用（表结构对不上代码）。
这里用「旧结构数据库」复现升级路径，验证迁移后的表结构与数据都正确。
"""
import importlib
import os
import sqlite3
import sys

import pytest


OLD_SCHEMA = """
CREATE TABLE devices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  platform TEXT NOT NULL,
  target_id INTEGER NOT NULL,
  channel TEXT NOT NULL DEFAULT 'stable',
  token_hash TEXT UNIQUE NOT NULL,
  token_hint TEXT NOT NULL,
  token_enc TEXT,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  last_pull_at TEXT,
  last_pull_ip TEXT,
  pull_count INTEGER NOT NULL DEFAULT 0,
  extra_yaml TEXT NOT NULL DEFAULT '',
  sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE builds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  policy_sha TEXT NOT NULL,
  snapshot TEXT NOT NULL,
  results TEXT NOT NULL DEFAULT '{}',
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE releases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  build_id INTEGER NOT NULL REFERENCES builds(id),
  channel TEXT NOT NULL,
  action TEXT NOT NULL,
  operator TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE pointers (
  channel TEXT PRIMARY KEY,
  build_id INTEGER,
  released_at TEXT,
  operator TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
"""


def _prepare_old_db(path) -> sqlite3.Connection:
    """造一个"通道双轨"时代的数据库。"""
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO builds(id, created_at, created_by, status, policy_sha, "
                 "snapshot, results, note) VALUES(30, '2026-10-21T10:00:00+08:00', "
                 "'astral', 'success', 'sha30', 'enc:v1:xx', '{}', '')")
    conn.execute("INSERT INTO builds(id, created_at, created_by, status, policy_sha, "
                 "snapshot, results, note) VALUES(28, '2026-10-20T10:00:00+08:00', "
                 "'系统', 'success', 'sha28', 'enc:v1:yy', '{}', '自动构建')")
    conn.execute("INSERT INTO builds(id, created_at, created_by, status, policy_sha, "
                 "snapshot, results, note) VALUES(27, '2026-10-19T10:00:00+08:00', "
                 "'astral', 'failed', 'sha27', 'enc:v1:zz', '{}', '')")
    # 同一构建同时占两个通道（双轨模型的老毛病）
    conn.execute("INSERT INTO pointers(channel, build_id, released_at, operator, "
                 "action, reason) VALUES('stable', 30, '2026-10-21T11:55:00+08:00', "
                 "'astral', 'promote', '')")
    conn.execute("INSERT INTO pointers(channel, build_id, released_at, operator, "
                 "action, reason) VALUES('candidate', 30, '2026-10-21T11:54:58+08:00', "
                 "'astral', 'promote', '')")
    conn.execute("INSERT INTO releases(build_id, channel, action, operator, reason, "
                 "created_at) VALUES(28, 'stable', 'promote', '系统', '自动构建发布', "
                 "'2026-10-20T23:16:32+08:00')")
    conn.execute("INSERT INTO releases(build_id, channel, action, operator, reason, "
                 "created_at) VALUES(30, 'candidate', 'promote', 'astral', '', "
                 "'2026-10-21T11:54:58+08:00')")
    conn.execute("INSERT INTO devices(name, platform, target_id, channel, token_hash, "
                 "token_hint, created_at) VALUES('Stash-iOS', 'ios', 1, 'stable', "
                 "'hash1', 'mp_abc', '2026-10-01T10:00:00+08:00')")
    conn.execute("INSERT INTO devices(name, platform, target_id, channel, token_hash, "
                 "token_hint, created_at) VALUES('Stash-tvOS', 'tvos', 1, 'candidate', "
                 "'hash2', 'mp_def', '2026-10-01T10:00:00+08:00')")
    conn.execute("INSERT INTO settings(key, value) VALUES('auto_publish_channel', "
                 "'stable')")
    conn.commit()
    conn.close()
    return conn


def _init_app(tmp_path):
    """在指定数据目录上重新加载应用并执行迁移。"""
    os.environ["MAGICPANEL_DATA_DIR"] = str(tmp_path / "data")
    os.environ["MAGICPANEL_SCHEDULER"] = "0"
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from app import db
    db.init_db()
    return db


def test_old_database_migrates_to_state_machine(tmp_path):
    """旧库升级后：表结构、状态分布、唯一索引与设置项都正确。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _prepare_old_db(data_dir / "magicpanel.db")

    db = _init_app(tmp_path)
    conn = db.connect()

    # builds：状态拆成生命周期 + 校验结果
    rows = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, status, verify_status, published_by FROM builds")}
    assert rows[30]["status"] == "PRODUCTION", rows[30]
    assert rows[30]["verify_status"] == "success"
    assert rows[30]["published_by"] == "astral"
    assert rows[28]["status"] == "OFFLINE", rows[28]
    assert rows[27]["status"] == "BUILT", rows[27]
    assert rows[27]["verify_status"] == "failed"

    # 唯一索引：生产与测试各至多一条
    assert conn.execute(
        "SELECT COUNT(*) FROM builds WHERE status='PRODUCTION'").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM builds WHERE status='TESTING'").fetchone()[0] == 0
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_builds_production" in names
    assert "idx_builds_testing" in names

    # pointers 表废弃
    assert not list(conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pointers'"))

    # releases：channel → env，旧的 NOT NULL 列必须消失
    release_cols = {r[1] for r in conn.execute("PRAGMA table_info(releases)")}
    assert "env" in release_cols
    assert "channel" not in release_cols
    envs = {r["build_id"]: r["env"] for r in conn.execute(
        "SELECT build_id, env FROM releases")}
    assert envs[28] == "production"
    assert envs[30] == "testing"

    # devices：channel → env
    device_cols = {r[1] for r in conn.execute("PRAGMA table_info(devices)")}
    assert "env" in device_cols
    assert "channel" not in device_cols
    envs = {r["name"]: r["env"] for r in conn.execute("SELECT name, env FROM devices")}
    assert envs["Stash-iOS"] == "production"
    assert envs["Stash-tvOS"] == "testing"

    # 设置项改名
    assert db.one(conn, "SELECT value FROM settings "
                        "WHERE key='auto_publish_channel'") is None
    assert db.get_setting(conn, "auto_publish_env") == "production"
    conn.close()


def test_migration_is_idempotent(tmp_path):
    """重复执行迁移不会改坏数据（线上会多次启动）。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _prepare_old_db(data_dir / "magicpanel.db")

    db = _init_app(tmp_path)
    db.init_db()
    db.init_db()
    conn = db.connect()
    assert conn.execute(
        "SELECT COUNT(*) FROM builds WHERE status='PRODUCTION'").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM builds WHERE status='OFFLINE'").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM builds WHERE status='BUILT'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0] == 2
    conn.close()


def test_release_history_insert_after_migration(tmp_path):
    """迁移后写发布历史不再因旧列 NOT NULL 失败。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _prepare_old_db(data_dir / "magicpanel.db")

    db = _init_app(tmp_path)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO releases(build_id, env, action, operator, reason, "
            "created_at) VALUES(30, 'production', 'publish', 'admin', '发布', ?)",
            (db.now(),))
    conn = db.connect()
    row = db.one(conn, "SELECT env, action FROM releases WHERE operator='admin'")
    assert dict(row) == {"env": "production", "action": "publish"}
    conn.close()
