import importlib
import os
import sys
import tempfile

import pytest

TEST_DATA = None

# macOS 的临时目录挂在 /var/folders 下，而 /var 本身是 /private/var 的符号链接。
# 归档路径校验会拒绝父目录是符号链接的路径，于是备份相关的用例在本机必然失败。
# 把临时目录切到解析后的真实路径，Linux 上是恒等操作。
tempfile.tempdir = os.path.realpath(tempfile.gettempdir())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """每个用例独立数据目录与全新应用实例。"""
    monkeypatch.setenv("MAGICPANEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAGICPANEL_SCHEDULER", "0")
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        yield c


def setup_admin(client, username="admin", password="admin-pass-1"):
    resp = client.post("/api/v1/setup", json={
        "username": username, "password": password, "display_name": "管理员",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


def auth_headers(csrf):
    return {"X-CSRF-Token": csrf}
