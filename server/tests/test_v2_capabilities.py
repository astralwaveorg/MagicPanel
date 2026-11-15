"""角色与实际 HTTP 副作用边界。"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from conftest import setup_admin


@pytest.fixture(autouse=True)
def deny_external_operations(client, monkeypatch):
    from app.services import tester
    monkeypatch.setattr(tester, "install_core", lambda **kw: {"version": "fixture", "sha256": "fixture"})


def _admin(client):
    setup_admin(client)
    token = client.cookies.get("mp_session")
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _user(client, admin, role="operator", name=None):
    name = name or f"fixture-{role}"
    body = {"username": name, "password": "fixture-password-1"}
    if role is not None:
        body["role"] = role
    created = client.post("/api/v1/users", headers=admin, json=body)
    assert created.status_code == 201, created.text
    login = client.post("/api/v1/auth/login", json={
        "username": name, "password": "fixture-password-1"})
    assert login.status_code == 200, login.text
    token = client.cookies.get("mp_session")
    client.cookies.clear()
    return created.json(), {"Authorization": f"Bearer {token}"}


def _source(client, admin):
    r = client.post("/api/v1/sources", headers=admin, json={
        "name": "fixture-source", "url": "https://sub.example.com/sub?token=fixture-secret",
        "headers": [{"name": "Cookie", "value": "fixture-cookie-secret"}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_roles_reject_unknown_actions_and_operator_privilege_escalation(client):
    from app.services.capabilities import effective_capabilities, require_capability
    operator = {"role": "operator"}
    for action in ("view", "edit", "probe", "publish_test", "runtime_read"):
        require_capability(operator, action)
    for action in ("reveal", "publish_prod", "manage_users", "restore", "backup",
                   "runtime_write", "not-an-action"):
        with pytest.raises(HTTPException) as error:
            require_capability(operator, action)
        assert error.value.status_code == 403
        assert error.value.detail["code"] == "forbidden"
        assert error.value.detail["request_id"]
    assert effective_capabilities({"role": "unknown"}) == frozenset()
    assert effective_capabilities({"role": "viewer"}) == frozenset({"view"})


def test_new_users_default_operator_and_me_exposes_effective_capabilities(client):
    admin = _admin(client)
    created, operator = _user(client, admin, None, "default-user")
    assert created["role"] == "operator"
    me = client.get("/api/v1/auth/me", headers=operator).json()
    assert set(me["capabilities"]) == {"view", "edit", "probe", "publish_test", "runtime_read"}
    assert "portal_pin_hash" not in me
    assert client.post("/api/v1/users", headers=operator, json={
        "username": "cannot-admin", "password": "fixture-password-1", "role": "admin"
    }).status_code == 403
    assert client.post("/api/v1/users", headers=admin, json={
        "username": "invalid-role", "password": "fixture-password-1", "role": "superuser"
    }).status_code == 422


def test_viewer_http_rejection_precedes_fetch_test_publish_and_restore(client, monkeypatch):
    from app import db
    from app.services import updater
    admin = _admin(client)
    source = _source(client, admin)
    _, viewer = _user(client, admin, "viewer")
    calls = []
    monkeypatch.setattr(updater, "refresh_source", lambda *a, **k: calls.append("refresh"))
    monkeypatch.setattr(updater, "test_source", lambda *a, **k: calls.append("test"))
    assert client.get("/api/v1/groups", headers=viewer).status_code == 200
    with db.connect() as conn:
        before = tuple(conn.iterdump())
    for url, body in [
        (f"/api/v1/sources/{source['id']}/refresh", {}),
        (f"/api/v1/sources/{source['id']}/test", {}),
        ("/api/v1/builds/999/publish-both", {}),
        ("/api/v1/backup/restore", {"confirm": True, "data": {}}),
        ("/api/v1/backup/webdav/restore", {"confirm": True, "data": {"file": "fixture.mpa"}}),
        ("/api/v1/portal/my-pin", {"pin": "1234"}),
    ]:
        r = client.post(url, headers=viewer, json=body)
        assert r.status_code == 403, (url, r.text)
        assert r.json()["detail"]["code"] == "forbidden"
    assert calls == []
    with db.connect() as conn:
        assert tuple(conn.iterdump()) == before


def test_operator_source_metadata_allowed_but_keep_secret_retarget_rejected(client):
    admin = _admin(client)
    source = _source(client, admin)
    _, operator = _user(client, admin)
    url = f"/api/v1/sources/{source['id']}"
    edited = client.put(url, headers=operator, json={"name": source["name"], "suffix": "-safe"})
    assert edited.status_code == 200, edited.text
    for patch in ({"url": "https://other.example.com/sub"}, {"proxy_url": "http://proxy.example.com:8080"},
                  {"headers": [{"name": "Cookie", "value": None}]}, {"allow_private": True},
                  {"ua": "retarget-UA"}):
        result = client.put(url, headers=operator, json={"name": source["name"], **patch})
        assert result.status_code == 403, result.text
    assert client.post(url + "/reveal", headers=operator).status_code == 403
    revealed = client.post(url + "/reveal", headers=admin)
    assert revealed.status_code == 200
    assert revealed.headers["cache-control"] == "no-store"
    assert "fixture-cookie-secret" in revealed.text


def test_raw_configuration_restricted_but_safe_schema_readable(client):
    admin = _admin(client)
    _, viewer = _user(client, admin, "viewer")
    assert client.get("/api/v1/base-config/scopes", headers=viewer).status_code == 200
    assert client.get("/api/v1/base-config", headers=viewer).status_code == 403
    assert client.get("/api/v1/base-config", headers=admin).headers["cache-control"] == "no-store"


def test_settings_public_projection_omits_private_values(client):
    from app import db
    admin = _admin(client)
    with db.tx() as conn:
        db.set_setting(conn, "deps_private_key_enc", "fixture-encrypted-private-key")
        db.set_setting(conn, "core_proxy", "http://fixture-user:fixture-pass@proxy.example.com:8080")
    _, viewer = _user(client, admin, "viewer")
    response = client.get("/api/v1/settings", headers=viewer)
    assert response.status_code == 200
    assert "fixture-encrypted-private-key" not in response.text
    assert "fixture-pass" not in response.text
    assert "deps_private_key_enc" not in response.json()


def test_operator_automation_prod_precheck_precedes_background_work(client, monkeypatch):
    from app import db
    from app.services import scheduler
    admin = _admin(client)
    _, operator = _user(client, admin)
    calls = []
    monkeypatch.setattr(scheduler, "run_once_safe", lambda *a, **k: calls.append("run"))
    with db.tx() as conn:
        for key, value in {"auto_build_enabled": "1", "auto_publish_enabled": "1",
                           "auto_publish_env": "production"}.items():
            db.set_setting(conn, key, value)
    denied = client.post("/api/v1/automation/run", headers=operator)
    assert denied.status_code == 403, denied.text
    assert calls == []
    with db.tx() as conn:
        db.set_setting(conn, "auto_publish_env", "testing")
    assert client.post("/api/v1/automation/run", headers=operator).status_code == 200
    assert calls == ["run"]


def test_operator_cannot_enable_production_automation_or_retarget_webdav(client):
    admin = _admin(client)
    _, operator = _user(client, admin)
    for values in ({"auto_publish_enabled": "1"}, {"auto_publish_env": "production"}):
        assert client.put("/api/v1/settings", headers=operator, json={"values": values}).status_code == 403
    assert client.put("/api/v1/backup/webdav", headers=operator, json={
        "values": {"url": "https://other.example.com/dav", "password": ""}}).status_code == 403
    assert client.post("/api/v1/core/install", headers=operator).status_code == 403


def test_viewer_cookie_csrf_and_portal_pin_do_not_grant_reveal(client):
    admin = _admin(client)
    assert client.post("/api/v1/portal/my-pin", headers=admin, json={"pin": "7291"}).status_code == 201
    _, viewer = _user(client, admin, "viewer")
    token = viewer["Authorization"].removeprefix("Bearer ")
    client.cookies.set("mp_session", token)
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
    assert client.post("/api/v1/portal/my-pin", headers={"X-CSRF-Token": csrf},
                       json={"pin": "1234"}).status_code == 403
    portal = client.post("/api/v1/portal/data", json={"pin": ""})
    assert portal.status_code in (401, 403)
    assert "subscription_url" not in portal.text
    assert client.post("/api/v1/portal/data", json={"pin": "7291"}).status_code == 200
    client.cookies.clear()
    assert client.get("/api/v1/base-config", headers={"X-Portal-Pin": "7291"}).status_code == 401


def test_role_downgrade_revokes_sessions_and_portal_pin(client):
    from app import db
    admin = _admin(client)
    second, second_auth = _user(client, admin, "admin")
    assert client.post("/api/v1/portal/my-pin", headers=second_auth, json={"pin": "7291"}).status_code == 201
    changed = client.patch(f"/api/v1/users/{second['id']}/role", headers=admin, json={"role": "viewer"})
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/auth/me", headers=second_auth).status_code == 401
    with db.connect() as conn:
        assert conn.execute("SELECT portal_pin_hash FROM users WHERE id=?", (second["id"],)).fetchone()[0] == ""
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (second["id"],)).fetchone()[0] == 0
    assert client.post("/api/v1/portal/data", json={"pin": "7291"}).status_code in (403, 404)


def test_last_admin_cannot_be_deleted_or_downgraded(client):
    admin = _admin(client)
    _user(client, admin, "viewer")
    me = client.get("/api/v1/auth/me", headers=admin).json()
    assert client.patch(f"/api/v1/users/{me['id']}/role", headers=admin, json={"role": "viewer"}).status_code == 400
    assert client.delete(f"/api/v1/users/{me['id']}", headers=admin).status_code == 400


def test_concurrent_admin_downgrades_leave_one_admin(client):
    from app import db
    admin = _admin(client)
    second, second_auth = _user(client, admin, "admin")
    first = client.get("/api/v1/auth/me", headers=admin).json()
    def downgrade(user_id):
        return client.patch(f"/api/v1/users/{user_id}/role", headers=admin, json={"role": "viewer"}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(downgrade, [first["id"], second["id"]]))
    assert statuses.count(200) == 1, statuses
    assert all(status in (200, 400, 401, 403) for status in statuses)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 1


def test_viewer_self_service_password_and_logout_are_allowed(client):
    from app import db
    admin = _admin(client)
    viewer, auth = _user(client, admin, "viewer")
    denied = client.delete("/api/v1/users/1", headers=auth)
    assert denied.status_code == 403
    changed = client.post("/api/v1/auth/password", headers=auth, json={
        "old_password": "fixture-password-1", "new_password": "fixture-updated-pass"})
    assert changed.status_code == 200, changed.text
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth).status_code == 401
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_operator_local_metadata_does_not_expose_or_retarget_secrets(client):
    admin = _admin(client)
    body = {"name": "fixture-local", "protocol": "trojan", "server": "node.example.com",
            "port": 443, "params": {"password": "fixture-node-secret", "sni": "node.example.com"}}
    created = client.post("/api/v1/local-nodes", headers=admin, json=body)
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    _, operator = _user(client, admin)
    listing = client.get("/api/v1/local-nodes", headers=operator)
    assert listing.status_code == 200
    assert "fixture-node-secret" not in listing.text
    enabled = client.patch(f"/api/v1/local-nodes/{node_id}/enabled", headers=operator,
                           json={"enabled": False})
    assert enabled.status_code == 200
    assert "fixture-node-secret" not in enabled.text
    for patch in ({"server": "other.example.com"}, {"params": {"sni": "other.example.com"}}):
        denied = client.put(f"/api/v1/local-nodes/{node_id}", headers=operator,
                            json={**body, **patch})
        assert denied.status_code == 403, denied.text


def test_device_credentials_and_platform_raw_yaml_require_reveal(client):
    admin = _admin(client)
    target = client.post("/api/v1/targets", headers=admin, json={
        "name": "fixture-target", "engine": "stash", "platform": "ios",
        "extra_yaml": "secret: fixture-platform-secret\n"}).json()
    device = client.post("/api/v1/devices", headers=admin, json={
        "name": "fixture-device", "platform": "ios", "target_id": target["id"]}).json()
    _, operator = _user(client, admin)
    for endpoint in ("/api/v1/targets", "/api/v1/targets/page"):
        response = client.get(endpoint, headers=operator)
        assert response.status_code == 200
        assert "fixture-platform-secret" not in response.text
        assert "extra_yaml" not in response.text
    for endpoint, body in [
        ("/api/v1/devices", {"name": "unauthorized-device", "platform": "ios", "target_id": target["id"]}),
        (f"/api/v1/devices/{device['id']}/rotate-token", {}),
        (f"/api/v1/devices/{device['id']}/reveal", {}),
        (f"/api/v1/targets/{target['id']}/reveal", {}),
    ]:
        response = client.post(endpoint, headers=operator, json=body)
        assert response.status_code == 403, response.text
        assert device["token"] not in response.text
    raw = client.post(f"/api/v1/targets/{target['id']}/reveal", headers=admin)
    assert raw.status_code == 200
    assert raw.headers["cache-control"] == "no-store"
    assert "fixture-platform-secret" in raw.text
    # 元数据修改省略原文，保留既有平台扩展。
    result = client.put(f"/api/v1/targets/{target['id']}", headers=operator, json={
        "name": "fixture-target", "engine": "stash", "platform": "ios", "description": "safe"})
    assert result.status_code == 200, result.text
    changed = client.put(f"/api/v1/targets/{target['id']}", headers=operator, json={
        "name": "fixture-target", "engine": "stash", "platform": "ios", "extra_yaml": "secret: changed\n"})
    assert changed.status_code == 403
    assert "fixture-platform-secret" in client.post(
        f"/api/v1/targets/{target['id']}/reveal", headers=admin).text


def test_build_snapshot_only_available_through_explicit_reveal(client):
    from app import db, security
    admin = _admin(client)
    # 不启动真实核心；只需一份加密构建快照验证 API 边界。
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO builds(created_at, created_by, snapshot, policy_sha) VALUES(?,?,?,?)",
                           (db.now(), "fixture", security.encrypt_payload('{"fixture":"fixture-build-secret"}'), "fixture"))
        bid = cur.lastrowid
    assert "fixture-build-secret" not in client.get(f"/api/v1/builds/{bid}", headers=admin).text
    _, operator = _user(client, admin)
    assert client.post(f"/api/v1/builds/{bid}/reveal", headers=operator).status_code == 403
    revealed = client.post(f"/api/v1/builds/{bid}/reveal", headers=admin)
    assert revealed.status_code == 200
    assert revealed.headers["cache-control"] == "no-store"
    assert revealed.json()["snapshot"] == {"fixture": "fixture-build-secret"}


def test_get_direct_diagnostics_never_starts_probe(client, monkeypatch):
    from app.services import direct
    admin = _admin(client)
    _, viewer = _user(client, admin, "viewer")
    calls = []
    monkeypatch.setattr(direct, "_fetch_egress", lambda: calls.append("network"))
    monkeypatch.setattr(direct, "_cache", {"data": None, "at": 0.0})
    response = client.get("/api/v1/direct-check", headers=viewer)
    assert response.status_code == 200
    assert response.json()["state"] == "unknown"
    refresh = client.get("/api/v1/direct-check?refresh=true", headers=admin)
    assert refresh.status_code == 409
    assert refresh.json()["detail"]["code"] == "action_required"
    assert client.post("/api/v1/direct-check", headers=admin).status_code == 405
    assert calls == []


@pytest.mark.parametrize("change", ["production", "downgrade"])
def test_queued_manual_worker_rechecks_before_any_fetch(client, monkeypatch, change):
    from app import db
    from app.services import scheduler
    admin = _admin(client)
    operator, auth = _user(client, admin)
    with db.tx() as conn:
        db.set_setting(conn, "auto_publish_env", "testing")
    queued = []
    monkeypatch.setattr(scheduler, "run_once_safe", lambda *a, **kw: queued.append((a, kw)))
    assert client.post("/api/v1/automation/run", headers=auth).status_code == 200
    if change == "production":
        with db.tx() as conn:
            db.set_setting(conn, "auto_publish_env", "production")
    else:
        assert client.patch(f"/api/v1/users/{operator['id']}/role", headers=admin,
                            json={"role": "viewer"}).status_code == 200
    calls = []
    monkeypatch.setattr(scheduler, "_run_source_fetch", lambda *a, **kw: calls.append("fetch"))
    monkeypatch.setattr(scheduler, "_run_rule_fetch", lambda *a, **kw: calls.append("rules"))
    monkeypatch.setattr(scheduler, "_run_snippet_fetch", lambda *a, **kw: calls.append("snippets"))
    monkeypatch.setattr(scheduler, "_run_deps_sync", lambda *a, **kw: calls.append("deps"))
    monkeypatch.setattr(scheduler, "_run_source_test", lambda *a, **kw: calls.append("test"))
    monkeypatch.setattr(scheduler, "_run_auto_build", lambda *a, **kw: calls.append("build"))
    with pytest.raises(HTTPException) as denied:
        scheduler.run_once(*queued[0][0], **queued[0][1])
    assert denied.value.status_code == 403
    assert calls == []


def test_worker_rechecks_env_and_role_before_build(client, monkeypatch):
    from app import db
    from app.services import scheduler
    from datetime import datetime, timezone
    admin = _admin(client)
    operator, _ = _user(client, admin)
    calls = []
    monkeypatch.setattr(scheduler.builds, "current_policy", lambda *a: calls.append("snapshot"))
    with db.tx() as conn:
        db.set_setting(conn, "auto_build_enabled", "1")
        db.set_setting(conn, "auto_publish_enabled", "1")
        db.set_setting(conn, "auto_publish_env", "production")
    with pytest.raises(HTTPException) as denied:
        scheduler._run_auto_build({}, datetime.now(timezone.utc), force=True,
                                  actor_user_id=operator["id"])
    assert denied.value.status_code == 403
    assert calls == []


def test_operator_metadata_preserves_source_transport_and_snippet_source(client):
    admin = _admin(client)
    source = client.post("/api/v1/sources", headers=admin, json={
        "name": "preserved-source", "url": "https://fixture.example.com/sub",
        "ua": "FixtureOriginalUA", "allow_private": True}).json()
    snippet = client.post("/api/v1/snippets", headers=admin, json={
        "name": "preserved-snippet", "content": "secret: fixture-snippet-secret\n"}).json()
    _, operator = _user(client, admin)
    changed = client.put(f"/api/v1/sources/{source['id']}", headers=operator, json={
        "name": source["name"], "suffix": "-metadata"})
    assert changed.status_code == 200
    assert changed.json()["ua"] == "FixtureOriginalUA"
    assert changed.json()["allow_private"] is True
    changed = client.put(f"/api/v1/snippets/{snippet['id']}", headers=operator, json={
        "name": snippet["name"], "note": "safe metadata"})
    assert changed.status_code == 200, changed.text
    assert "fixture-snippet-secret" not in changed.text
    assert "fixture-snippet-secret" in client.post(
        f"/api/v1/snippets/{snippet['id']}/reveal", headers=admin).text
    assert client.put(f"/api/v1/snippets/{snippet['id']}", headers=operator, json={
        "name": snippet["name"], "content": "secret: retarget\n"}).status_code == 403


def test_reveal_audit_identifies_object_without_recording_material(client):
    import json
    from app import db
    admin = _admin(client)
    node = client.post("/api/v1/local-nodes", headers=admin, json={
        "name": "audit-fixture", "protocol": "trojan", "server": "node.example.com",
        "port": 443, "params": {"password": "fixture-audit-secret"}}).json()
    revealed = client.post(f"/api/v1/local-nodes/{node['id']}/reveal", headers=admin)
    assert revealed.status_code == 200
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM audit WHERE action='访问私密内容' ORDER BY id DESC LIMIT 1").fetchone()
    assert json.loads(row["detail"])["references"] == {"node_id": node["id"]}
    assert "fixture-audit-secret" not in str(tuple(row))


def test_webdav_restore_uses_server_owned_staging_and_current_key(client, monkeypatch):
    from app import config
    from app.services import webdav
    admin = _admin(client)
    captured = []
    def restore(conn, remote_name, actor, *, destination, key_path):
        captured.append((remote_name, actor, destination, key_path))
        return {"status": "STAGED", "verification_status": "VERIFIED", "restored": False,
                "staging_name": destination.name, "requires_maintenance_restart": True, "key_restored": False}
    monkeypatch.setattr(webdav, "restore_from_remote", restore)
    response = client.post("/api/v1/backup/webdav/restore", headers=admin, json={
        "confirm": True, "data": {"file": "fixture.mpa", "destination": "C:/client-cannot-select"}})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "STAGED"
    assert response.json()["restored"] is False
    assert response.json()["requires_maintenance_restart"] is True
    assert response.json()["verification_status"] == "VERIFIED"
    assert response.json()["key_restored"] is False
    assert str(config.DATA_DIR) not in response.text
    name, actor, destination, key_path = captured[0]
    assert name == "fixture.mpa" and actor == "admin"
    assert destination.parent == (config.DATA_DIR / "restore-staging").resolve()
    assert len(destination.name) == 32 and not destination.exists()
    assert key_path == config.SECRET_KEY_PATH
