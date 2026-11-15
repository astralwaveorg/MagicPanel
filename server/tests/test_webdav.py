"""本地 DAV fixture 验证加密归档和 staging，不恢复运行库。"""
import json
import sqlite3
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dav_server import DavServer  # noqa: E402

def _configure(conn, url, username="dav", password="secret", keep=3, interval=6):
    from app.services import webdav
    webdav.save_settings(conn, {
        "enabled": "1",
        "url": url,
        "directory": "magicpanel",
        "username": username,
        "password": password,
        "keep": str(keep),
        "interval_hours": str(interval),
    })


def test_webdav_backup_upload_list_and_restore(client):
    from app import db
    from app.services import webdav
    csrf = __import__("conftest").setup_admin(client)
    h = __import__("conftest").auth_headers(csrf)
    with DavServer(auth=("dav", "secret")) as server:
        with db.tx() as conn:
            _configure(conn, server.url)
        # 测试连接
        r = client.post("/api/v1/backup/webdav/test", headers=h)
        assert r.status_code == 200, r.text
        # 手动备份
        r = client.post("/api/v1/backup/webdav/upload", headers=h)
        assert r.status_code == 200, r.text
        assert len(r.json()["files"]) == 2
        # 远端确实有文件
        assert any(name.endswith(".mpbackup") for name in server.state.files)
        assert any(name.endswith(".meta.json") for name in server.state.files)
        assert not any(name.endswith((".key", ".db")) for name in server.state.files)
        metadata = next(value for name, value in server.state.files.items() if name.endswith(".meta.json"))
        assert set(json.loads(metadata)) == {"format", "version", "encrypted", "created_at", "size", "key_included"}
        # 列举
        r = client.get("/api/v1/backup/webdav/files", headers=h)
        assert r.status_code == 200, r.text
        files = r.json()["files"]
        assert files and all(f["name"].startswith("magicpanel-") for f in files)
        assert files[0]["size"] > 0
        # 口令不回显
        r = client.get("/api/v1/backup/webdav", headers=h)
        info = r.json()
        assert info["password_set"] is True
        assert "password" not in info or not info.get("password")
        # 状态已记录
        assert info["last_status"] == "成功"
        assert info["last_backup_at"]


def test_webdav_restore_stages_without_replacing_running_data(client, tmp_path):
    from app import config, db
    from app.services import webdav
    setup_admin = __import__("conftest").setup_admin
    auth_headers = __import__("conftest").auth_headers
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    with DavServer(auth=("dav", "secret")) as server:
        with db.tx() as conn:
            _configure(conn, server.url)
        client.post("/api/v1/sources", headers=h, json={
            "name": "备份前来源", "url": "https://example.com/sub"})
        assert client.post("/api/v1/backup/webdav/upload", headers=h).status_code == 200
        # staging 只含备份时的数据，运行库保留备份之后的改动。
        client.post("/api/v1/sources", headers=h, json={
            "name": "备份后来源", "url": "https://example.com/sub2"})
        assert len(client.get("/api/v1/sources", headers=h).json()) == 2
        files = client.get("/api/v1/backup/webdav/files", headers=h).json()["files"]
        archive_file = next(f["name"] for f in files if f["name"].endswith(".mpbackup"))
        # 恢复必须显式确认
        r = client.post("/api/v1/backup/webdav/restore", headers=h,
                        json={"confirm": False, "data": {"file": archive_file}})
        assert r.status_code == 400
        destination = tmp_path / "remote-staging"
        with db.connect() as conn:
            result = webdav.restore_from_remote(conn, archive_file, "fixture", destination=destination,
                                                 key_path=config.SECRET_KEY_PATH)
        assert result["status"] == "STAGED" and result["restored"] is False
        assert result["verification_status"] == "VERIFIED"
        assert result["requires_maintenance_restart"] is True
        resp = client.get("/api/v1/sources", headers=h)
        assert resp.status_code == 200, resp.text
        names = [s["name"] for s in resp.json()]
        assert names == ["备份前来源", "备份后来源"]
        with sqlite3.connect(destination / "magicpanel.db") as restored:
            assert restored.execute("SELECT name FROM sources").fetchall() == [("备份前来源",)]


def test_webdav_rotation_keeps_latest_n(client):
    from app import db
    setup_admin = __import__("conftest").setup_admin
    auth_headers = __import__("conftest").auth_headers
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    with DavServer(auth=("dav", "secret")) as server:
        with db.tx() as conn:
            _configure(conn, server.url, keep=2)
        for _ in range(3):
            r = client.post("/api/v1/backup/webdav/upload", headers=h)
            assert r.status_code == 200, r.text
        archives = [n for n in server.state.files if n.endswith(".mpbackup")]
        assert len(archives) == 2, archives
        metadata = [n for n in server.state.files if n.endswith(".meta.json")]
        assert len(metadata) == 2, metadata
        assert not any(n.endswith(".key") for n in server.state.files)


def test_webdav_legacy_requires_explicit_staging_and_never_rotates_legacy_files(client, tmp_path):
    from app import config, db
    from app.services import webdav
    __import__("conftest").setup_admin(client)
    with DavServer(auth=("dav", "secret")) as server:
        with db.tx() as conn:
            _configure(conn, server.url, keep=1)
        with db.connect() as conn:
            with pytest.raises(webdav.WebDavError, match="backup_staging_required"):
                webdav.restore_from_remote(conn, "magicpanel-fixture.db", "fixture")
            with pytest.raises(webdav.WebDavError, match="legacy_restore_required"):
                webdav.restore_from_remote(conn, "magicpanel-fixture.db", "fixture",
                                           destination=tmp_path / "no-legacy", key_path=config.SECRET_KEY_PATH)
            snapshot = tmp_path / "legacy.db"
            target = sqlite3.connect(snapshot)
            try:
                conn.backup(target)
            finally:
                target.close()
            webdav.upload_file(conn, snapshot, "magicpanel-20000101.db")
            webdav.upload_file(conn, config.SECRET_KEY_PATH, "magicpanel-20000101.key")
            webdav.run_backup(conn)
            webdav.run_backup(conn)
        assert any(n.endswith("magicpanel-20000101.db") for n in server.state.files)
        assert any(n.endswith("magicpanel-20000101.key") for n in server.state.files)


def test_http_archive_restore_uses_private_server_staging_without_live_replacement(client, tmp_path):
    from contextlib import closing
    from app import config, db
    csrf = __import__("conftest").setup_admin(client)
    headers = __import__("conftest").auth_headers(csrf)
    original_key = config.SECRET_KEY_PATH.read_bytes()
    with DavServer(auth=("dav", "secret")) as server:
        with db.tx() as conn:
            _configure(conn, server.url)
        assert client.post("/api/v1/sources", headers=headers, json={
            "name": "before", "url": "https://example.com/fixture"}).status_code == 201
        response = client.post("/api/v1/backup/webdav/upload", headers=headers)
        assert response.status_code == 200, response.text
        name = next(item for item in response.json()["files"] if item.endswith(".mpbackup"))
        assert client.post("/api/v1/sources", headers=headers, json={
            "name": "after", "url": "https://example.com/after"}).status_code == 201
        response = client.post("/api/v1/backup/webdav/restore", headers=headers, json={
            "confirm": True, "data": {"file": name, "destination": str(tmp_path / "untrusted"),
                                       "key_path": str(tmp_path / "untrusted.key")}})
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        result = response.json()
        assert result["status"] == "STAGED" and result["restored"] is False
        assert result["verification_status"] == "VERIFIED"
        assert str(config.DATA_DIR) not in response.text
        assert not (tmp_path / "untrusted").exists()
        destination = config.DATA_DIR / "restore-staging" / result["staging_name"]
        with closing(sqlite3.connect(destination / "magicpanel.db")) as restored:
            assert restored.execute("SELECT name FROM sources ORDER BY id").fetchall() == [("before",)]
            assert restored.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert len(client.get("/api/v1/sources").json()) == 2
        assert config.SECRET_KEY_PATH.read_bytes() == original_key


def test_webdav_requires_configuration(client):
    setup_admin = __import__("conftest").setup_admin
    auth_headers = __import__("conftest").auth_headers
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/backup/webdav/upload", headers=h)
    assert r.status_code == 400
    assert "WebDAV" in r.json()["detail"]


def test_webdav_password_is_encrypted_at_rest(client):
    from app import db, security
    from app.services import webdav
    setup_admin = __import__("conftest").setup_admin
    csrf = setup_admin(client)
    with DavServer() as server:
        with db.tx() as conn:
            _configure(conn, server.url, password="super-secret")
            raw = db.get_setting(conn, webdav.SET_PASS)
            assert "super-secret" not in raw
            assert raw.startswith("enc:")
            # 能正常解开用于连接
            assert security.decrypt_payload(raw) == "super-secret"
