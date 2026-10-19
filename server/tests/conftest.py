import importlib
import os
import sys

import pytest

TEST_DATA = None


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """每个用例独立数据目录与全新应用实例。"""
    monkeypatch.setenv("MAGICPANEL_DATA_DIR", str(tmp_path / "data"))
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
