"""备份表的唯一注册表；父表先恢复，清空时反序执行。"""

BACKUP_TABLES = (
    "users", "sources", "rule_providers", "local_nodes", "variants",
    "targets", "snippets", "devices", "base_configs", "proxy_groups", "rules",
    "builds", "releases", "repo_migrations", "automation_runs", "settings",
    "schema_version",
)

# 历史导出唯一缺少的长期表。只允许 v1 使用这些安全缺省值。
LEGACY_OPTIONAL_TABLES = frozenset({
    "variants", "repo_migrations", "automation_runs", "schema_version",
})

PRESERVED_TABLES = ("audit",)
RESET_TABLES = ("sessions", "rename_applies")


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
