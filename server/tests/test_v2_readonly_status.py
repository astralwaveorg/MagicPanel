"""状态读取不能成为出网探针或直连证明。"""
from conftest import setup_admin


def test_direct_status_is_read_only_even_with_expired_cache(client, monkeypatch):
    setup_admin(client)
    from app.services import direct
    def forbidden(*args, **kwargs):
        raise AssertionError("status_get_attempted_probe")
    monkeypatch.setattr(direct, "_fetch_egress", forbidden)
    monkeypatch.setattr(direct, "_cache", {"at": 0.0, "data": {
        "ip": "192.0.2.9", "country_code": "CN", "password": "fixture-secret",
    }})
    result = client.get("/api/v1/direct-check")
    assert result.status_code == 200
    body = result.json()
    assert body["state"] == "unknown"
    assert body["freshness"] == "stale"
    assert body["egress"] == {"ip": "192.0.2.9", "country_code": "CN"}
    assert "fixture-secret" not in result.text


def test_legacy_refresh_requires_bounded_task_preview(client, monkeypatch):
    setup_admin(client)
    from app.services import direct
    monkeypatch.setattr(direct, "_fetch_egress", lambda: (_ for _ in ()).throw(
        AssertionError("legacy_refresh_attempted_probe")))
    response = client.get("/api/v1/direct-check?refresh=1")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "action_required"


def test_empty_status_has_no_implied_probe_or_direct_success(client, monkeypatch):
    setup_admin(client)
    from app.services import direct
    monkeypatch.setattr(direct, "_cache", {"at": 0.0, "data": None})
    result = client.get("/api/v1/direct-check").json()
    assert result["state"] == "unknown"
    assert result["freshness"] == "unknown"
    assert not result["egress"]
    assert not result["checked_at"]


def test_egress_country_never_attests_transparent_proxy_bypass(client, monkeypatch):
    from app.services import direct
    monkeypatch.setenv("HTTP_PROXY", "http://user:fixture-secret@proxy.example.com")
    monkeypatch.setattr(direct, "_fetch_egress", lambda: {
        "ip": "192.0.2.9", "country_code": "CN",
    })
    result = direct.check(refresh=True)
    assert result["state"] == "unknown"
    assert result["source_kind"] == "egress_reported"
    assert result["freshness"] == "fresh"
    assert "fixture-secret" not in str(result)
