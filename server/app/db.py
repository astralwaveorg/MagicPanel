"""SQLite 数据层：连接、事务与建表。单实例单写入，WAL 模式。"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'admin',
  portal_pin_hash TEXT NOT NULL DEFAULT '',
  avatar_mime TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  ip TEXT, ua TEXT
);
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  url_enc TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  filter TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT 'Stash',
  interval INTEGER NOT NULL DEFAULT 21600,
  auto_fetch INTEGER NOT NULL DEFAULT 1,
  allow_private INTEGER NOT NULL DEFAULT 0,
  last_status TEXT NOT NULL DEFAULT 'never',
  last_error TEXT NOT NULL DEFAULT '',
  last_fetched_at TEXT,
  last_attempt_at TEXT,
  node_count INTEGER,
  sha256 TEXT,
  fail_count INTEGER NOT NULL DEFAULT 0,
  snapshot_enc TEXT,
  nodes_meta TEXT NOT NULL DEFAULT '[]',
  filter_unavailable INTEGER NOT NULL DEFAULT 0,
  tested_at TEXT,
  test_attempt_at TEXT,
  test_interval INTEGER NOT NULL DEFAULT 21600,
  auto_test INTEGER NOT NULL DEFAULT 1,
  test_results TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_providers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  behavior TEXT NOT NULL DEFAULT 'domain',
  format TEXT NOT NULL DEFAULT 'yaml',
  kind TEXT NOT NULL DEFAULT 'remote',
  url TEXT NOT NULL DEFAULT '',
  inline_content TEXT NOT NULL DEFAULT '',
  interval INTEGER NOT NULL DEFAULT 86400,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_status TEXT NOT NULL DEFAULT 'never',
  last_error TEXT NOT NULL DEFAULT '',
  last_fetched_at TEXT,
  last_attempt_at TEXT,
  rule_count INTEGER,
  sha256 TEXT,
  content TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_nodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  protocol TEXT NOT NULL,
  server TEXT NOT NULL,
  port INTEGER NOT NULL,
  params_enc TEXT NOT NULL DEFAULT '',
  extra_yaml_enc TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proxy_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL DEFAULT 'select',
  sort INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0,
  filter TEXT NOT NULL DEFAULT '',
  use_sources TEXT NOT NULL DEFAULT '[]',
  local_nodes TEXT NOT NULL DEFAULT '[]',
  proxies TEXT NOT NULL DEFAULT '[]',
  url TEXT NOT NULL DEFAULT 'https://www.gstatic.com/generate_204',
  interval INTEGER NOT NULL DEFAULT 600,
  timeout INTEGER NOT NULL DEFAULT 8000,
  tolerance INTEGER NOT NULL DEFAULT 150,
  lazy INTEGER NOT NULL DEFAULT 1,
  strategy TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sort INTEGER NOT NULL DEFAULT 0,
  type TEXT NOT NULL,
  value TEXT NOT NULL DEFAULT '',
  target TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  note TEXT NOT NULL DEFAULT '',
  no_resolve INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS targets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  engine TEXT NOT NULL,
  platform TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  extra_yaml TEXT NOT NULL DEFAULT '',
  update_interval INTEGER NOT NULL DEFAULT 12,
  sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  platform TEXT NOT NULL,
  target_id INTEGER NOT NULL REFERENCES targets(id),
  channel TEXT NOT NULL DEFAULT 'stable',
  token_hash TEXT UNIQUE NOT NULL,
  token_hint TEXT NOT NULL,
  token_enc TEXT,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  last_pull_at TEXT,
  last_pull_ip TEXT,
  pull_count INTEGER NOT NULL DEFAULT 0,
  extra_yaml TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS builds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  policy_sha TEXT NOT NULL,
  snapshot TEXT NOT NULL,
  results TEXT NOT NULL DEFAULT '{}',
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS releases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  build_id INTEGER NOT NULL REFERENCES builds(id),
  channel TEXT NOT NULL,
  action TEXT NOT NULL,
  operator TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pointers (
  channel TEXT PRIMARY KEY,
  build_id INTEGER,
  released_at TEXT,
  operator TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  object_type TEXT NOT NULL DEFAULT '',
  object_id TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS automation_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'scheduled',
  summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS snippets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  category TEXT NOT NULL DEFAULT 'general',
  engine TEXT NOT NULL DEFAULT 'all',
  content TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS base_configs (
  engine TEXT NOT NULL DEFAULT 'stash',
  platform TEXT NOT NULL DEFAULT '',
  device_id INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (engine, platform, device_id)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_offset_hours(hours: float) -> str:
    """当前时间加减若干小时后的 ISO 字符串（用于"早于某时刻"的比较）。"""
    moment = datetime.now(timezone.utc).astimezone() + timedelta(hours=hours)
    return moment.isoformat(timespec="seconds")


class _Conn(sqlite3.Connection):
    """上下文退出时提交/回滚并关闭连接。"""

    def __exit__(self, exc_type, exc, tb):
        super().__exit__(exc_type, exc, tb)
        self.close()


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=15, factory=_Conn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "sources", "filter_unavailable",
                       "filter_unavailable INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "sources", "tested_at", "tested_at TEXT")
        _ensure_column(conn, "sources", "test_results",
                       "test_results TEXT NOT NULL DEFAULT '{}'")
        # 定时抓取/测速：记录最近一次尝试（含失败），避免失败后每个 tick 重试
        _ensure_column(conn, "sources", "last_attempt_at", "last_attempt_at TEXT")
        _ensure_column(conn, "sources", "test_attempt_at", "test_attempt_at TEXT")
        _ensure_column(conn, "sources", "test_interval",
                       "test_interval INTEGER NOT NULL DEFAULT 21600")
        # 本地快照来源：关闭自动抓取，只使用已保存快照
        _ensure_column(conn, "sources", "auto_fetch",
                       "auto_fetch INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "sources", "auto_test",
                       "auto_test INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "rule_providers", "last_attempt_at",
                       "last_attempt_at TEXT")
        # 客户端更新间隔：客户端拉取子资源的周期；0 表示跟随抓取间隔
        _ensure_column(conn, "sources", "client_interval",
                       "client_interval INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "rule_providers", "client_interval",
                       "client_interval INTEGER NOT NULL DEFAULT 0")
        # 引擎平台支持拖动排序
        _ensure_column(conn, "targets", "sort", "sort INTEGER NOT NULL DEFAULT 0")
        # 通道指针记录最近一次发布/回滚的来源，供界面展示“当前版本由谁、何时发布”
        _ensure_column(conn, "pointers", "released_at", "released_at TEXT")
        _ensure_column(conn, "pointers", "operator",
                       "operator TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "pointers", "action",
                       "action TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "pointers", "reason",
                       "reason TEXT NOT NULL DEFAULT ''")
        # 令牌同时保存 Fernet 加密副本：哈希用于校验，密文用于门户与后台重新展示地址
        _ensure_column(conn, "devices", "token_enc", "token_enc TEXT")
        # 门户 PIN 与维护者账号绑定，可按人撤销
        _ensure_column(conn, "users", "portal_pin_hash",
                       "portal_pin_hash TEXT NOT NULL DEFAULT ''")
        # 自定义头像的 MIME；文件在 data/avatars/
        _ensure_column(conn, "users", "avatar_mime",
                       "avatar_mime TEXT NOT NULL DEFAULT ''")
        # load-balance 的分配策略（consistent-hashing / round-robin / sticky-sessions）
        _ensure_column(conn, "proxy_groups", "strategy",
                       "strategy TEXT NOT NULL DEFAULT ''")
        # 策略组引用的本地单节点 ID 列表
        _ensure_column(conn, "proxy_groups", "local_nodes",
                       "local_nodes TEXT NOT NULL DEFAULT '[]'")
        # 分流规则的 no-resolve 修饰符（仅 IP 类规则有效）
        _ensure_column(conn, "rules", "no_resolve",
                       "no_resolve INTEGER NOT NULL DEFAULT 0")
        # 差异配置：策略组与规则可限定适用目标（空 = 全部目标）
        _ensure_column(conn, "proxy_groups", "targets",
                       "targets TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "rules", "targets",
                       "targets TEXT NOT NULL DEFAULT '[]'")
        # 设备级个性化：分发时叠加在该设备目标产物之上
        _ensure_column(conn, "devices", "extra_yaml",
                       "extra_yaml TEXT NOT NULL DEFAULT ''")
        for key, value in config.SETTINGS_DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value)
            )
        _migrate_settings(conn)
        _migrate_base_configs_scope(conn)
        _migrate_base_configs(conn)
        _migrate_build_snapshots(conn)


def _migrate_settings(conn) -> None:
    """把旧的默认间隔（12 小时）迁移到 1 小时；仅改仍等于旧默认的行。"""
    for key in ("profile_update_interval", "auto_build_interval_hours"):
        conn.execute(
            "UPDATE settings SET value=? WHERE key=? AND value='12'",
            (config.SETTINGS_DEFAULTS[key], key),
        )


def _migrate_base_configs_scope(conn) -> None:
    """base_configs 主键演进：engine → (engine, target) → (engine, platform, device_id)。

    作用域最终落在「引擎 + 平台」与「设备」两级；旧的 target 级通过 targets 表
    映射成 platform，找不到对应目标的行直接丢弃（该作用域已不存在）。
    """
    info = list(conn.execute("PRAGMA table_info(base_configs)"))
    if not info:
        return
    cols = {r["name"] for r in info}
    if "target" not in cols:
        conn.execute("ALTER TABLE base_configs ADD COLUMN target TEXT NOT NULL DEFAULT ''")
        info = list(conn.execute("PRAGMA table_info(base_configs)"))
    if "device_id" not in cols:
        conn.execute(
            "ALTER TABLE base_configs ADD COLUMN device_id INTEGER NOT NULL DEFAULT 0")
        info = list(conn.execute("PRAGMA table_info(base_configs)"))
    pk_cols = [r["name"] for r in sorted(
        (x for x in info if x["pk"]), key=lambda x: x["pk"])]
    if pk_cols == ["engine", "platform", "device_id"]:
        return

    target_platform = {
        r["name"]: r["platform"] for r in conn.execute(
            "SELECT name, platform FROM targets")}
    device_platform = {}
    for r in conn.execute("SELECT d.id AS id, t.platform AS platform FROM devices d "
                          "JOIN targets t ON t.id = d.target_id"):
        device_platform[int(r["id"])] = r["platform"]

    conn.execute("DROP TABLE IF EXISTS base_configs_scope_new")
    conn.execute("""CREATE TABLE base_configs_scope_new (
        engine TEXT NOT NULL DEFAULT 'stash',
        platform TEXT NOT NULL DEFAULT '',
        device_id INTEGER NOT NULL DEFAULT 0,
        content TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (engine, platform, device_id))""")
    for row in conn.execute("SELECT engine, target, device_id, content, updated_at "
                             "FROM base_configs"):
        device_id = int(row["device_id"] or 0)
        if device_id:
            platform = device_platform.get(device_id, "")
        else:
            platform = target_platform.get(row["target"] or "", "")
        if not platform:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO base_configs_scope_new"
            "(engine, platform, device_id, content, updated_at) VALUES(?,?,?,?,?)",
            (row["engine"], platform, device_id, row["content"], row["updated_at"]))
    conn.execute("DROP TABLE base_configs")
    conn.execute("ALTER TABLE base_configs_scope_new RENAME TO base_configs")


def _migrate_base_configs(conn) -> None:
    """按引擎写入默认基础配置（已存在的不覆盖）。"""
    from .services import base_config as base_config_service

    # 播种为空覆盖：内置默认才是起点，通用层默认不覆盖任何键
    for engine in base_config_service.ENGINES:
        conn.execute(
            "INSERT OR IGNORE INTO base_configs"
            "(engine, platform, device_id, content, updated_at) "
            "VALUES(?,?,?,?,?)",
            (engine, "", 0, base_config_service.to_yaml({}), now()),
        )


def _migrate_build_snapshots(conn) -> None:
    """构建快照可能含本地节点凭据，逐条加密（幂等）。"""
    from . import security

    rows = conn.execute(
        "SELECT id, snapshot FROM builds WHERE snapshot != '' "
        "AND snapshot NOT LIKE 'enc:v1:%'"
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE builds SET snapshot=? WHERE id=?",
            (security.encrypt_payload(row["snapshot"]), row["id"]),
        )


@contextmanager
def tx():
    """写事务：提交或回滚，连接随上下文关闭。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def one(conn: sqlite3.Connection, sql: str, args=()):
    return conn.execute(sql, args).fetchone()


def all_(conn: sqlite3.Connection, sql: str, args=()):
    return conn.execute(sql, args).fetchall()


def row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def get_setting(conn, key: str, default: str = "") -> str:
    row = one(conn, "SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
