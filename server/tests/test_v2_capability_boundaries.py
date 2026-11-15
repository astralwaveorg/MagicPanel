"""权限审查回归：历史记录、URL 投影和连接修改。"""
import socket

import httpx
import pytest

from conftest import setup_admin

RULE_URL = "https://fixture-user:fixture-rule-pass@rules.example.com/list?token=fixture-rule-token"
PROXY_URL = "http://fixture-proxy-user:fixture-proxy-pass@proxy.example.com:8080"
LEGACY_URL = "https://legacy.example.com/list?token=fixture-legacy-rule-token"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("external_network_forbidden_in_capability_boundary_test")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def _admin(client):
    setup_admin(client)
    token = client.cookies.get("mp_session")
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _user(client, admin, role):
    username = f"fixture-{role}"
    created = client.post("/api/v1/users", headers=admin, json={
        "username": username, "password": "fixture-user-pass", "role": role})
    assert created.status_code == 201, created.text
    assert client.post("/api/v1/auth/login", json={
        "username": username, "password": "fixture-user-pass"}).status_code == 200
    token = client.cookies.get("mp_session")
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _provider(client, admin):
    response = client.post("/api/v1/rule-providers", headers=admin, json={
        "name": "fixture-rule", "url": RULE_URL, "proxy_url": PROXY_URL,
        "behavior": "classical", "format": "yaml", "interval": 7200})
    assert response.status_code == 201, response.text
    return response


def _legacy_audit():
    from app import db, security
    detail = {"url": "https://fixture-user:fixture-audit-pass@audit.example.com/api?token=fixture-audit-token",
              "password": "fixture-legacy-password"}
    with db.tx() as conn:
        security.audit(conn, "legacy-admin", "historical-update", "settings", "legacy", detail)
        row = dict(conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 1").fetchone())
    return row


def _migration(provider_id):
    from app import db
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO repo_migrations(batch,object_type,object_id,origin_kind,origin_url,origin_behavior,switched_at) "
            "VALUES(?,?,?,?,?,?,?)", (9, "rule_provider", provider_id, "remote", LEGACY_URL, "domain", db.now()))
    return cur.lastrowid


def _assert_no_credentials(text):
    for marker in ("fixture-rule-pass", "fixture-rule-token", "fixture-proxy-pass",
                   "fixture-audit-pass", "fixture-audit-token", "fixture-legacy-password",
                   "fixture-legacy-rule-token"):
        assert marker not in text


@pytest.mark.parametrize("endpoint", ["/api/v1/audit", "/api/v1/overview"])
def test_historical_audit_is_safely_projected_without_changing_storage(client, endpoint):
    from app import db
    admin = _admin(client)
    viewer = _user(client, admin, "viewer")
    original = _legacy_audit()
    response = client.get(endpoint, headers=viewer)
    assert response.status_code == 200
    _assert_no_credentials(response.text)
    items = response.json()["items" if endpoint.endswith("audit") else "recent_audit"]
    historical = next(row for row in items if row["id"] == original["id"])
    assert historical["action"] == "historical-update"
    assert historical["has_detail"] is True
    assert "授权" in historical["summary"]
    with db.connect() as conn:
        assert dict(conn.execute("SELECT * FROM audit WHERE id=?", (original["id"],)).fetchone()) == original


def test_audit_search_does_not_query_hidden_historical_detail(client):
    admin = _admin(client)
    viewer = _user(client, admin, "viewer")
    _legacy_audit()
    hidden = client.get("/api/v1/audit?keyword=fixture-audit-token", headers=viewer)
    assert hidden.status_code == 200
    assert hidden.json()["total"] == 0 and hidden.json()["items"] == []
    visible = client.get("/api/v1/audit?keyword=historical-update", headers=viewer)
    assert visible.json()["total"] == 1


@pytest.mark.parametrize("endpoint", ["/api/v1/rule-providers", "/api/v1/rule-providers/page"])
def test_rule_provider_lists_hide_credential_urls(client, endpoint):
    admin = _admin(client)
    _provider(client, admin)
    viewer = _user(client, admin, "viewer")
    response = client.get(endpoint, headers=viewer)
    assert response.status_code == 200
    _assert_no_credentials(response.text)
    assert "rules.example.com" in response.text


def test_rule_provider_create_and_enabled_responses_use_same_safe_projection(client):
    admin = _admin(client)
    created = _provider(client, admin)
    _assert_no_credentials(created.text)
    operator = _user(client, admin, "operator")
    changed = client.patch(f"/api/v1/rule-providers/{created.json()['id']}/enabled",
                           headers=operator, json={"enabled": False})
    assert changed.status_code == 200
    _assert_no_credentials(changed.text)


def test_rule_provider_keyword_search_only_uses_public_url_summary(client):
    admin = _admin(client)
    _provider(client, admin)
    viewer = _user(client, admin, "viewer")
    hidden = client.get("/api/v1/rule-providers/page?keyword=fixture-rule-token", headers=viewer)
    assert hidden.status_code == 200
    assert hidden.json()["total"] == 0 and hidden.json()["items"] == []
    public = client.get("/api/v1/rule-providers/page?keyword=rules.example.com", headers=viewer)
    assert public.json()["total"] == 1


@pytest.mark.parametrize("field,value", [("url", "https://replacement.example.com/list"),
    ("proxy_url", "http://replacement.example.com:8080"), ("proxy_url", None),
    ("kind", "inline"), ("repo_path", "rule/replacement.yaml")])
def test_operator_cannot_change_rule_provider_connections(client, field, value):
    from app import db
    admin = _admin(client)
    provider = _provider(client, admin).json()
    operator = _user(client, admin, "operator")
    with db.connect() as conn:
        before = tuple(conn.iterdump())
    response = client.put(f"/api/v1/rule-providers/{provider['id']}", headers=operator,
                          json={"name": provider["name"], field: value})
    assert response.status_code == 403, response.text
    with db.connect() as conn:
        assert tuple(conn.iterdump()) == before


def test_rule_provider_metadata_preserves_omitted_connection_fields(client):
    from app import db, security
    admin = _admin(client)
    provider = _provider(client, admin).json()
    operator = _user(client, admin, "operator")
    response = client.put(f"/api/v1/rule-providers/{provider['id']}", headers=operator,
                          json={"name": provider["name"], "interval": 14400})
    assert response.status_code == 200, response.text
    _assert_no_credentials(response.text)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM rule_providers WHERE id=?", (provider["id"],)).fetchone()
        assert row["url"] == RULE_URL
        assert security.decrypt_text(row["proxy_url_enc"]) == PROXY_URL
        assert row["behavior"] == "classical" and row["interval"] == 14400
    assert client.post("/api/v1/rule-providers", headers=operator, json={
        "name": "unauthorized-new-source", "url": "https://replacement.example.com/list"}).status_code == 403


def test_migration_list_hides_origin_credentials_and_rollback_checks_reveal(client):
    from app import db
    admin = _admin(client)
    provider = _provider(client, admin).json()
    _migration(provider["id"])
    operator = _user(client, admin, "operator")
    response = client.get("/api/v1/deps/migrations", headers=operator)
    assert response.status_code == 200
    _assert_no_credentials(response.text)
    with db.connect() as conn:
        before = tuple(conn.iterdump())
    denied = client.post("/api/v1/deps/rollback-migration?batch=9", headers=operator)
    assert denied.status_code == 403
    with db.connect() as conn:
        assert tuple(conn.iterdump()) == before
    assert client.post("/api/v1/deps/rollback-migration?batch=9", headers=admin).status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT url FROM rule_providers WHERE id=?", (provider["id"],)).fetchone()[0] == LEGACY_URL


def test_explicit_rule_migration_and_audit_reveal_are_scoped_and_no_store(client):
    from app import db
    admin = _admin(client)
    provider = _provider(client, admin).json()
    migration_id = _migration(provider["id"])
    audit = _legacy_audit()
    viewer = _user(client, admin, "viewer")
    endpoints = [(f"/api/v1/rule-providers/{provider['id']}/reveal", "fixture-rule-token"),
                 (f"/api/v1/deps/migrations/{migration_id}/reveal", "fixture-legacy-rule-token"),
                 (f"/api/v1/audit/{audit['id']}/reveal", "fixture-audit-token")]
    with db.connect() as conn:
        baseline = conn.execute("SELECT MAX(id) FROM audit").fetchone()[0]
    for endpoint, marker in endpoints:
        denied = client.post(endpoint, headers=viewer)
        assert denied.status_code == 403, denied.text
        response = client.post(endpoint, headers=admin)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert marker in response.text
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM audit WHERE id>?", (baseline,)).fetchall()
    assert rows
    _assert_no_credentials(str([tuple(row) for row in rows]))


@pytest.mark.parametrize("endpoint", ["/api/v1/portal/data", "/api/v1/portal/provider-detail"])
def test_portal_pin_does_not_reveal_rule_origin_credentials(client, endpoint):
    admin = _admin(client)
    _provider(client, admin)
    assert client.post("/api/v1/portal/my-pin", headers=admin, json={"pin": "7291"}).status_code == 201
    response = client.post(endpoint, json={"pin": "7291", "name": "fixture-rule"})
    assert response.status_code == 200, response.text
    _assert_no_credentials(response.text)
    assert "rules.example.com" in response.text


@pytest.mark.parametrize("endpoint", ["/api/v1/rule-providers", "/api/v1/overview"])
def test_failure_summaries_do_not_return_credential_urls(client, endpoint):
    from app import db
    admin = _admin(client)
    provider = _provider(client, admin).json()
    viewer = _user(client, admin, "viewer")
    with db.tx() as conn:
        conn.execute("UPDATE rule_providers SET last_error=?, last_status='failed' WHERE id=?",
                     ("HTTP error for " + RULE_URL, provider["id"]))
    response = client.get(endpoint, headers=viewer)
    assert response.status_code == 200
    _assert_no_credentials(response.text)
    items = response.json()["rule_providers"] if endpoint.endswith("overview") else response.json()
    row = next(item for item in items if item["id"] == provider["id"])
    assert row["has_error"] is True and row["last_error"]
    revealed = client.post(f"/api/v1/rule-providers/{provider['id']}/reveal", headers=admin)
    assert revealed.status_code == 200 and "fixture-rule-token" in revealed.text


def test_rule_refresh_error_does_not_bypass_safe_error_projection(client, monkeypatch):
    from app.services import fetcher
    admin = _admin(client)
    provider = _provider(client, admin).json()
    operator = _user(client, admin, "operator")
    def fail(*args, **kwargs):
        raise fetcher.FetchError("HTTP error for " + RULE_URL)
    monkeypatch.setattr(fetcher, "fetch", fail)
    response = client.post(f"/api/v1/rule-providers/{provider['id']}/refresh", headers=operator)
    assert response.status_code == 502
    _assert_no_credentials(response.text)
    assert "保留" in response.text
    revealed = client.post(f"/api/v1/rule-providers/{provider['id']}/reveal", headers=admin)
    assert revealed.status_code == 200 and "fixture-rule-token" in revealed.json()["last_error"]


@pytest.mark.parametrize("endpoint", ["/api/v1/portal/data", "/api/v1/portal/provider-detail"])
@pytest.mark.parametrize("url,marker", [
    ("https://rules.example.com/list?token=https://github.com/fixture-portal-query-token/rules", "fixture-portal-query-token"),
    ("https://rules.example.com/github.com/fixture-portal-path-token/rules", "fixture-portal-path-token"),
    ("https://github.com:fixture-portal-userinfo-token@rules.example.com/rules", "fixture-portal-userinfo-token"),
    ("https://cdn.jsdelivr.net/npm/pkg/gh/fixture-portal-trusted-path-token/rules", "fixture-portal-trusted-path-token"),
    ("https://rules.example.com/list#https://cdn.jsdelivr.net/gh/fixture-portal-fragment-token/rules", "fixture-portal-fragment-token"),
])
def test_portal_origin_never_extracts_embedded_repository_urls(client, endpoint, url, marker):
    admin = _admin(client)
    created = client.post("/api/v1/rule-providers", headers=admin, json={
        "name": "fixture-origin", "url": url})
    assert created.status_code == 201, created.text
    assert marker not in created.text
    assert client.post("/api/v1/portal/my-pin", headers=admin, json={"pin": "7291"}).status_code == 201
    response = client.post(endpoint, json={"pin": "7291", "name": "fixture-origin"})
    assert response.status_code == 200, response.text
    assert marker not in response.text
    row = response.json()["rule_providers"][0] if endpoint.endswith("data") else response.json()
    assert row["origin"] == ""


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/astralwaveorg/magic-sets", "astralwaveorg/magic-sets"),
    ("https://github.com/astralwaveorg/magic-sets.git/tree/main/rule", "astralwaveorg/magic-sets"),
    ("https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/google.yaml", "MetaCubeX/meta-rules-dat"),
    ("https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Clash/Apple/Apple.yaml", "blackmatrix7/ios_rule_script"),
    ("git@github.com:astralwaveorg/magic-sets.git", "astralwaveorg/magic-sets"),
    ("ssh://git@github.com/astralwaveorg/magic-sets.git", "astralwaveorg/magic-sets"),
    ("https://fixture-user:fixture-pass@github.com/astralwaveorg/magic-sets?token=https://github.com/fixture-ignored/rules#ignored", "astralwaveorg/magic-sets"),
    ("https://github.com.evil.example/github.com/fixture-not-a-repository/rules", ""),
])
def test_provider_origin_uses_actual_host_and_repository_path(client, url, expected):
    from app.routers.portal import _provider_origin
    assert _provider_origin(url) == expected


@pytest.mark.parametrize("endpoint", ["/api/v1/portal/data", "/api/v1/portal/provider-detail"])
def test_repo_portal_origin_uses_configured_repository_not_stale_url(client, endpoint):
    from app import db
    admin = _admin(client)
    created = client.post("/api/v1/rule-providers", headers=admin, json={
        "name": "fixture-repo", "kind": "repo", "repo_path": "rule/demo.yaml",
        "url": "https://github.com/fixture-stale-url-token/rules"})
    assert created.status_code == 201, created.text
    with db.tx() as conn:
        db.set_setting(conn, "deps_url", "git@github.com:astralwaveorg/magic-sets.git")
    assert client.post("/api/v1/portal/my-pin", headers=admin, json={"pin": "7291"}).status_code == 201
    response = client.post(endpoint, json={"pin": "7291", "name": "fixture-repo"})
    assert response.status_code == 200
    assert "fixture-stale-url-token" not in response.text
    row = response.json()["rule_providers"][0] if endpoint.endswith("data") else response.json()
    assert row["origin"] == "astralwaveorg/magic-sets"
