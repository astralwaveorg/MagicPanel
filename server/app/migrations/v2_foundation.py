"""V2 私密资源基础表；不提交调用方事务。"""


def migrate(conn) -> None:
    if not conn.in_transaction:
        raise ValueError("migration_transaction_required")
    conn.execute("""CREATE TABLE IF NOT EXISTS private_blobs (
        blob_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
        material_hmac TEXT NOT NULL, key_version INTEGER NOT NULL,
        ciphertext BLOB NOT NULL, ciphertext_sha256 TEXT NOT NULL,
        size INTEGER NOT NULL CHECK(size>=0), created_at TEXT NOT NULL,
        UNIQUE(kind,material_hmac,key_version)
    )""")
    if 'trusted_upstream_id_key' not in {r[1] for r in conn.execute('PRAGMA table_info(sources)')}:
        conn.execute("ALTER TABLE sources ADD COLUMN trusted_upstream_id_key TEXT NOT NULL DEFAULT ''")
    catalog_schema(conn)
    profile_schema(conn)
    from ..services import node_catalog
    node_catalog.backfill(conn)
    from ..services import node_refs
    node_refs.migrate_refs(conn)
    conn.execute("INSERT OR IGNORE INTO schema_version(key,value) VALUES('v2_private_blobs', '1')")


def catalog_schema(conn):
    statements = (
        """CREATE TABLE IF NOT EXISTS node_catalog (
            node_uid TEXT PRIMARY KEY, origin_key TEXT NOT NULL UNIQUE,
            origin_kind TEXT NOT NULL CHECK(origin_kind IN ('source','local')),
            source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
            local_node_id INTEGER REFERENCES local_nodes(id) ON DELETE SET NULL,
            upstream_id_hmac TEXT, ordinal INTEGER NOT NULL UNIQUE, current_revision INTEGER NOT NULL DEFAULT 0,
            raw_name TEXT NOT NULL, display_name TEXT NOT NULL, emit_name TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
            retired INTEGER NOT NULL DEFAULT 0, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS catalog_state (
            id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS node_revisions (
            node_uid TEXT NOT NULL REFERENCES node_catalog(node_uid), revision INTEGER NOT NULL,
            material_blob_id TEXT NOT NULL REFERENCES private_blobs(blob_id),
            identity_hmac TEXT NOT NULL, material_hmac TEXT NOT NULL, key_version INTEGER NOT NULL,
            public_config_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(node_uid,revision))""",
        """CREATE TABLE IF NOT EXISTS node_aliases (
            node_uid TEXT NOT NULL REFERENCES node_catalog(node_uid), name_kind TEXT NOT NULL,
            name TEXT NOT NULL, revision INTEGER NOT NULL,
            UNIQUE(node_uid,name_kind,name,revision))""",
        """CREATE TABLE IF NOT EXISTS rename_applies (
            preview_digest TEXT PRIMARY KEY, actor_user_id INTEGER NOT NULL REFERENCES users(id),
            applied_catalog_revision INTEGER NOT NULL, applied_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS catalog_issues (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL, origin TEXT NOT NULL,
            candidate_uids TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            UNIQUE(code,origin,candidate_uids,status))""",
    )
    for sql in statements:
        conn.execute(sql)
    conn.execute('INSERT OR IGNORE INTO catalog_state(id,revision) VALUES(1,0)')


def profile_schema(conn):
    for table, fields in (
        ('targets', [('default_runtime_profile', "TEXT NOT NULL DEFAULT 'legacy-v1'"),
                     ('config_revision', 'INTEGER NOT NULL DEFAULT 1')]),
        ('devices', [('runtime_profile', 'TEXT DEFAULT NULL'),
                     ('config_revision', 'INTEGER NOT NULL DEFAULT 1')]),
    ):
        existing = {row[1] for row in conn.execute('PRAGMA table_info(' + table + ')')}
        for name, definition in fields:
            if name not in existing:
                conn.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + name + ' ' + definition)
    conn.execute("INSERT OR IGNORE INTO schema_version(key,value) VALUES('v2_runtime_profiles','1')")
