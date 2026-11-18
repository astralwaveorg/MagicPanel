"""加密完整归档从独立 fixture 目录恢复，不接触运行目录。"""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from v2_helpers import admin, ordering


def archive_fixture(client, tmp_path):
    from app import config, db
    from app.services import backups, resource_store
    headers = admin(client)
    assert client.post("/api/v1/groups", headers=headers, json={
        "name": "kept", "type": "select", "proxies": ["DIRECT"]}).status_code == 201
    assert client.post("/api/v1/rules", headers=headers, json={
        "type": "MATCH", "target": "kept"}).status_code == 201
    assert client.post("/api/v1/variants", headers=headers, json={
        "name": "恢复测试", "copy_from": 0}).status_code == 201
    material = b"proxies:\n  - password: example-build-plaintext-marker\n"
    build = config.DATA_DIR / "builds/41/fixture.yaml"
    build.parent.mkdir(parents=True)
    build.write_bytes(material)
    extra = {"avatars/1.png": b"fixture-avatar", "deps/rule-repo/rule/magic-test.yaml": b"payload: []\n",
             "deps/rule-repo/.git/HEAD": b"ref: refs/heads/main\n",
             "bin/mihomo": b"fixture-core", "core-work/geoip.dat": b"fixture-geo",
             "core-work/country.mmdb": b"fixture-mmdb", "deps/.mp_key": b"must-exclude-key",
             "core-work/config.yaml": b"exclude-ephemeral-core-config", "builds/999/tmp.yaml": b"unfinished"}
    for path, content in extra.items():
        target = config.DATA_DIR / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (config.DATA_DIR / "bin/mihomo").chmod(0o700)
    with db.tx(immediate=True) as conn:
        ref = resource_store.put_private(conn, "rule", b"\x00\xffmrs-fixture")
        results = {"fixture": {"ok": True, "size": len(material),
                               "sha256": hashlib.sha256(material).hexdigest()}}
        conn.execute("INSERT INTO builds(id,created_at,policy_sha,snapshot,results) VALUES(41,?,?,?,?)",
                     (db.now(), "fixture", "{}", json.dumps(results)))
        conn.execute("INSERT INTO audit(at,actor,action) VALUES(?, 'fixture', '历史证据')", (db.now(),))
        before = ordering(conn)
    archive = tmp_path / "fixture.mpbackup"
    with db.connect() as conn:
        report = backups.create_archive(conn, archive, include_runtime=True, include_history=True)
    return archive, ref, before, material, report


def test_archive_restores_private_material_variants_files_and_sessions(client, tmp_path, monkeypatch):
    from app import config, db, security
    from app.services import backups, resource_store
    archive, ref, before, material, result = archive_fixture(client, tmp_path)
    assert material not in archive.read_bytes()
    assert config.SECRET_KEY_PATH.read_bytes() not in archive.read_bytes()
    assert b"must-exclude-key" not in archive.read_bytes()
    destination = tmp_path / "restored"
    report = backups.restore_archive(archive, destination, key_path=config.SECRET_KEY_PATH)
    assert report["status"] == "VERIFIED"
    restored = sqlite3.connect(destination / "magicpanel.db")
    restored.row_factory = sqlite3.Row
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("PRAGMA foreign_key_check").fetchone() is None
        assert restored.execute("SELECT COUNT(*) FROM variants").fetchone()[0] == 2
        assert ordering(restored) == before
        assert restored.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert restored.execute("SELECT COUNT(*) FROM audit WHERE action='历史证据'").fetchone()[0] == 1
        monkeypatch.setattr(config, "SECRET_KEY_PATH", destination / "secret.key")
        security._fernet_cache.clear()
        assert resource_store.get_private(restored, ref["blob_id"]) == b"\x00\xffmrs-fixture"
    finally:
        restored.close()
    assert (destination / "builds/41/fixture.yaml").read_bytes() == material
    assert (destination / "deps/rule-repo/.git/HEAD").read_bytes() == b"ref: refs/heads/main\n"
    assert (destination / "avatars/1.png").read_bytes() == b"fixture-avatar"
    assert (destination / "bin/mihomo").read_bytes() == b"fixture-core"
    assert (destination / "core-work/geoip.dat").read_bytes() == b"fixture-geo"
    assert (destination / "core-work/country.mmdb").read_bytes() == b"fixture-mmdb"
    assert (destination / "deps/rule-repo/rule/magic-test.yaml").read_bytes() == b"payload: []\n"
    assert not (destination / "deps/.mp_key").exists()
    assert not (destination / "core-work/config.yaml").exists()
    assert not (destination / "builds/999").exists()
    assert not list(destination.glob(".*plaintext*"))
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


@pytest.mark.parametrize("damage", ["wrong_key", "tag", "header", "cut_tag", "cut_middle", "empty", "legacy"])
def test_archive_authentication_failure_never_extracts_or_changes_source(client, tmp_path, damage):
    from app import config
    from app.services import backups
    from cryptography.fernet import Fernet
    archive, _, _, _, _ = archive_fixture(client, tmp_path)
    original = archive.read_bytes()
    key = config.SECRET_KEY_PATH
    if damage == "wrong_key":
        key = tmp_path / "other.key"
        key.write_bytes(Fernet.generate_key())
    else:
        content = {"tag": original[:-1] + bytes([original[-1] ^ 1]),
                   "header": b"X" + original[1:], "cut_tag": original[:-4],
                   "cut_middle": original[:len(original)//2], "empty": b"",
                   "legacy": b"SQLite format 3\x00"}[damage]
        archive = tmp_path / "damaged.mpbackup"
        archive.write_bytes(content)
    destination = tmp_path / "rejected"
    with pytest.raises(ValueError, match="^archive_(authentication_failed|invalid)$"):
        backups.restore_archive(archive, destination, key_path=key)
    assert not destination.exists()
    assert (tmp_path / "fixture.mpbackup").read_bytes() == original
    assert not list(tmp_path.glob(".mp-restore-*"))


def test_archive_rejects_busy_connection_existing_target_and_missing_key(client, tmp_path):
    from app import config, db
    from app.services import backups
    archive, _, _, _, _ = archive_fixture(client, tmp_path)
    with db.tx(immediate=True) as conn:
        with pytest.raises(ValueError, match="archive_requires_idle_connection"):
            backups.create_archive(conn, tmp_path / "busy.mpbackup", include_history=True)
    destination = tmp_path / "exists"
    destination.mkdir()
    (destination / "keep").write_text("kept")
    with pytest.raises(ValueError, match="archive_destination_exists"):
        backups.restore_archive(archive, destination, key_path=config.SECRET_KEY_PATH)
    assert (destination / "keep").read_text() == "kept"
    with pytest.raises(ValueError, match="key_required"):
        backups.restore_archive(archive, tmp_path / "missing-key", key_path=tmp_path / "absent.key")
    assert not (tmp_path / "absent.key").exists()


def test_real_posix_archive_permissions(client, tmp_path):
    import os
    import stat
    if os.name != "posix":
        pytest.skip("POSIX mode 在 WSL 独立执行")
    from app import config
    from app.services import backups
    archive, _, _, _, _ = archive_fixture(client, tmp_path)
    destination = tmp_path / "private"
    backups.restore_archive(archive, destination, key_path=config.SECRET_KEY_PATH)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / "secret.key").stat().st_mode) == 0o600
    assert stat.S_IMODE((destination / "builds/41/fixture.yaml").stat().st_mode) == 0o600
    assert stat.S_IMODE((destination / "bin/mihomo").stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in destination.rglob("*") if path.is_dir())


def rewrite_archive(source, target, key_path, transform):
    """用独立 AEAD API 构造已认证但内部恶意的测试归档。"""
    import base64
    import io
    import os
    import tarfile
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from app import security
    raw = source.read_bytes()
    master = base64.urlsafe_b64decode(key_path.read_bytes())
    key = security.derive_subkey(master, purpose="backup-archive-encryption")
    plaintext = AESGCM(key).decrypt(raw[10:22], raw[22:], raw[:22])
    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:") as tar:
        entries = [(item, tar.extractfile(item).read()) for item in tar.getmembers()]
    entries = transform(entries, master)
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:") as tar:
        for info, content in entries:
            tar.addfile(info, io.BytesIO(content))
    header = b"MPBACKUP\x00\x01" + os.urandom(12)
    target.write_bytes(header + AESGCM(key).encrypt(header[10:22], result.getvalue(), header))


@pytest.mark.parametrize("damage,code", [
    ("traversal", "archive_invalid_path"), ("absolute", "archive_invalid_path"),
    ("drive", "archive_invalid_path"), ("backslash", "archive_invalid_path"),
    ("symlink", "archive_unsafe_file"), ("hardlink", "archive_unsafe_file"),
    ("device", "archive_unsafe_file"), ("duplicate", "archive_duplicate_path"),
    ("case_duplicate", "archive_duplicate_path"), ("manifest_mac", "archive_invalid_manifest"),
    ("digest", "archive_resource_corrupt"),
])
def test_authenticated_archive_still_rejects_unsafe_members(client, tmp_path, damage, code):
    import copy
    import tarfile
    from app import config
    from app.services import backups
    archive, _, _, _, _ = archive_fixture(client, tmp_path)

    def transform(entries, master):
        if damage == "manifest_mac":
            info, content = entries[0]
            envelope = json.loads(content)
            envelope["mac"] = "0" * 64
            content = json.dumps(envelope).encode()
            info.size = len(content)
            entries[0] = (info, content)
        elif damage == "digest":
            info, content = next(item for item in entries if item[0].name == "avatars/1.png")
            entries = [(item, (b"x" + content[1:]) if item.name == info.name else body)
                       for item, body in entries]
        elif damage in {"duplicate", "case_duplicate"}:
            info, content = copy.copy(entries[1][0]), entries[1][1]
            if damage == "case_duplicate":
                info.name = info.name.upper()
            entries.append((info, content))
        else:
            name = {"traversal": "../escaped", "absolute": "/escaped", "drive": "C:/escaped",
                    "backslash": "dir\\escaped"}.get(damage, "unsafe-entry")
            info = tarfile.TarInfo(name)
            if damage in {"symlink", "hardlink", "device"}:
                info.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                             "device": tarfile.CHRTYPE}[damage]
                if damage != "device":
                    info.linkname = "../../outside"
            entries.append((info, b""))
        return entries

    malicious = tmp_path / "malicious.mpbackup"
    rewrite_archive(archive, malicious, config.SECRET_KEY_PATH, transform)
    destination = tmp_path / "unsafe-staging"
    with pytest.raises(ValueError, match=f"^{code}$"):
        backups.restore_archive(malicious, destination, key_path=config.SECRET_KEY_PATH)
    assert not destination.exists()
    assert not (tmp_path / "escaped").exists()


def test_archive_rejects_limits_and_changed_resources(client, tmp_path, monkeypatch):
    from app import config, db
    from app.services import backup_archive, backups
    archive, _, _, _, _ = archive_fixture(client, tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(backup_archive, "MAX_ARCHIVE_BYTES", 100)
        with pytest.raises(ValueError, match="archive_limit_exceeded"):
            backups.restore_archive(archive, tmp_path / "limited", key_path=config.SECRET_KEY_PATH)
        assert not (tmp_path / "limited").exists()
    with monkeypatch.context() as patch:
        patch.setattr(backup_archive, "MAX_FILES", 1)
        with pytest.raises(ValueError, match="archive_limit_exceeded"):
            backups.restore_archive(archive, tmp_path / "too-many", key_path=config.SECRET_KEY_PATH)
    original = backup_archive._copy_file
    def copy_and_change(source, target, fingerprint):
        result = original(source, target, fingerprint)
        if source.name == "1.png":
            source.write_bytes(b"changed-during-copy")
        return result
    monkeypatch.setattr(backup_archive, "_copy_file", copy_and_change)
    with db.connect() as conn:
        with pytest.raises(ValueError, match="archive_resource_changed"):
            backups.create_archive(conn, tmp_path / "changed.mpbackup", include_history=True)
    assert not (tmp_path / "changed.mpbackup").exists()
    assert not list(tmp_path.glob(".mp-archive-*"))


def test_archive_checks_private_blob_before_emitting_backup(client, tmp_path):
    from app import db
    from app.services import backups
    archive_fixture(client, tmp_path)
    with db.tx(immediate=True) as conn:
        conn.execute("UPDATE private_blobs SET ciphertext_sha256=?", ("0" * 64,))
    with db.connect() as conn:
        with pytest.raises(ValueError, match="private_blob_corrupt"):
            backups.create_archive(conn, tmp_path / "invalid-resource.mpbackup", include_history=True)
    assert not (tmp_path / "invalid-resource.mpbackup").exists()


def test_restore_revokes_incomplete_execution_without_rewriting_history(client):
    from app.services.backup_archive import sanitize_restored
    from contextlib import closing
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript("""
            CREATE TABLE sessions(token TEXT); INSERT INTO sessions VALUES('old');
            CREATE TABLE rename_applies(token TEXT); INSERT INTO rename_applies VALUES('old');
            CREATE TABLE probe_jobs(id TEXT, state TEXT, lease_owner TEXT, lease_until TEXT, cancel_requested INT);
            INSERT INTO probe_jobs VALUES('queued','queued','worker','later',0),('done','completed',NULL,NULL,0);
            CREATE TABLE probe_items(id TEXT,state TEXT,lease_owner TEXT,lease_until TEXT);
            INSERT INTO probe_items VALUES('running','running','worker','later'),('done','succeeded',NULL,NULL);
            CREATE TABLE managed_execution_owners(execution_scope TEXT,owner_epoch INT,status TEXT);
            INSERT INTO managed_execution_owners VALUES('active',4,'active'),('retired',3,'retired');
            CREATE TABLE managed_selection_state(execution_scope TEXT,selection_revision INT,mirror_state TEXT);
            INSERT INTO managed_selection_state VALUES('fixture',42,'confirmed');
            CREATE TABLE managed_apply_intents(action_id TEXT,state TEXT);
            INSERT INTO managed_apply_intents VALUES('pending','proposed'),('done','verified'),('bad','rejected');
            CREATE TABLE audit(detail TEXT); INSERT INTO audit VALUES('historical evidence');
        """)
        sanitize_restored(conn)
        sanitize_restored(conn)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM rename_applies").fetchone()[0] == 0
        assert conn.execute("SELECT state,lease_owner,lease_until,cancel_requested FROM probe_jobs WHERE id='queued'").fetchone() == (
            "cancelled", None, None, 1)
        assert conn.execute("SELECT state FROM probe_jobs WHERE id='done'").fetchone()[0] == "completed"
        assert conn.execute("SELECT state FROM probe_items WHERE id='running'").fetchone()[0] == "cancelled"
        assert conn.execute("SELECT owner_epoch,status FROM managed_execution_owners WHERE execution_scope='active'").fetchone() == (
            4, "reconcile_required")
        assert conn.execute("SELECT status FROM managed_execution_owners WHERE execution_scope='retired'").fetchone()[0] == "retired"
        assert conn.execute("SELECT selection_revision,mirror_state FROM managed_selection_state").fetchone() == (42, "reconcile_required")
        assert conn.execute("SELECT * FROM managed_apply_intents ORDER BY action_id").fetchall() == [
            ("bad", "rejected"), ("done", "verified"), ("pending", "reconcile_required")]
        assert conn.execute("SELECT detail FROM audit").fetchone()[0] == "historical evidence"


@pytest.mark.parametrize("name", ["unexpected.txt", "magicpanel.db-wal", "deps/.mp_key"])
def test_authenticated_archive_rejects_unmanaged_files(client, tmp_path, name):
    import hashlib
    import hmac
    import tarfile
    from app import config, security
    from app.services import backups
    archive, _, _, _, _ = archive_fixture(client, tmp_path)
    def add_unmanaged(entries, master):
        info, content = entries[0]
        envelope = json.loads(content)
        envelope["manifest"]["files"].append({"path": name, "size": 0,
            "sha256": hashlib.sha256(b"").hexdigest(), "mode": 0o600})
        canonical = json.dumps(envelope["manifest"], ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode()
        envelope["mac"] = hmac.new(security.derive_subkey(master, purpose="backup-manifest-mac"),
                                    canonical, hashlib.sha256).hexdigest()
        content = json.dumps(envelope).encode()
        info.size = len(content)
        entries[0] = (info, content)
        entries.append((tarfile.TarInfo(name), b""))
        return entries
    malicious = tmp_path / "unmanaged.mpbackup"
    rewrite_archive(archive, malicious, config.SECRET_KEY_PATH, add_unmanaged)
    with pytest.raises(ValueError, match="archive_invalid_manifest"):
        backups.restore_archive(malicious, tmp_path / "unmanaged-staging", key_path=config.SECRET_KEY_PATH)
    assert not (tmp_path / "unmanaged-staging").exists()


def test_review_legacy_wrong_key_rejects_raw_encrypted_setting(client, tmp_path):
    from contextlib import closing
    from cryptography.fernet import Fernet
    from app import config, db
    from app.services import webdav
    foreign = Fernet(Fernet.generate_key())
    with db.tx() as conn:
        db.set_setting(conn, "deps_token_enc", foreign.encrypt(b"fixture-repo-token").decode())
    snapshot = tmp_path / "foreign-key-legacy.db"
    with db.connect() as conn, closing(sqlite3.connect(snapshot)) as target:
        conn.backup(target)
    with pytest.raises(webdav.WebDavError, match="^backup_invalid$"):
        webdav._restore_files(snapshot, config.SECRET_KEY_PATH, "fixture",
                             destination=tmp_path / "wrong-key-stage", legacy=True)
    assert not (tmp_path / "wrong-key-stage").exists()


def test_review_archive_rejects_corrupt_raw_encrypted_setting(client, tmp_path):
    from app import db
    from app.services import backups
    with db.tx() as conn:
        db.set_setting(conn, "deps_private_key_enc", "corrupt-fixture-token")
    with db.connect() as conn:
        with pytest.raises(ValueError, match="^backup_invalid$"):
            backups.create_archive(conn, tmp_path / "corrupt-setting.mpbackup", include_history=True)
    assert not (tmp_path / "corrupt-setting.mpbackup").exists()


def test_review_archive_accepts_plain_note_with_ciphertext_prefix(client, tmp_path):
    from contextlib import closing
    from app import config, db
    from app.services import backups, webdav
    headers = admin(client)
    response = client.post("/api/v1/rules", headers=headers, json={
        "type": "MATCH", "target": "DIRECT", "note": "enc:v1: this is plain fixture text"})
    assert response.status_code == 201, response.text
    with db.connect() as conn:
        result = backups.create_archive(conn, tmp_path / "note.mpbackup", include_runtime=True, include_history=True)
    assert result["encrypted"] is True
    result = backups.restore_archive(tmp_path / "note.mpbackup", tmp_path / "note-restored",
                                     key_path=config.SECRET_KEY_PATH)
    assert result["status"] == "VERIFIED"
    snapshot = tmp_path / "note-legacy.db"
    with db.connect() as conn, closing(sqlite3.connect(snapshot)) as target:
        conn.backup(target)
    result = webdav._restore_files(snapshot, config.SECRET_KEY_PATH, "fixture",
                                  destination=tmp_path / "note-legacy-stage", legacy=True)
    assert result["status"] == "STAGED"
    for name in ("note-restored", "note-legacy-stage"):
        with closing(sqlite3.connect(tmp_path / name / "magicpanel.db")) as conn:
            assert conn.execute("SELECT note FROM rules").fetchone()[0] == "enc:v1: this is plain fixture text"


@pytest.mark.parametrize("flow", ["archive", "legacy"])
@pytest.mark.parametrize("setting", ["deps_token_enc", "deps_private_key_enc"])
@pytest.mark.parametrize("material", ["current", "wrong", "corrupt", "prefixed"])
def test_registered_raw_settings_validate_exact_fernet_codec(client, tmp_path, flow, setting, material):
    from contextlib import closing
    from cryptography.fernet import Fernet
    from app import config, db, security
    from app.services import backups, webdav
    current_key = config.SECRET_KEY_PATH.read_bytes()
    valid = security.encrypt_text("fixture-private-material")
    value = {"current": valid,
             "wrong": Fernet(Fernet.generate_key()).encrypt(b"fixture-private-material").decode(),
             "corrupt": "corrupt-fixture-token", "prefixed": security.PAYLOAD_PREFIX + valid}[material]
    with db.tx() as conn:
        db.set_setting(conn, setting, value)
    destination = tmp_path / "checked-stage"
    if flow == "archive":
        def run():
            with db.connect() as conn:
                return backups.create_archive(conn, tmp_path / "checked.mpbackup", include_runtime=True, include_history=True)
        error = ValueError
    else:
        snapshot = tmp_path / "checked-legacy.db"
        with db.connect() as conn, closing(sqlite3.connect(snapshot)) as target:
            conn.backup(target)
        def run():
            return webdav._restore_files(snapshot, config.SECRET_KEY_PATH, "fixture",
                                         destination=destination, legacy=True)
        error = webdav.WebDavError
    if material == "current":
        result = run()
        assert result["encrypted"] is True if flow == "archive" else result["status"] == "STAGED"
        if flow == "legacy":
            with closing(sqlite3.connect(destination / "magicpanel.db")) as restored:
                token = restored.execute("SELECT value FROM settings WHERE key=?", (setting,)).fetchone()[0]
            assert Fernet((destination / "secret.key").read_bytes()).decrypt(token.encode()) == b"fixture-private-material"
    else:
        with pytest.raises(error, match="^backup_invalid$"):
            run()
        assert not destination.exists() and not (tmp_path / "checked.mpbackup").exists()
    assert config.SECRET_KEY_PATH.read_bytes() == current_key
    with db.connect() as conn:
        assert db.get_setting(conn, setting) == value


@pytest.mark.parametrize("flow", ["archive", "legacy"])
@pytest.mark.parametrize("material", ["encrypted", "legacy_plain", "corrupt"])
def test_registered_payload_setting_preserves_legacy_plaintext_only(client, tmp_path, flow, material):
    from contextlib import closing
    from app import config, db, security
    from app.services import backups, webdav
    value = {"encrypted": security.encrypt_payload("fixture-dav-password"),
             "legacy_plain": "fixture-old-dav-password", "corrupt": "enc:v1:corrupt-fixture-token"}[material]
    with db.tx() as conn:
        db.set_setting(conn, "webdav_password_enc", value)
        db.set_setting(conn, "ordinary_fixture_note", "enc:v1:plain setting annotation")
    if flow == "archive":
        def run():
            with db.connect() as conn:
                return backups.create_archive(conn, tmp_path / "payload.mpbackup", include_runtime=True, include_history=True)
        error = ValueError
    else:
        snapshot = tmp_path / "payload-legacy.db"
        with db.connect() as conn, closing(sqlite3.connect(snapshot)) as target:
            conn.backup(target)
        def run():
            return webdav._restore_files(snapshot, config.SECRET_KEY_PATH, "fixture",
                                         destination=tmp_path / "payload-stage", legacy=True)
        error = webdav.WebDavError
    if material == "corrupt":
        with pytest.raises(error, match="^backup_invalid$"):
            run()
    else:
        result = run()
        assert result["encrypted"] is True if flow == "archive" else result["status"] == "STAGED"


def test_legacy_validation_uses_explicit_key_without_live_fernet_cache(client, tmp_path):
    from contextlib import closing
    from cryptography.fernet import Fernet
    from app import config, db, security
    from app.services import webdav
    current_key = config.SECRET_KEY_PATH.read_bytes()
    live_token = security.encrypt_text("prime-live-cache")
    supplied_key = tmp_path / "explicit-fixture.key"
    supplied_key.write_bytes(Fernet.generate_key())
    token = Fernet(supplied_key.read_bytes()).encrypt(b"fixture-repo-token").decode()
    with db.tx() as conn:
        db.set_setting(conn, "deps_token_enc", token)
    snapshot = tmp_path / "explicit-key-legacy.db"
    with db.connect() as conn, closing(sqlite3.connect(snapshot)) as target:
        conn.backup(target)
    result = webdav._restore_files(snapshot, supplied_key, "fixture",
                                  destination=tmp_path / "explicit-key-stage", legacy=True)
    assert result["status"] == "STAGED"
    assert config.SECRET_KEY_PATH.read_bytes() == current_key
    assert security.decrypt_text(live_token) == "prime-live-cache"
    assert Fernet(current_key).decrypt(security.encrypt_text("still-live").encode()) == b"still-live"
