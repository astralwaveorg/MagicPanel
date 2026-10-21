"""SQLite 数据层：连接、事务与建表。单实例单写入，WAL 模式。"""
import json
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
  node_type TEXT NOT NULL DEFAULT '本地',
  protocol TEXT NOT NULL,
  server TEXT NOT NULL,
  port INTEGER NOT NULL,
  params_enc TEXT NOT NULL DEFAULT '',
  extra_yaml_enc TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  test_status TEXT NOT NULL DEFAULT '',
  test_delay INTEGER NOT NULL DEFAULT 0,
  tested_at TEXT,
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
  env TEXT NOT NULL DEFAULT 'production',
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
CREATE TABLE IF NOT EXISTS builds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'BUILT',
  verify_status TEXT NOT NULL DEFAULT 'success',
  policy_sha TEXT NOT NULL,
  snapshot TEXT NOT NULL,
  results TEXT NOT NULL DEFAULT '{}',
  note TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  published_by TEXT NOT NULL DEFAULT '',
  publish_reason TEXT NOT NULL DEFAULT '',
  status_updated_at TEXT
);
CREATE TABLE IF NOT EXISTS releases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  build_id INTEGER NOT NULL REFERENCES builds(id),
  env TEXT NOT NULL,
  action TEXT NOT NULL,
  operator TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS schema_version (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

-- 状态机约束：生产版本与测试版本全局各至多一条。
-- 部分唯一索引（status 为常量时对 id 建唯一索引）把"同一环境双活"
-- 从应用层校验升级为数据库层强制，应用层校验被并发绕过时仍不会写坏。
CREATE UNIQUE INDEX IF NOT EXISTS idx_builds_production
  ON builds(id) WHERE status='PRODUCTION';
CREATE UNIQUE INDEX IF NOT EXISTS idx_builds_testing
  ON builds(id) WHERE status='TESTING';
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


def _ensure_column(conn, table: str, column: str, ddl: str) -> bool:
    """补列；返回 True 表示这次真的加了列（用于一次性初始化）。"""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        return True
    return False


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
        _ensure_column(conn, "proxy_groups", "local_first",
                       "local_first INTEGER NOT NULL DEFAULT 0")
        if _ensure_column(conn, "devices", "sort", "sort INTEGER NOT NULL DEFAULT 0"):
            # 首次加列时按 id 初始化顺序：全为 0 的排序值没有区分度，
            # 拖拽排序会"排了但没生效"。
            conn.execute("UPDATE devices SET sort = id WHERE sort = 0")
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
        _migrate_release_state_machine(conn)
        _migrate_releases_env(conn)
        _migrate_local_node_type(conn)
        _migrate_local_node_test(conn)
        _migrate_verification_wording(conn)
        _migrate_base_config_defaults(conn)
        _migrate_device_scope(conn)


def _migrate_release_state_machine(conn) -> None:
    """通道双轨 → 单一生命周期状态机（一次性迁移）。

    旧模型：builds.status 存校验结果，"发布到哪里"由 pointers 表的
    stable / candidate 两个指针决定，因此同一个构建可以同时占两个通道。

    新模型：builds.status 只存生命周期状态（BUILT / TESTING /
    PRODUCTION / OFFLINE），校验结果移到 verify_status，pointers 表废弃。

    迁移规则：
      * 旧 status（success/failed/building）→ verify_status；
      * stable 指针 → PRODUCTION，candidate 指针 → TESTING；
        同一构建同时命中两个指针时生产优先（候选指针作废）；
      * 曾在 releases 出现但当前未生效的构建 → OFFLINE；
      * 从未发布过的构建 → BUILT；
      * 指针上的发布元数据（时间/操作人/说明）上移到 builds 行。
    """
    done = one(conn, "SELECT value FROM schema_version "
                     "WHERE key='release_state_v1'")
    if done:
        return

    def has_table(name: str) -> bool:
        return bool(one(conn, "SELECT name FROM sqlite_master "
                              "WHERE type='table' AND name=?", (name,)))

    def columns(table: str) -> set[str]:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}

    # --- builds：拆分校验结果与生命周期状态 ---
    build_cols = columns("builds")
    _ensure_column(conn, "builds", "verify_status",
                   "verify_status TEXT NOT NULL DEFAULT 'success'")
    _ensure_column(conn, "builds", "published_at", "published_at TEXT")
    _ensure_column(conn, "builds", "published_by",
                   "published_by TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "builds", "publish_reason",
                   "publish_reason TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "builds", "status_updated_at", "status_updated_at TEXT")
    if "verify_status" not in build_cols:
        # 新加的列：先把旧 status 当作校验结果搬过去
        conn.execute("UPDATE builds SET verify_status=status "
                     "WHERE status IN ('building','success','failed')")
    else:
        conn.execute("UPDATE builds SET verify_status=status "
                     "WHERE verify_status='success' "
                     "AND status IN ('building','success','failed')")

    # --- pointers → 生命周期状态 ---
    pointer_rows = []
    if has_table("pointers"):
        pointer_rows = [dict(r) for r in conn.execute("SELECT * FROM pointers")]
    # 一个构建可能同时占着两个指针（双轨模型的老毛病）：
    # 生产优先，候选指针作废，测试环境迁移后为空。
    pointer_state: dict[int, tuple[str, dict]] = {}
    for row in pointer_rows:
        if not row.get("build_id"):
            continue
        bid = int(row["build_id"])
        status = "PRODUCTION" if row.get("channel") == "stable" else "TESTING"
        if bid in pointer_state and pointer_state[bid][0] == "PRODUCTION":
            continue
        pointer_state[bid] = (status, row)
    for bid, (status, row) in pointer_state.items():
        conn.execute(
            "UPDATE builds SET status=?, published_at=?, published_by=?, "
            "publish_reason=?, status_updated_at=? WHERE id=?",
            (status, row.get("released_at"), row.get("operator") or "",
             row.get("reason") or "", row.get("released_at") or now(), bid),
        )
    # 未被指针占用、但发布过的构建 → 已下线归档
    conn.execute(
        "UPDATE builds SET status='OFFLINE', status_updated_at=COALESCE(status_updated_at, ?) "
        "WHERE status NOT IN ('PRODUCTION','TESTING') AND id IN "
        "(SELECT DISTINCT build_id FROM releases WHERE build_id IS NOT NULL)",
        (now(),),
    )
    # 从未发布过的构建 → 已构建
    conn.execute(
        "UPDATE builds SET status='BUILT' "
        "WHERE status NOT IN ('PRODUCTION','TESTING','OFFLINE')")
    # 迁移前 status 里残留的旧校验值统一纠正
    conn.execute(
        "UPDATE builds SET status='BUILT' "
        "WHERE status NOT IN ('BUILT','TESTING','PRODUCTION','OFFLINE')")

    # --- releases 表结构在 v2 里重建（见 _migrate_releases_env）---

    # --- devices：channel → env ---
    device_cols = columns("devices")
    if "env" not in device_cols:
        conn.execute("ALTER TABLE devices ADD COLUMN env TEXT "
                     "NOT NULL DEFAULT 'production'")
    if "channel" in device_cols:
        conn.execute(
            "UPDATE devices SET env = CASE channel "
            "WHEN 'candidate' THEN 'testing' ELSE 'production' END")
        conn.execute("ALTER TABLE devices DROP COLUMN channel")
    else:
        conn.execute("UPDATE devices SET env='production' WHERE env=''")

    # --- settings：auto_publish_channel → auto_publish_env ---
    old = one(conn, "SELECT value FROM settings WHERE key='auto_publish_channel'")
    if old:
        env = "testing" if old["value"] == "candidate" else "production"
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)",
                     ("auto_publish_env", env))
        conn.execute("DELETE FROM settings WHERE key='auto_publish_channel'")

    # --- 废弃 pointers 表 ---
    if has_table("pointers"):
        conn.execute("DROP TABLE pointers")

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_builds_production "
                 "ON builds(id) WHERE status='PRODUCTION'")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_builds_testing "
                 "ON builds(id) WHERE status='TESTING'")
    conn.execute("INSERT OR REPLACE INTO schema_version(key, value) "
                 "VALUES('release_state_v1', ?)", (now(),))


def _migrate_releases_env(conn) -> None:
    """releases 表重建：channel → env，并去掉旧的 NOT NULL 列。

    旧表的 channel 列是 NOT NULL 且没有默认值：只加 env 列的话，
    之后写发布历史会因缺 channel 而整条 INSERT 失败。
    因此这里整表重建，一次到位。
    """
    done = one(conn, "SELECT value FROM schema_version "
                     "WHERE key='release_state_v2'")
    if done:
        return
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(releases)")}
    if not cols:
        return
    conn.execute("DROP TABLE IF EXISTS releases_env_new")
    conn.execute("""CREATE TABLE releases_env_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        build_id INTEGER NOT NULL REFERENCES builds(id),
        env TEXT NOT NULL,
        action TEXT NOT NULL,
        operator TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL)""")
    if "env" in cols:
        # 已有 env：按旧值归一（半迁移库里可能还存着 stable / candidate）
        conn.execute(
            "INSERT INTO releases_env_new(id, build_id, env, action, operator, "
            "reason, created_at) SELECT id, build_id, "
            "CASE env WHEN 'stable' THEN 'production' "
            "WHEN 'candidate' THEN 'testing' "
            "WHEN 'testing' THEN 'testing' ELSE 'production' END, "
            "CASE action WHEN 'promote' THEN 'publish' ELSE action END, "
            "operator, reason, created_at FROM releases")
    else:
        conn.execute(
            "INSERT INTO releases_env_new(id, build_id, env, action, operator, "
            "reason, created_at) SELECT id, build_id, "
            "CASE channel WHEN 'candidate' THEN 'testing' ELSE 'production' END, "
            "CASE action WHEN 'promote' THEN 'publish' ELSE action END, "
            "operator, reason, created_at FROM releases")
    conn.execute("DROP TABLE releases")
    conn.execute("ALTER TABLE releases_env_new RENAME TO releases")
    conn.execute("INSERT OR REPLACE INTO schema_version(key, value) "
                 "VALUES('release_state_v2', ?)", (now(),))


# 本地节点历史上用 [单] 前缀标注（只拼在产物里，也可能被手工写进名称）。
# 类型化之后统一用「名称 (类型)」，名称本身要还原成纯名称。
_LEGACY_NAME_PREFIXES = ("[单]", "[本地]", "[单节点]", "【单】", "【本地】")


def _migrate_local_node_type(conn) -> None:
    """本地节点：补 node_type 列，并把历史名称里的旧前缀清理掉。"""
    done = one(conn, "SELECT value FROM schema_version "
                     "WHERE key='local_node_type_v1'")
    if done:
        return
    _ensure_column(conn, "local_nodes", "node_type",
                   "node_type TEXT NOT NULL DEFAULT '本地'")
    conn.execute("UPDATE local_nodes SET node_type='本地' "
                 "WHERE node_type IS NULL OR node_type=''")
    for row in conn.execute("SELECT id, name FROM local_nodes"):
        name = (row["name"] or "").strip()
        cleaned = name
        for prefix in _LEGACY_NAME_PREFIXES:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        if cleaned == name or not cleaned:
            continue
        # 清理后可能与另一个节点同名：保留原名，不静默丢数据
        clash = one(conn, "SELECT id FROM local_nodes WHERE name=? AND id!=?",
                    (cleaned, row["id"]))
        if clash:
            continue
        conn.execute("UPDATE local_nodes SET name=? WHERE id=?",
                     (cleaned, row["id"]))
    conn.execute("INSERT OR REPLACE INTO schema_version(key, value) "
                 "VALUES('local_node_type_v1', ?)", (now(),))


def _migrate_local_node_test(conn) -> None:
    """本地节点补测速结果列（最近一次测速的状态与延迟）。"""
    done = one(conn, "SELECT value FROM schema_version "
                     "WHERE key='local_node_test_v1'")
    if done:
        return
    _ensure_column(conn, "local_nodes", "test_status",
                   "test_status TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "local_nodes", "test_delay",
                   "test_delay INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "local_nodes", "tested_at", "tested_at TEXT")
    conn.execute("INSERT OR REPLACE INTO schema_version(key, value) "
                 "VALUES('local_node_test_v1', ?)", (now(),))


def _migrate_device_scope(conn) -> None:
    """策略组与规则支持"适用设备"维度。

    引擎平台 = 引擎 + 平台，同一对只能有一个；个性化（谁走哪条规则、
    谁用哪个策略组）落在设备上，而不是再复制一份引擎平台。
    """
    done = one(conn, "SELECT value FROM schema_version "
                     "WHERE key='device_scope_v1'")
    if done:
        return
    _ensure_column(conn, "rules", "devices", "devices TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "proxy_groups", "devices",
                   "devices TEXT NOT NULL DEFAULT '[]'")
    conn.execute("INSERT OR REPLACE INTO schema_version(key, value) "
                 "VALUES('device_scope_v1', ?)", (now(),))


def _migrate_base_config_defaults(conn) -> None:
    """引擎默认补全后，清掉各层里与新默认重复的覆盖。

    引擎默认配置按官方文档补全后，原来堆在"引擎平台配置 / 设备独立配置"
    里的通用键就变成了重复内容。这里重算每层的差异并写回：
    **每层实际生效的值保持不变**，只是把与上层相同的键删掉。
    """
    done = one(conn, "SELECT value FROM schema_version "
                     "WHERE key='base_defaults_full_v1'")
    if done:
        return
    from .services import base_config as base_config_service

    # 补全前的默认：stash 是 4 键精简版，mihomo 是兼容现状
    old_defaults = {
        "stash": {
            "mode": "rule", "log-level": "warning", "ipv6": False,
            base_config_service.PANEL_DIRECT_KEY: True,
        },
        "mihomo": {
            "mixed-port": 7890, "allow-lan": False, "mode": "rule",
            "log-level": "warning", "ipv6": False,
            "profile": {"store-selected": True, "store-fake-ip": True},
            base_config_service.PANEL_DIRECT_KEY: True,
        },
    }
    docs: dict = {}
    for row in all_(conn, "SELECT engine, platform, device_id, content "
                          "FROM base_configs"):
        key = (row["engine"], row["platform"], int(row["device_id"] or 0))
        try:
            doc = base_config_service.parse_content(row["content"] or "")
        except ValueError:
            doc = {}
        docs[key] = doc
    devices = all_(conn, "SELECT id, target_id FROM devices")
    target_of = {int(d["id"]): int(d["target_id"]) for d in devices}
    targets = all_(conn, "SELECT id, engine, platform FROM targets")
    target_info = {int(t["id"]): (t["engine"], t["platform"]) for t in targets}

    def save(engine: str, platform: str, device_id: int, overlay: dict) -> None:
        key = (engine, platform, device_id)
        content = base_config_service.to_yaml(overlay) if overlay else ""
        if key in docs and not overlay:
            conn.execute("DELETE FROM base_configs WHERE engine=? AND platform=? "
                         "AND device_id=?", (engine, platform, device_id))
        else:
            conn.execute(
                "INSERT INTO base_configs(engine, platform, device_id, content, "
                "updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(engine, platform, device_id) DO UPDATE SET "
                "content=excluded.content, updated_at=excluded.updated_at",
                (engine, platform, device_id, content, now()))

    for engine in base_config_service.ENGINES:
        old_default = old_defaults[engine]
        new_default = base_config_service.default_doc(engine)
        # 引擎默认层：生效值不变，只去掉与新默认重复的键
        builtin_old = base_config_service.merge_docs(
            old_default, docs.get((engine, "", 0), {}))
        builtin_overlay = base_config_service.diff_overlay(new_default, builtin_old)
        save(engine, "", 0, builtin_overlay)
        platforms = sorted({p for (e, p, d) in docs if e == engine and p})
        for platform in platforms:
            plat_old = base_config_service.merge_docs(
                builtin_old, docs.get((engine, platform, 0), {}))
            plat_overlay = base_config_service.diff_overlay(builtin_old, plat_old)
            save(engine, platform, 0, plat_overlay)
            for did, tid in target_of.items():
                if target_info.get(tid, ("", ""))[1] != platform:
                    continue
                dev_old = base_config_service.merge_docs(
                    plat_old, docs.get((engine, platform, did), {}))
                dev_overlay = base_config_service.diff_overlay(plat_old, dev_old)
                save(engine, platform, did, dev_overlay)
    conn.execute("INSERT OR REPLACE INTO schema_version(key, value) "
                 "VALUES('base_defaults_full_v1', ?)", (now(),))


def _migrate_verification_wording(conn) -> None:
    """校验文案只报发布结果与校验状态，不再提“实机待验收”。

    面板只负责构建与发布，客户端上的实机行为不是发布环节关心的事；
    历史构建里已存的旧文案一并改掉，避免同一个页面两种说法。
    """
    done = one(conn, "SELECT value FROM schema_version "
                     "WHERE key='verification_wording_v1'")
    if done:
        return
    rows = all_(conn, "SELECT id, results FROM builds WHERE results LIKE '%实机%'")
    for row in rows:
        try:
            data = json.loads(row["results"] or "{}")
        except (TypeError, ValueError):
            continue
        changed = False
        for item in data.values():
            if not isinstance(item, dict):
                continue
            text = item.get("verification") or ""
            new_text = (text.replace("核心校验通过（mihomo -t），实机行为待验收",
                                     "核心校验通过（mihomo -t）")
                        .replace("静态通过（未做核心校验），实机待验收",
                                 "静态通过（未做核心校验）")
                        .replace("静态通过，实机待验收", "静态通过"))
            if new_text != text:
                item["verification"] = new_text
                changed = True
        if changed:
            conn.execute("UPDATE builds SET results=? WHERE id=?",
                         (json.dumps(data, ensure_ascii=False), row["id"]))
    conn.execute("INSERT OR REPLACE INTO schema_version(key, value) "
                 "VALUES('verification_wording_v1', ?)", (now(),))


def _migrate_settings(conn) -> None:
    """把旧的默认间隔（12 小时）迁移到 1 小时。

    只在**首次升级时**执行一次：每次启动都改的话，用户后来特意设回
    12 小时会被无声改回 1 小时。版本记录在 schema_version 表里。
    """
    done = one(conn, "SELECT value FROM schema_version WHERE key='settings_v1'")
    if done:
        return
    for key in ("profile_update_interval", "auto_build_interval_hours"):
        conn.execute(
            "UPDATE settings SET value=? WHERE key=? AND value='12'",
            (config.SETTINGS_DEFAULTS[key], key),
        )
    conn.execute(
        "INSERT OR REPLACE INTO schema_version(key, value) VALUES('settings_v1', ?)",
        (now(),),
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
def tx(immediate: bool = False):
    """写事务：提交或回滚，连接随上下文关闭。

    immediate=True 时用 BEGIN IMMEDIATE 立即取写锁：
    状态切换（发布/下线/回滚）必须串行执行，否则两个并发请求
    可能各自读到"旧版本"并同时写入，出现同一环境两条生效记录。
    """
    conn = connect()
    if immediate:
        conn.isolation_level = None      # 关闭 Python 的隐式事务，改用显式 BEGIN
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
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


class UniqueViolation(Exception):
    """唯一约束冲突（并发下"先查后插"会同时通过检查）。"""


def insert_unique(conn, sql: str, args=(), message: str = "记录已存在"):
    """插入并把唯一约束冲突转成可读异常。

    "先 SELECT 查重再 INSERT"在并发下并不安全：两个请求都能通过检查，
    后一个 INSERT 会抛 IntegrityError，客户端收到 500（语义错误）。
    """
    try:
        cur = conn.execute(sql, args)
        return cur
    except sqlite3.IntegrityError as exc:
        raise UniqueViolation(message) from exc


def reorder_subset(conn, table: str, ids: list[int]) -> int:
    """按给定顺序重排这些行，其它行保持原位。

    列表分页后，界面只拿得到当前页的 id；此时"整表顺序"的语义不成立，
    但"这几项之间按拖动的顺序排"是明确的——按它们现有的 sort 值
    重新分配即可，不影响其它行。
    """
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    rows = all_(conn, f"SELECT id, sort FROM {table} WHERE id IN ({marks})",
                list(ids))
    if len(rows) != len(set(ids)):
        return 0
    values = sorted(r["sort"] for r in rows)
    for index, rid in enumerate(ids):
        conn.execute(f"UPDATE {table} SET sort=? WHERE id=?", (values[index], rid))
    return len(ids)


def paged(conn, table: str, where: str = "", args=(), order: str = "id",
          limit: int = 50, offset: int = 0, columns: str = "*") -> dict:
    """分页查询（order 传排序字段，如 "sort, id" 或 "id DESC"）。"""
    """分页查询：返回 {items, total, limit, offset}。

    列表接口一律带上分页：几百条规则/组全量返回会让面板打开变慢，
    也让"翻到第 200 条"这种操作根本做不到。
    """
    limit = min(max(int(limit), 1), 500)
    offset = max(int(offset), 0)
    total = one(conn, f"SELECT COUNT(*) AS c FROM {table} {where}", args)["c"]
    order_sql = f"ORDER BY {order}" if order else ""
    rows = all_(
        conn,
        f"SELECT {columns} FROM {table} {where} {order_sql} LIMIT ? OFFSET ?",
        list(args) + [limit, offset],
    )
    return {
        "items": [row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
