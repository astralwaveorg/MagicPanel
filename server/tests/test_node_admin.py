"""node_admin 解析与命名的纯函数测试（不连数据库、不外发请求）。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "node_admin_cli", ROOT / "scripts" / "node_admin.py")
node_admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(node_admin)


def test_parse_vless_reality():
    parsed = node_admin.parse_vless(
        "vless://11111111-2222-3333-4444-555555555555@203.0.113.9:443"
        "?encryption=none&security=reality&sni=www.example.com&fp=chrome"
        "&pbk=PUBLIC_KEY&sid=abcd1234&type=tcp#demo")
    assert parsed["protocol"] == "vless"
    assert parsed["server"] == "203.0.113.9"
    assert parsed["port"] == 443
    assert parsed["params"]["uuid"] == "11111111-2222-3333-4444-555555555555"
    assert parsed["params"]["reality_public_key"] == "PUBLIC_KEY"
    assert parsed["params"]["reality_short_id"] == "abcd1234"
    assert parsed["params"]["servername"] == "www.example.com"
    assert parsed["params"]["tls"] is True
    assert parsed["params"]["network"] == "tcp"


def test_parse_source_prefers_url_in_report():
    report = """
  ▸ VLESS 分享链接
  vless://11111111-2222-3333-4444-555555555555@203.0.113.9:30033?security=reality&sni=www.example.com&pbk=PK&sid=SID&type=tcp#x

  ▸ Clash / Mihomo 节点配置
proxies:
  - name: "x"
    type: vless
    server: 198.51.100.1
"""
    parsed = node_admin.parse_source(report)
    assert parsed["server"] == "203.0.113.9"
    assert parsed["port"] == 30033


def test_parse_clash_stops_at_trailing_text():
    text = """proxies:
  - name: "demo"
    type: vless
    server: 198.51.100.7
    port: 8443
    uuid: 11111111-2222-3333-4444-555555555555
    network: tcp
    tls: true
    udp: true
    servername: www.example.com
    reality-opts:
      public-key: PK
      short-id: SID
    client-fingerprint: chrome
────────────
维护提示
"""
    parsed = node_admin.parse_clash(text)
    assert parsed["protocol"] == "vless"
    assert parsed["server"] == "198.51.100.7"
    assert parsed["port"] == 8443
    assert parsed["params"]["reality_public_key"] == "PK"


def test_parse_hysteria2():
    parsed = node_admin.parse_source(
        "hy2://secret@203.0.113.10:8443?sni=example.com&insecure=1&obfs=salamander")
    assert parsed["protocol"] == "hysteria2"
    assert parsed["port"] == 8443
    assert parsed["params"]["password"] == "secret"
    assert parsed["params"]["skip_cert_verify"] is True


def test_parse_ss_sip002():
    import base64
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:pass").decode().rstrip("=")
    parsed = node_admin.parse_source(f"ss://{userinfo}@203.0.113.11:8388#demo")
    assert parsed["protocol"] == "ss"
    assert parsed["params"]["cipher"] == "aes-256-gcm"
    assert parsed["params"]["password"] == "pass"


def test_next_name():
    existing = ["🇺🇸 美国自建 01", "🇺🇸 美国自建 04", "🇯🇵 日本自建 02"]
    assert node_admin.next_name(existing, "🇺🇸 美国自建") == "🇺🇸 美国自建 05"
    assert node_admin.next_name([], "🇸🇬 新加坡自建") == "🇸🇬 新加坡自建 01"
