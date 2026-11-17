"""check_secrets.py 自身的回归（2026-11-18）：新模式要能抓真凭据、放过 fixture。"""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "check_secrets",
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "check_secrets.py"))
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)
scan = _mod.scan


def test_private_key_block_is_caught():
    hits = scan("a.yaml", "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n")
    assert hits and "私钥块" in hits[0]


def test_fernet_token_is_caught():
    token = "gAAAA" + "A" * 60
    hits = scan("a.py", f'enc = "{token}"')
    assert hits and "Fernet" in hits[0]


def test_proxy_uri_with_credentials_is_caught():
    hits = scan("a.md", "节点 vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443?x=1#n")
    assert hits and "代理分享链接" in hits[0]


def test_doc_protocol_mentions_are_not_flagged():
    assert scan("docs/a.md", "支持 ss:// / trojan:// / vmess:// / vless:// 两种格式") == []


def test_test_fixture_examples_are_exempt():
    assert scan("server/tests/a.py", "-----BEGIN OPENSSH PRIVATE KEY-----\\nxxx\\n") == []
    assert scan("server/tests/a.py", "ss://YWVzLTI1Ni1nY206cHctaGtleQ@ss.example.com:443#SS节点") == []
