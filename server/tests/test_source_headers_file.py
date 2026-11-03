"""节点来源：自定义请求头 + 上传本地文件作为订阅来源。

两个需求：
  * 机场订阅要带 Cookie / 特定 User-Agent 才能取到（风控），所以来源
    要支持自定义请求头；请求头的值是凭据：密文存储、接口不回显原文。
  * 有的订阅没有在线地址（只能在客户端导出成文件），这种来源仍然是
    「订阅来源」而不是「本地节点」：照常参与分组、测速与下发。
"""
import base64

import pytest

from conftest import auth_headers, setup_admin
from test_api import make_policy, publish_to_prod


CLASH_YAML = """proxies:
  - name: 香港01
    type: ss
    server: hk.example.com
    port: 443
    cipher: aes-256-gcm
    password: pw-hk
  - name: 日本01
    type: trojan
    server: jp.example.com
    port: 443
    password: pw-jp
    sni: jp.example.com
""".encode()

URI_LIST = (
    "ss://YWVzLTI1Ni1nY206cHctaGtleQ@ss.example.com:443#SS节点\n"
    "trojan://pw@tr.example.com:443?sni=tr.example.com#Trojan节点\n"
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _source(client, h, **kw):
    body = {"name": kw.pop("name", "机场A"),
            "url": kw.pop("url", "https://a.example.com/sub?token=abc123")}
    body.update(kw)
    r = client.post("/api/v1/sources", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---- 自定义请求头 ----

def test_source_headers_are_stored_encrypted_and_not_echoed(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h, headers=[
        {"name": "Cookie", "value": "acw_tc=secret-value"},
        {"name": "User-Agent", "value": "meta/ua.net.qytclient.ios/1.4"},
    ])
    # 接口只回显名字，值不回显
    assert src["headers"] == [{"name": "Cookie"}, {"name": "User-Agent"}]
    listing = client.get("/api/v1/sources", headers=h).json()
    row = next(x for x in listing if x["id"] == src["id"])
    assert "secret-value" not in str(row)

    # 库里的值是密文
    from app import db
    with db.connect() as conn:
        raw = db.one(conn, "SELECT headers_enc FROM sources WHERE id=?",
                     (src["id"],))["headers_enc"]
    assert raw and "secret-value" not in raw


def test_source_headers_can_be_revealed_explicitly(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h, headers=[{"name": "Cookie", "value": "acw_tc=xyz"}])
    r = client.post(f"/api/v1/sources/{src['id']}/reveal", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["headers"] == [{"name": "Cookie", "value": "acw_tc=xyz"}]


def test_source_headers_can_be_cleared(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h, headers=[{"name": "Cookie", "value": "a=b"}])
    r = client.put(f"/api/v1/sources/{src['id']}", headers=h, json={
        "name": src["name"], "url": src["name"] and "https://a.example.com/sub?token=abc123",
        "headers": [],
    })
    assert r.status_code == 200, r.text
    assert r.json()["headers"] == []


def test_source_headers_reject_bad_input(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "机场B", "url": "https://b.example.com/s",
        "headers": [{"name": "Bad Header", "value": "x"}]})
    assert r.status_code == 400
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "机场B", "url": "https://b.example.com/s",
        "headers": [{"name": "Cookie", "value": "a\r\nX-Evil: 1"}]})
    assert r.status_code == 400
    r = client.post("/api/v1/sources", headers=h, json={
        "name": "机场B", "url": "https://b.example.com/s",
        "headers": [{"name": "A", "value": "1"}, {"name": "a", "value": "2"}]})
    assert r.status_code == 400


# ---- 文件来源 ----

def test_import_source_from_clash_yaml_file(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "文件机场", "content_b64": _b64(CLASH_YAML)})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["source_kind"] == "file"
    assert data["node_count"] == 2
    assert [n["name"] for n in data["nodes"]] == ["香港01", "日本01"]
    # 文件来源没有在线地址，也不参与自动抓取
    assert data["auto_fetch"] is False


def test_import_source_from_base64_uri_list(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 上传的文件本身就是「base64 文本」（机场导出的常见形态），
    # 传输时再包一层 base64，所以这里是两次编码
    r = client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "文件机场2", "content_b64": _b64(_b64(URI_LIST.encode()).encode())})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["node_count"] == 2
    names = [n["name"] for n in data["nodes"]]
    assert names == ["SS节点", "Trojan节点"]


def test_import_source_file_rejects_unparsable_content(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "坏文件", "content_b64": _b64(b"<html>waf</html>")})
    assert r.status_code == 400
    assert "网页" in r.json()["detail"]


def test_file_source_participates_in_build(client):
    """文件来源是订阅来源：照常进产物、走策略组。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "文件机场", "content_b64": _b64(CLASH_YAML)})
    r = client.post("/api/v1/groups", headers=h, json={
        "name": "文件组", "type": "select", "proxies": ["DIRECT"],
        "use_sources": ["文件机场"]})
    assert r.status_code == 201, r.text
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build
    publish_to_prod(client, h, build["id"])
    target = client.get("/api/v1/targets", headers=h).json()[0]
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "iPhone", "platform": target["platform"],
        "target_id": target["id"]}).json()
    body = client.get(f"/feed/{dev['token']}/config.yaml").text
    assert "hk.example.com" in body
    assert "文件组" in body


def test_file_source_refresh_is_rejected(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "文件机场", "content_b64": _b64(CLASH_YAML)})
    sid = r.json()["id"]
    r = client.post(f"/api/v1/sources/{sid}/refresh", headers=h)
    assert r.status_code in (400, 502), r.text


def test_file_source_can_be_replaced(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/sources/import-file", headers=h, json={
        "name": "文件机场", "content_b64": _b64(CLASH_YAML)})
    sid = r.json()["id"]
    newer = CLASH_YAML + ("  - name: 韩国01\n    type: ss\n    server: kr.example.com\n"
                          "    port: 443\n    cipher: aes-256-gcm\n    password: pw\n").encode()
    r = client.put(f"/api/v1/sources/{sid}/file", headers=h, json={
        "name": "文件机场", "content_b64": _b64(newer)})
    assert r.status_code == 200, r.text
    assert r.json()["node_count"] == 3


# ---- 面板自身域名 ----

def test_panel_domain_is_kept_out_of_fake_ip(client):
    """面板自己的域名必须在 Fake-IP 排除清单里：客户端拿真实 IP 去更新订阅。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    target = client.get("/api/v1/targets", headers=h).json()[0]
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "iPhone", "platform": target["platform"],
        "target_id": target["id"]}).json()
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    publish_to_prod(client, h, build["id"])
    body = client.get(f"/feed/{dev['token']}/config.yaml").text
    assert "fake-ip-filter" in body
    # 面板域名以 +. 形式出现在排除清单里
    import re
    flt = re.search(r"fake-ip-filter:\n((?:\s+- .*\n)+)", body)
    assert flt, body[:500]
    assert "+." in flt.group(1)


def test_source_header_value_null_keeps_existing_value(client):
    """值不回显，编辑时留空即保持原值（null 语义）。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h, headers=[
        {"name": "Cookie", "value": "acw_tc=keepme"},
        {"name": "X-Token", "value": "old"},
    ])
    r = client.put(f"/api/v1/sources/{src['id']}", headers=h, json={
        "name": src["name"], "url": "https://a.example.com/sub?token=abc123",
        "headers": [
            {"name": "Cookie", "value": None},
            {"name": "X-Token", "value": "new"},
        ],
    })
    assert r.status_code == 200, r.text
    revealed = client.post(f"/api/v1/sources/{src['id']}/reveal", headers=h).json()
    values = {x["name"]: x["value"] for x in revealed["headers"]}
    assert values["Cookie"] == "acw_tc=keepme"
    assert values["X-Token"] == "new"


def test_new_header_without_value_is_rejected(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    src = _source(client, h, headers=[{"name": "Cookie", "value": "a=b"}])
    r = client.put(f"/api/v1/sources/{src['id']}", headers=h, json={
        "name": src["name"], "url": "https://a.example.com/sub?token=abc123",
        "headers": [{"name": "Brand-New", "value": None}],
    })
    assert r.status_code == 400
