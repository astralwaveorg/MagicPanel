"""WebDAV 备份链路的端到端测试：配置 → 上传 → 列举 → 下载恢复 → 轮转。"""
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
        assert len(r.json()["files"]) == 2      # 数据库快照 + 主密钥
        # 远端确实有文件
        assert any(name.endswith(".db") for name in server.state.files)
        assert any(name.endswith(".key") for name in server.state.files)
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


def test_webdav_restore_replaces_data(client):
    from app import db
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
        # 备份之后再写一条，验证恢复会把它抹掉
        client.post("/api/v1/sources", headers=h, json={
            "name": "备份后来源", "url": "https://example.com/sub2"})
        assert len(client.get("/api/v1/sources", headers=h).json()) == 2
        files = client.get("/api/v1/backup/webdav/files", headers=h).json()["files"]
        db_file = next(f["name"] for f in files if f["name"].endswith(".db"))
        # 恢复必须显式确认
        r = client.post("/api/v1/backup/webdav/restore", headers=h,
                        json={"confirm": False, "data": {"file": db_file}})
        assert r.status_code == 400
        # 正常恢复
        r = client.post("/api/v1/backup/webdav/restore", headers=h,
                        json={"confirm": True, "data": {"file": db_file}})
        assert r.status_code == 200, r.text
        resp = client.get("/api/v1/sources", headers=h)
        assert resp.status_code == 200, resp.text
        names = [s["name"] for s in resp.json()]
        assert names == ["备份前来源"]


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
        dbs = [n for n in server.state.files if n.endswith(".db")]
        assert len(dbs) == 2, dbs
        # 每个快照都带主密钥
        keys = [n for n in server.state.files if n.endswith(".key")]
        assert len(keys) == 2, keys


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
