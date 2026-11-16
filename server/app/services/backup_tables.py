"""备份表的唯一注册表；父表先恢复，清空时反序执行。"""

BACKUP_TABLES = (
    "users", "sources", "rule_providers", "local_nodes", "variants", "private_blobs",
    "node_catalog", "catalog_state", "node_revisions", "node_aliases", "catalog_issues",
    "targets", "snippets", "devices", "base_configs", "proxy_groups", "rules",
    "builds", "releases", "repo_migrations", "automation_runs", "settings",
    "schema_version", "probe_observers", "probe_jobs", "probe_items", "probe_results",
    "probe_reservations", "probe_paths", "probe_adapter_health", "routing_plans",
    "resource_revisions", "build_manifests", "build_resources", "resource_aliases",
    "artifact_leases", "distribution_envelopes", "deployment_bundles", "owner_receipts",
    "resource_gc_queue", "release_state", "operation_requests",
    "probe_schedule_state", "probe_recovery_windows",
)

# 历史导出唯一缺少的长期表。只允许 v1 使用这些安全缺省值。
LEGACY_OPTIONAL_TABLES = frozenset({
    "node_catalog", "catalog_state", "node_revisions", "node_aliases", "catalog_issues",
    "variants", "repo_migrations", "automation_runs", "schema_version", "private_blobs",
})

PRESERVED_TABLES = ("audit",)
RESET_TABLES = ("sessions", "rename_applies")

# 只为真实 SQLite BLOB 列注册 codec；普通 JSON 对象不作隐式 bytes。
BLOB_COLUMNS = frozenset({("private_blobs", "ciphertext")})

# 按持久化契约识别密文；payload 仅在该已知字段内兼容历史明文。
ENCRYPTED_COLUMNS = {
    ("sources", "url_enc"): "fernet",
    ("sources", "proxy_url_enc"): "fernet",
    ("sources", "snapshot_enc"): "fernet",
    ("sources", "headers_enc"): "fernet",
    ("rule_providers", "proxy_url_enc"): "fernet",
    ("local_nodes", "params_enc"): "fernet",
    ("local_nodes", "extra_yaml_enc"): "fernet",
    ("snippets", "proxy_url_enc"): "fernet",
    ("devices", "token_enc"): "fernet",
    ("builds", "snapshot"): "payload",
}
ENCRYPTED_SETTINGS = {
    "deps_private_key_enc": "fernet",
    "deps_token_enc": "fernet",
    "webdav_password_enc": "payload",
}


def registered_tables(conn) -> tuple[str, ...]:
    actual = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    known = set(BACKUP_TABLES) | set(PRESERVED_TABLES) | set(RESET_TABLES)
    if actual - known or set(BACKUP_TABLES) - actual:
        raise ValueError("backup_schema_unregistered")
    return BACKUP_TABLES


def reset_tables(conn) -> tuple[str, ...]:
    return tuple(table for table in RESET_TABLES if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
