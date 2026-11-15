"""逻辑备份通过真实接口和调用事务验证恢复边界。"""
from copy import deepcopy
import hashlib
import sqlite3

import pytest

from v2_helpers import admin, import_source, make_local, ordering, proxy


def seeded(client):
    headers = admin(client)
    assert client.post("/api/v1/groups", headers=headers, json={
        "name": "keep", "type": "select", "proxies": ["DIRECT"]}).status_code == 201
    assert client.post("/api/v1/rules", headers=headers, json={
        "type": "MATCH", "target": "keep"}).status_code == 201
    return headers


def export(conn):
    from app.services import backups
    conn.execute("BEGIN")
    return backups.export_logical(conn)


def test_backup_contains_variants_and_keeps_order(client):
    from app import db
    from app.services import backups
    headers = seeded(client)
    assert client.post("/api/v1/variants", headers=headers, json={
        "name": "第二方案", "copy_from": 0}).status_code == 201
    with db.connect() as conn:
        before = ordering(conn)
        payload = export(conn)
    assert payload["version"] == 2
    assert payload["files"] == [] and payload["key_required"] is True
    assert {r["name"] for r in payload["tables"]["variants"]} == {"默认", "第二方案"}
    assert {"repo_migrations", "automation_runs", "schema_version"} <= payload["tables"].keys()
    assert not {"sessions", "audit"} & payload["tables"].keys()
    with db.tx(immediate=True) as conn:
        result = backups.restore_logical(conn, payload)
        assert ordering(conn) == before
        assert conn.in_transaction
    assert result == {"legacy_import": False, "tables": len(payload["tables"]),
                      "rows": sum(map(len, payload["tables"].values()))}


def test_legacy_default_is_only_safe_variant_inference(client):
    from app import db
    from app.services import backups
    seeded(client)
    with db.connect() as conn:
        payload = export(conn)
        before = ordering(conn)
    payload["version"] = 1
    for table in ("variants", "schema_version", "automation_runs", "repo_migrations"):
        payload["tables"].pop(table)
    for table in ("proxy_groups", "rules"):
        for row in payload["tables"][table]:
            row.pop("variant_id")
    with db.tx(immediate=True) as conn:
        report = backups.restore_logical(conn, payload)
        assert ordering(conn) == before
        row = dict(conn.execute("SELECT * FROM variants").fetchone())
        assert row["id"] == 0 and row["is_system"] == 1 and row["name"] == "默认"
        assert row["created_at"] == row["updated_at"] == payload["exported_at"]
    assert report["legacy_import"] is True


@pytest.mark.parametrize("damage,code", [
    ("legacy_variant", "backup_missing_variants"),
    ("unknown_table", "backup_invalid"),
    ("unknown_column", "backup_invalid"),
    ("duplicate_id", "backup_invalid"),
    ("duplicate_key", "backup_invalid"),
    ("foreign_key", "backup_invalid_reference"),
    ("variant", "backup_invalid_reference"),
    ("rule_target", "backup_invalid_reference"),
    ("group_member", "backup_invalid_reference"),
    ("scope", "backup_invalid_reference"),
    ("source", "backup_invalid_reference"),
    ("base_config", "backup_invalid_reference"),
    ("bad_row", "backup_invalid"),
    ("missing_table", "backup_invalid"),
])
def test_invalid_snapshot_never_deletes_current_rows(client, damage, code):
    from app import db
    from app.services import backups
    seeded(client)
    with db.connect() as conn:
        payload = export(conn)
    tables = payload["tables"]
    if damage == "legacy_variant":
        payload["version"] = 1
        tables.pop("variants")
        tables["rules"][0]["variant_id"] = 42
    elif damage == "unknown_table":
        tables["payload-secret"] = []
    elif damage == "unknown_column":
        tables["users"][0]["payload-secret"] = "ciphertext-marker"
    elif damage == "duplicate_id":
        tables["rules"].append(deepcopy(tables["rules"][0]))
    elif damage == "duplicate_key":
        tables["settings"].append(deepcopy(tables["settings"][0]))
    elif damage == "foreign_key":
        tables["releases"].append({"id": 1, "build_id": 999, "env": "production",
                                   "action": "publish", "created_at": db.now()})
    elif damage == "variant":
        tables["rules"][0]["variant_id"] = 999
    elif damage == "rule_target":
        tables["rules"][0]["target"] = "missing-secret"
    elif damage == "group_member":
        tables["proxy_groups"][0]["proxies"] = '["missing-secret"]'
    elif damage == "scope":
        tables["rules"][0]["devices"] = '["missing-secret"]'
    elif damage == "source":
        tables["proxy_groups"][0]["use_sources"] = '["missing-secret"]'
    elif damage == "base_config":
        tables["base_configs"].append({"engine": "stash", "platform": "ios",
                                        "device_id": 999, "updated_at": db.now()})
    elif damage == "bad_row":
        tables["rules"].append("ciphertext-marker")
    elif damage == "missing_table":
        tables.pop("users")
    with db.tx(immediate=True) as conn:
        before = ordering(conn)
        statements = []
        conn.set_trace_callback(statements.append)
        with pytest.raises(ValueError, match=f"^{code}$"):
            backups.restore_logical(conn, payload)
        assert ordering(conn) == before
        assert not any(s.lstrip().upper().startswith("DELETE ") for s in statements)


def test_http_dry_run_and_restore_revoke_sessions_preserve_audit(client):
    from app import db
    headers = seeded(client)
    response = client.get("/api/v1/backup/export")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    with db.connect() as conn:
        before = ordering(conn)
        audit_before = [tuple(row) for row in conn.execute("SELECT * FROM audit ORDER BY id")]
        session_before = [tuple(row) for row in conn.execute("SELECT * FROM sessions")]
    preview = client.post("/api/v1/backup/restore", headers=headers,
                          json={"data": payload, "dry_run": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True
    assert preview.json()["staging"]["validated"] is True
    assert preview.json()["staging"]["complete_archive"] is False
    with db.connect() as conn:
        assert ordering(conn) == before
        assert [tuple(row) for row in conn.execute("SELECT * FROM sessions")] == session_before
    result = client.post("/api/v1/backup/restore", headers=headers,
                         json={"data": payload, "confirm": True})
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert client.get("/api/v1/overview").status_code == 401
    with db.connect() as conn:
        assert ordering(conn) == before
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        audit_after = [tuple(row) for row in conn.execute("SELECT * FROM audit ORDER BY id")]
        assert audit_after[:len(audit_before)] == audit_before
        assert any(row[3] == "恢复备份" for row in audit_after[len(audit_before):])


def test_http_errors_are_safe_and_keep_live_session(client):
    from app import db
    headers = seeded(client)
    payload = client.get("/api/v1/backup/export").json()
    payload["tables"]["users"][0]["secret-marker"] = "ciphertext-marker"
    response = client.post("/api/v1/backup/restore", headers=headers,
                           json={"data": payload, "confirm": True})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "backup_invalid"
    assert response.json()["detail"]["request_id"]
    assert "secret-marker" not in response.text and "ciphertext-marker" not in response.text
    assert client.get("/api/v1/overview").status_code == 200


def test_services_require_caller_transaction_and_do_not_commit(client):
    from app import db
    from app.services import backups
    seeded(client)
    with db.connect() as conn:
        with pytest.raises(ValueError, match="backup_transaction_required"):
            backups.export_logical(conn)
        payload = export(conn)
        conn.rollback()
        with pytest.raises(ValueError, match="backup_transaction_required"):
            backups.restore_logical(conn, payload)
        conn.execute("BEGIN IMMEDIATE")
        backups.restore_logical(conn, payload)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        conn.rollback()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_build_files_are_bound_to_target_database_directory(client, tmp_path):
    from app import config, db
    from app.services import backups
    headers = seeded(client)
    assert client.post("/api/v1/targets", headers=headers, json={
        "name": "fixture", "engine": "stash", "platform": "ios"}).status_code == 201
    built = client.post("/api/v1/builds", headers=headers, json={"note": "backup-fixture"})
    assert built.status_code == 201, built.text
    for name, result in built.json()["results"].items():
        if result["ok"]:
            content = (config.BUILDS_DIR / str(built.json()["id"]) / f"{name}.yaml").read_bytes()
            assert len(content) == result["size"]
            assert hashlib.sha256(content).hexdigest() == result["sha256"]
            assert b"\r\n" not in content
    with db.connect() as conn:
        payload = export(conn)
    assert payload["files"]
    item = payload["files"][0]
    file = config.DATA_DIR / item["path"]
    assert item["size"] == file.stat().st_size
    assert item["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
    destination = tmp_path / "different" / "magicpanel.db"
    destination.parent.mkdir()
    with db.connect() as source, sqlite3.connect(destination) as target:
        source.backup(target)
    target = sqlite3.connect(destination)
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys=ON")
    target.execute("BEGIN IMMEDIATE")
    before = ordering(target)
    with pytest.raises(ValueError, match="backup_missing_resource"):
        backups.restore_logical(target, payload)
    assert ordering(target) == before
    target.close()
    original = file.read_bytes()
    file.write_bytes(original + b"tamper")
    with db.tx(immediate=True) as conn:
        with pytest.raises(ValueError, match="backup_missing_resource"):
            backups.restore_logical(conn, payload)
    file.write_bytes(original)
    broken = deepcopy(payload)
    broken["files"] = []
    with db.tx(immediate=True) as conn:
        with pytest.raises(ValueError, match="backup_missing_resource"):
            backups.restore_logical(conn, broken)
    with db.tx(immediate=True) as conn:
        backups.restore_logical(conn, payload)


def test_legacy_cannot_guess_variants_or_timestamps(client):
    from app import db
    from app.services import backups
    seeded(client)
    with db.connect() as conn:
        payload = export(conn)
    payload["version"] = 1
    payload["tables"].pop("variants")
    payload["exported_at"] = "invalid-secret"
    with db.tx(immediate=True) as conn:
        with pytest.raises(ValueError, match="backup_invalid"):
            backups.restore_logical(conn, payload)


def test_export_reads_one_database_snapshot_during_concurrent_write(client):
    from app import db
    from app.services import backups
    headers = seeded(client)
    source = import_source(client, headers, [proxy()])
    changed = False
    with db.connect() as conn:
        conn.execute("BEGIN")

        def concurrent_change(statement):
            nonlocal changed
            if statement.startswith('SELECT * FROM "sources"') and not changed:
                changed = True
                with db.tx(immediate=True) as other:
                    other.execute("UPDATE sources SET name='concurrent' WHERE id=?", (source["id"],))

        conn.set_trace_callback(concurrent_change)
        payload = backups.export_logical(conn)
    assert changed
    assert payload["tables"]["sources"][0]["name"] == "source-fixture"
    with db.connect() as conn:
        assert conn.execute("SELECT name FROM sources").fetchone()[0] == "concurrent"


def test_real_source_and_local_node_references_survive_restore(client):
    from app import db
    from app.services import backups, local_nodes
    headers = seeded(client)
    source = import_source(client, headers, [proxy("source-node")])
    node = make_local(client, headers)
    assert client.post("/api/v1/groups", headers=headers, json={
        "name": "source-and-local", "type": "select", "use_sources": [source["name"]],
        "local_nodes": [node["id"]], "proxies": [
            local_nodes.display_name(node["name"], node["node_type"]), "source-node"]
    }).status_code == 201
    with db.connect() as conn:
        before = ordering(conn)
        payload = export(conn)
    with db.tx(immediate=True) as conn:
        backups.restore_logical(conn, payload)
        assert ordering(conn) == before


def test_unexpected_live_write_failure_rolls_back_even_if_caller_catches(client):
    from app import db
    from app.services import backups
    seeded(client)
    with db.connect() as conn:
        payload = export(conn)
    with db.tx(immediate=True) as conn:
        before = ordering(conn)
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.execute("CREATE TEMP TRIGGER fail_restore BEFORE INSERT ON rules "
                     "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with pytest.raises(sqlite3.IntegrityError):
            backups.restore_logical(conn, payload)
        assert ordering(conn) == before
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == sessions


@pytest.mark.parametrize("damage", ["cycle", "cross_variant", "missing_variant", "malformed_list"])
def test_logical_reference_errors_are_rejected_before_delete(client, damage):
    from app import db
    from app.services import backups
    headers = seeded(client)
    assert client.post("/api/v1/variants", headers=headers, json={
        "name": "第二方案", "copy_from": 0}).status_code == 201
    with db.connect() as conn:
        payload = export(conn)
    tables = payload["tables"]
    if damage == "cycle":
        tables["proxy_groups"][0]["proxies"] = '["keep"]'
    elif damage == "cross_variant":
        tables["proxy_groups"][1]["name"] = "second-only"
        tables["rules"][0]["target"] = "second-only"
    elif damage == "missing_variant":
        tables.pop("variants")
    else:
        tables["rules"][0]["targets"] = '{"secret":"marker"}'
    with db.tx(immediate=True) as conn:
        before = ordering(conn)
        statements = []
        conn.set_trace_callback(statements.append)
        with pytest.raises(ValueError):
            backups.restore_logical(conn, payload)
        assert ordering(conn) == before
        assert not any(statement.startswith("DELETE ") for statement in statements)


def test_platform_overlay_without_target_is_valid_existing_api_state(client):
    from app import db
    from app.services import backups
    headers = seeded(client)
    response = client.put("/api/v1/base-config?engine=stash&platform=ios", headers=headers,
                          json={"content": "mixed-port: 7891\n"})
    assert response.status_code == 200, response.text
    with db.connect() as conn:
        payload = export(conn)
    with db.tx(immediate=True) as conn:
        backups.restore_logical(conn, payload)
        assert conn.execute("SELECT COUNT(*) FROM base_configs WHERE platform='ios'").fetchone()[0] == 1


def test_missing_primary_key_is_not_reassigned_during_restore(client):
    from app import db
    from app.services import backups
    seeded(client)
    with db.connect() as conn:
        payload = export(conn)
    payload["tables"]["proxy_groups"][0].pop("id")
    with db.tx(immediate=True) as conn:
        before = ordering(conn)
        with pytest.raises(ValueError, match="backup_invalid"):
            backups.restore_logical(conn, payload)
        assert ordering(conn) == before


def test_export_refuses_build_file_that_changed_since_build(client):
    from app import config, db
    from app.services import backups
    headers = seeded(client)
    assert client.post("/api/v1/targets", headers=headers, json={
        "name": "fixture", "engine": "stash", "platform": "ios"}).status_code == 201
    built = client.post("/api/v1/builds", headers=headers, json={"note": "backup-fixture"})
    assert built.status_code == 201, built.text
    file = next(config.BUILDS_DIR.glob("*/*.yaml"))
    file.write_bytes(file.read_bytes() + b"tamper")
    with db.connect() as conn:
        conn.execute("BEGIN")
        with pytest.raises(ValueError, match="backup_missing_resource"):
            backups.export_logical(conn)


def legacy_database(tmp_path, *, original_schema=True, missing_markers=False):
    from app import db
    snapshot = tmp_path / "legacy-physical.db"
    with db.connect() as source, sqlite3.connect(snapshot) as target:
        source.backup(target)
    with sqlite3.connect(snapshot) as conn:
        if original_schema:
            conn.row_factory = sqlite3.Row
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='proxy_groups'").fetchone()[0]
            sql = sql.replace("proxy_groups", "legacy_groups", 1)
            sql = sql.replace("variant_id INTEGER NOT NULL DEFAULT 0,", "")
            sql = sql.replace("UNIQUE(variant_id, name)", "UNIQUE(name)")
            conn.execute(sql)
            columns = ",".join(row["name"] for row in conn.execute("PRAGMA table_info(proxy_groups)")
                               if row["name"] != "variant_id")
            conn.execute(f"INSERT INTO legacy_groups({columns}) SELECT {columns} FROM proxy_groups")
            conn.execute("DROP TABLE proxy_groups")
            conn.execute("ALTER TABLE legacy_groups RENAME TO proxy_groups")
            conn.execute("ALTER TABLE rules DROP COLUMN variant_id")
        conn.execute("DROP TABLE variants")
        if missing_markers:
            conn.execute("DROP TABLE schema_version")
        else:
            conn.execute("DELETE FROM schema_version WHERE key='variants_v1'")
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    return snapshot


@pytest.mark.parametrize("missing_markers", [False, True])
def test_legacy_physical_restore_preserves_default_variant_and_migration_markers(client, tmp_path, missing_markers):
    from app import db
    from app.services import webdav
    headers = seeded(client)
    with db.connect() as conn:
        before = ordering(conn)
        markers = [tuple(row) for row in conn.execute("SELECT * FROM schema_version ORDER BY key")]
    snapshot = legacy_database(tmp_path, missing_markers=missing_markers)
    assert webdav._restore_files(snapshot, None, "admin")["restored"] is True
    with db.connect() as conn:
        assert ordering(conn) == before
        assert [tuple(row) for row in conn.execute("SELECT * FROM schema_version ORDER BY key")] == markers
        variant = conn.execute("SELECT id,name,is_system FROM variants").fetchone()
        assert variant is not None and tuple(variant) == (0, "默认", 1)
    assert client.get("/api/v1/overview").status_code == 401
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-pass-1"})
    assert response.status_code == 200, response.text
    headers = {"X-CSRF-Token": response.json()["csrf_token"]}
    assert client.post("/api/v1/groups", headers=headers, json={
        "name": "after-legacy-restore", "type": "select", "proxies": ["DIRECT"]}).status_code == 201


def test_legacy_physical_restore_with_missing_nondefault_variant_never_clears_live_data(client, tmp_path):
    from app import db
    from app.services import webdav
    seeded(client)
    snapshot = legacy_database(tmp_path, original_schema=False)
    with sqlite3.connect(snapshot) as conn:
        conn.execute("UPDATE proxy_groups SET variant_id=42")
    with db.connect() as conn:
        before = ordering(conn)
        markers = [tuple(row) for row in conn.execute("SELECT * FROM schema_version ORDER BY key")]
        sessions = [tuple(row) for row in conn.execute("SELECT * FROM sessions")]
    with pytest.raises(webdav.WebDavError, match="backup_missing_variants"):
        webdav._restore_files(snapshot, None, "admin")
    with db.connect() as conn:
        assert ordering(conn) == before
        assert [tuple(row) for row in conn.execute("SELECT * FROM schema_version ORDER BY key")] == markers
        assert [tuple(row) for row in conn.execute("SELECT * FROM sessions")] == sessions


def test_legacy_snapshot_rejects_duplicate_migration_keys(client):
    from app import db
    from app.services import backups
    seeded(client)
    with db.connect() as conn:
        payload = export(conn)
    payload["version"] = 1
    payload["tables"]["schema_version"].append(deepcopy(payload["tables"]["schema_version"][0]))
    with db.tx(immediate=True) as conn:
        before = ordering(conn)
        with pytest.raises(ValueError, match="backup_invalid"):
            backups.restore_logical(conn, payload)
        assert ordering(conn) == before


def test_physical_restore_uses_snapshot_variants_and_preserves_source_bytes(client, tmp_path):
    from app import db
    from app.services import webdav
    headers = seeded(client)
    assert client.post("/api/v1/variants", headers=headers, json={
        "name": "第二方案", "copy_from": 0}).status_code == 201
    snapshot = tmp_path / "current-physical.db"
    with db.connect() as source, sqlite3.connect(snapshot) as target:
        before = ordering(source)
        source.backup(target)
    source_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with db.tx(immediate=True) as conn:
        conn.execute("UPDATE proxy_groups SET sort=sort+500")
        conn.execute("UPDATE rules SET sort=sort+600")
        conn.execute("UPDATE variants SET name='current-only' WHERE id!=0")
    webdav._restore_files(snapshot, None, "admin")
    with db.connect() as conn:
        assert ordering(conn) == before
        assert {row[0] for row in conn.execute("SELECT name FROM variants")} == {"默认", "第二方案"}
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == source_hash


def test_physical_restore_rejects_unknown_columns_even_in_empty_table(client, tmp_path):
    from app import db
    from app.services import webdav
    seeded(client)
    snapshot = legacy_database(tmp_path)
    with sqlite3.connect(snapshot) as conn:
        conn.execute("ALTER TABLE sources ADD COLUMN unknown_secret TEXT")
    with db.connect() as conn:
        before = ordering(conn)
    with pytest.raises(webdav.WebDavError, match="backup_invalid"):
        webdav._restore_files(snapshot, None, "admin")
    with db.connect() as conn:
        assert ordering(conn) == before
