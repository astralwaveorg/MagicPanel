"""解锁检测引擎：状态映射、Cloudflare 判别、地区标记、缓存合并。"""
import json

import pytest

from app.services import unlock_check as u


class _StubResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


class _StubClient:
    def __init__(self, responses):
        self.responses = responses

    def __get__(self, *a):  # 支持 with
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return self.responses[url]


def _patch(monkeypatch, responses):
    def fake_client(proxy):
        return _StubClient(responses)
    monkeypatch.setattr(u, "_client", fake_client)


def test_unlocked_and_region_extraction(monkeypatch):
    check = {"id": "yt", "url": "https://www.youtube.com/premium",
             "unlock": {200}, "region_regex": r'"countryCode":"(\w\w)"'}
    _patch(monkeypatch, {"https://www.youtube.com/premium":
                         _StubResp(200, '{"countryCode":"US"}')})
    r = u._run_single(check, None)
    assert r["state"] == "unlocked" and r["region"] == "US"


def test_cloudflare_challenge_is_error_not_blocked(monkeypatch):
    check = {"id": "cf", "url": "https://x.example/", "unlock": {200}}
    _patch(monkeypatch, {"https://x.example/": _StubResp(
        403, "Just a moment... challenge-platform verification")})
    r = u._run_single(check, None)
    assert r["state"] == "error"
    assert "Cloudflare" in r["detail"]


def test_region_marker_overrides_default_blocked(monkeypatch):
    check = {"id": "claude", "url": "https://claude.ai/", "unlock": {200},
             "region_marker": r"not available in your region"}
    _patch(monkeypatch, {"https://claude.ai/": _StubResp(
        403, "Claude is not available in your region.")})
    assert u._run_single(check, None)["state"] == "blocked"
    _patch(monkeypatch, {"https://claude.ai/": _StubResp(
        403, "Rate limited challenge")})
    r = u._run_single(check, None)
    assert r["state"] == "error"


def test_unsupported_only_when_declared(monkeypatch):
    check = {"id": "a", "url": "https://a.example/", "unlock": {200},
             "unsupported": {404}}
    _patch(monkeypatch, {"https://a.example/": _StubResp(404)})
    assert u._run_single(check, None)["state"] == "unsupported"
    check2 = {"id": "b", "url": "https://b.example/", "unlock": {200}}
    _patch(monkeypatch, {"https://b.example/": _StubResp(404)})
    assert u._run_single(check2, None)["state"] == "error"


def test_timeout_is_error(monkeypatch):
    class _Boom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            raise u.httpx.ConnectTimeout("boom")
    monkeypatch.setattr(u, "_client", lambda proxy: _Boom())
    check = {"id": "t", "url": "https://t.example/", "unlock": {200}}
    r = u._run_single(check, None)
    assert r["state"] == "error" and r["status"] is None


def test_cache_merge_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "_CACHE_PATH", tmp_path / "cache.json")
    full = {"checked_at": 1, "exit": "panel",
            "results": [{"id": "a", "state": "unlocked", "status": 200},
                        {"id": "b", "state": "blocked", "status": 403}]}
    u._save_cache("panel", full, merge=False)
    partial = {"checked_at": 2, "exit": "panel",
               "results": [{"id": "a", "state": "blocked", "status": 403}]}
    u._save_cache("panel", partial, merge=True)
    merged = u.last_results("panel")
    states = {r["id"]: r["state"] for r in merged["results"]}
    assert states == {"a": "blocked", "b": "blocked"}
    assert merged["checked_at"] == 2


def test_catalog_integrity():
    ids = [c["id"] for c in u.CHECKS]
    assert len(ids) == len(set(ids)), "检测 id 必须唯一"
    for c in u.CHECKS:
        assert c["category"] in u.CATEGORY_NAMES
        assert c["url"].startswith("https://")
