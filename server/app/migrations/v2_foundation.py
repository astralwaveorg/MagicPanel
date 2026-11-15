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
    conn.execute("INSERT OR IGNORE INTO schema_version(key,value) VALUES('v2_private_blobs', '1')")
