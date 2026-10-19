"""测速核心本地上传安装：格式识别、执行校验、替换与鉴权。"""
import gzip
import io
import zipfile

from conftest import auth_headers, setup_admin

# 可执行的假核心：忽略参数，自报 Mihomo 版本
FAKE_CORE = b'#!/bin/sh\necho "Mihomo Meta v9.9.9 test-upload"\n'
NOT_CORE = b'#!/bin/sh\necho "hello"\n'


def _zip_with_mihomo(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mihomo-linux-amd64", payload)
    return buf.getvalue()


def test_core_upload_gzip(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    assert client.get("/api/v1/core/status").json()["available"] is False

    r = client.post("/api/v1/core/upload", content=gzip.compress(FAKE_CORE),
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    assert "v9.9.9" in r.json()["version"]

    status = client.get("/api/v1/core/status").json()
    assert status["available"] is True
    assert "v9.9.9" in status["version"]
    assert status["platform"] and status["pinned_version"]

    # 再次上传即为更新
    newer = FAKE_CORE.replace(b"v9.9.9", b"v9.9.10")
    r = client.post("/api/v1/core/upload", content=gzip.compress(newer),
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200 and "v9.9.10" in r.json()["version"]


def test_core_upload_zip_and_raw(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)

    r = client.post("/api/v1/core/upload", content=_zip_with_mihomo(FAKE_CORE),
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text

    r = client.post("/api/v1/core/upload", content=FAKE_CORE,
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text


def test_core_upload_rejects_invalid(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 不是可执行文件
    r = client.post("/api/v1/core/upload", content=b"plain text data",
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 400
    # 可执行但不是 Mihomo
    r = client.post("/api/v1/core/upload", content=NOT_CORE,
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 400
    # zip 中没有 mihomo 条目
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "nothing")
    r = client.post("/api/v1/core/upload", content=buf.getvalue(),
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 400
    # 全部失败后核心仍不可用（未被污染）
    assert client.get("/api/v1/core/status").json()["available"] is False


def test_core_upload_requires_auth(client):
    client.cookies.clear()
    r = client.post("/api/v1/core/upload", content=gzip.compress(FAKE_CORE),
                    headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 401
