"""私密 bytes 与调用方事务、密钥生命周期的真实边界。"""
import json
import sqlite3

import pytest


def test_blob_encrypted_and_rolled_back_with_caller(client):
    from app import db
    from app.services.resource_store import put_private, get_private
    with db.tx() as conn:
        ref = put_private(conn, "node-material", b"example-test-password\x00\xff")
        assert get_private(conn, ref["blob_id"]) == b"example-test-password\x00\xff"
        raw = conn.execute("SELECT ciphertext FROM private_blobs WHERE blob_id=?",
                           (ref["blob_id"],)).fetchone()[0]
        assert isinstance(raw, bytes) and b"example-test-password" not in raw
    with pytest.raises(RuntimeError):
        with db.tx() as conn:
            doomed = put_private(conn, "provider", b"example-new-payload")
            raise RuntimeError("rollback-fixture")
    with db.connect() as conn:
        assert conn.execute("SELECT 1 FROM private_blobs WHERE blob_id=?",
                            (doomed["blob_id"],)).fetchone() is None


def test_blob_deduplicates_by_kind_and_requires_transaction(client):
    from app import db
    from app.services.resource_store import put_private
    with db.connect() as conn:
        with pytest.raises(ValueError, match="private_blob_transaction_required"):
            put_private(conn, "rule", b"same")
    with db.tx(immediate=True) as conn:
        first = put_private(conn, "rule", b"same")
        assert put_private(conn, "rule", b"same") == first
        assert put_private(conn, "provider", b"same")["blob_id"] != first["blob_id"]
        assert conn.execute("SELECT COUNT(*) FROM private_blobs").fetchone()[0] == 2


@pytest.mark.parametrize("damage", ["ciphertext", "digest", "size", "hmac", "version"])
def test_blob_corruption_only_returns_safe_error(client, damage):
    from app import db
    from app.services import resource_store
    with db.tx(immediate=True) as conn:
        ref = resource_store.put_private(conn, "rule", b"fixture-secret")
        column, value = {"ciphertext": ("ciphertext", b"bad-secret"),
                         "digest": ("ciphertext_sha256", "0" * 64),
                         "size": ("size", 999), "hmac": ("material_hmac", "0" * 64),
                         "version": ("key_version", 99)}[damage]
        conn.execute(f"UPDATE private_blobs SET {column}=? WHERE blob_id=?", (value, ref["blob_id"]))
        with pytest.raises(ValueError, match="^private_blob_corrupt$"):
            resource_store.get_private(conn, ref["blob_id"])


def test_blob_rejects_invalid_input_and_oversize(client, monkeypatch):
    from app import db
    from app.services import resource_store
    monkeypatch.setattr(resource_store, "MAX_PRIVATE_BYTES", 4)
    with db.tx(immediate=True) as conn:
        for kind, body in [("unknown", b"x"), ("rule", "x"), ("rule", b"12345")]:
            with pytest.raises(ValueError, match="private_blob_invalid"):
                resource_store.put_private(conn, kind, body)
        assert conn.execute("SELECT COUNT(*) FROM private_blobs").fetchone()[0] == 0


def test_derived_keys_have_fixed_domains_and_versions(client):
    from app import security
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    master = bytes(range(32))
    expected = HKDF(algorithm=hashes.SHA256(), length=32,
                    salt=b"MagicPanel/v2/key-derivation", info=b"v1:node-identity").derive(master)
    assert security.derive_subkey(master, purpose="node-identity") == expected
    assert len({security.derive_subkey(master, purpose=p) for p in (
        "private-blob-hmac", "node-identity", "backup-manifest-mac", "backup-archive-encryption")}) == 4
    for args in [(b"short", "node-identity", 1), (master, "node-identity", 2), (master, "", 1)]:
        with pytest.raises(ValueError):
            security.derive_subkey(args[0], purpose=args[1], version=args[2])


def test_missing_key_never_replaced_during_reinitialization(client):
    from app import config, db, security
    from app.services import resource_store
    with db.tx(immediate=True) as conn:
        resource_store.put_private(conn, "rule", b"fixture-secret")
    config.SECRET_KEY_PATH.unlink()
    security._fernet_cache.clear()
    with pytest.raises(security.DecryptError, match="^key_required$"):
        db.init_db()
    assert not config.SECRET_KEY_PATH.exists()
    with pytest.raises(security.DecryptError, match="^key_required$"):
        security.encrypt_text("must-not-create")


def test_fresh_directory_key_is_private_and_existing_directory_requires_key(client, tmp_path, monkeypatch):
    from app import config, security
    fresh = tmp_path / "fresh"
    monkeypatch.setattr(config, "DATA_DIR", fresh)
    monkeypatch.setattr(config, "SECRET_KEY_PATH", fresh / "secret.key")
    assert len(security.load_master_material(require_existing=False)) == 32
    assert (fresh / "secret.key").is_file()
    (fresh / "secret.key").unlink()
    (fresh / "leftover.db").write_bytes(b"existing")
    with pytest.raises(security.DecryptError, match="^key_required$"):
        security.load_master_material(require_existing=False)
    assert not (fresh / "secret.key").exists()


def test_logical_blob_codec_roundtrips_only_registered_blob_columns(client):
    from app import db
    from app.services import backups, resource_store
    with db.tx(immediate=True) as conn:
        ref = resource_store.put_private(conn, "rule", b"\x00\xffmrs-data")
        payload = json.loads(json.dumps(backups.export_logical(conn)))
        encoded = payload["tables"]["private_blobs"][0]["ciphertext"]
        assert encoded["encoding"] == "base64"
        backups.restore_logical(conn, payload)
        assert resource_store.get_private(conn, ref["blob_id"]) == b"\x00\xffmrs-data"
        payload["tables"]["settings"][0]["value"] = encoded
        with pytest.raises(ValueError, match="backup_invalid"):
            backups.restore_logical(conn, payload)
