"""V2 安全节点目录 API 与改名预演合同。"""
import pytest

from conftest import auth_headers
from v2_helpers import admin, make_local, assert_no_secrets


def test_node_page_has_safe_identity(client):
    h = admin(client)
    make_local(client, h)
    response = client.get('/api/v1/nodes?limit=1&offset=0', headers=h)
    assert response.status_code == 200, response.text
    page = response.json()
    assert set(page) == {'items', 'total', 'limit', 'offset', 'catalog_revision'}
    assert page['total'] == 1 and page['limit'] == 1 and page['offset'] == 0
    item = page['items'][0]
    assert len(item['node_uid']) == 32 and item['revision'] == 1
    assert {'raw_name', 'display_name', 'emit_name', 'meta'} <= set(item)
    assert_no_secrets(page)


def test_operator_metadata_allowed_but_secret_keep_retarget_denied(client):
    from conftest import auth_headers
    owner = admin(client)
    make_local(client, owner)
    page = client.get('/api/v1/nodes', headers=owner).json()
    uid = page['items'][0]['node_uid']
    made = client.post('/api/v1/users', headers=owner, json={
        'username': 'fixture-operator', 'password': 'example-operator-password',
        'display_name': '操作员', 'role': 'operator'})
    assert made.status_code == 201
    login = client.post('/api/v1/auth/login', json={
        'username': 'fixture-operator', 'password': 'example-operator-password'})
    assert login.status_code == 200
    operator = auth_headers(login.json()['csrf_token'])
    edited = client.patch(f'/api/v1/nodes/{uid}/metadata', headers=operator, json={
        'expected_catalog_revision': page['catalog_revision'],
        'meta': {'note': 'operator-reviewed'}})
    assert edited.status_code == 200, edited.text
    changed = client.patch(f'/api/v1/nodes/{uid}/configuration', headers=operator, json={
        'expected_revision': 1, 'server': 'different.example.com',
        'secret_set': {}, 'secret_clear': []})
    assert changed.status_code == 403
    detail = client.get(f'/api/v1/nodes/{uid}', headers=operator).json()
    assert detail['server'] == 'node.example.com'
    assert detail['revision'] == 1


def test_rename_preview_is_read_only_and_expires(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app import db
    from app.services import policy_mutations
    h = admin(client)
    make_local(client, h)
    page = client.get('/api/v1/nodes', headers=h).json()
    uid = page['items'][0]['node_uid']
    clock = {'now': datetime(2027, 1, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr(policy_mutations, '_utcnow', lambda: clock['now'])
    with db.connect() as conn:
        before = tuple(conn.iterdump())
    preview = client.post('/api/v1/nodes/rename-preview', headers=h, json={
        'node_uids': [uid], 'names': {uid: 'TTL-fixture'},
        'expected_catalog_revision': page['catalog_revision']})
    assert preview.status_code == 200, preview.text
    with db.connect() as conn:
        assert tuple(conn.iterdump()) == before
    clock['now'] += timedelta(minutes=31)
    expired = client.post('/api/v1/nodes/rename-apply', headers=h, json={
        'preview_id': preview.json()['preview_id'],
        'expected_catalog_revision': page['catalog_revision']})
    assert expired.status_code == 409
    assert expired.json()['detail']['code'] == 'preview_expired'


def test_rename_apply_rejects_changed_catalog(client):
    h = admin(client)
    make_local(client, h)
    page = client.get('/api/v1/nodes', headers=h).json()
    uid = page['items'][0]['node_uid']
    preview = client.post('/api/v1/nodes/rename-preview', headers=h, json={
        'node_uids': [uid], 'names': {uid: 'Renamed (机房)'},
        'expected_catalog_revision': page['catalog_revision']})
    assert preview.status_code == 200, preview.text
    make_local(client, h, name='US-02')
    result = client.post('/api/v1/nodes/rename-apply', headers=h, json={
        'preview_id': preview.json()['preview_id'],
        'expected_catalog_revision': page['catalog_revision']})
    assert result.status_code == 409
    assert result.json()['detail']['code'] == 'stale_revision'


def test_local_configuration_patch_keeps_secret_and_versions_material(client):
    from app import db
    h = admin(client)
    node = make_local(client, h)
    page = client.get('/api/v1/nodes', headers=h).json()
    uid = page['items'][0]['node_uid']
    changed = client.patch(f'/api/v1/nodes/{uid}/configuration', headers=h, json={
        'expected_revision': 1, 'server': 'different.example.com'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['revision'] == 2
    assert changed.json()['server'] == 'different.example.com'
    assert changed.json()['configured_secret_fields'] == ['password']
    with db.connect() as conn:
        row = conn.execute('SELECT server,current_revision FROM local_nodes JOIN node_catalog '
                           'ON local_nodes.id=node_catalog.local_node_id WHERE node_uid=?',
                           (uid,)).fetchone()
    assert row['server'] == 'different.example.com'
    assert row['current_revision'] == 2


def test_rename_apply_updates_typed_refs_once_and_replay_is_rejected(client):
    from conftest import auth_headers
    from app import db
    h = admin(client)
    node = make_local(client, h)
    page = client.get('/api/v1/nodes', headers=h).json()
    uid = page['items'][0]['node_uid']
    group = client.post('/api/v1/groups', headers=h, json={
        'name': 'fixture-group', 'members_v2': [{'kind': 'node', 'ref': uid}, {'kind': 'builtin', 'ref': 'DIRECT'}],
        'use_sources': []}).json()
    preview = client.post('/api/v1/nodes/rename-preview', headers=h, json={
        'node_uids': [uid], 'names': {uid: 'Renamed Node'},
        'expected_catalog_revision': page['catalog_revision']})
    assert preview.status_code == 200, preview.text
    before_revision = page['items'][0]['revision']
    applied = client.post('/api/v1/nodes/rename-apply', headers=h, json={
        'preview_id': preview.json()['preview_id'],
        'expected_catalog_revision': page['catalog_revision']})
    assert applied.status_code == 200, applied.text
    assert applied.json()['catalog_revision'] > page['catalog_revision']
    current = client.get(f'/api/v1/nodes/{uid}', headers=h).json()
    assert current['emit_name'] == 'Renamed Node'
    assert current['revision'] == before_revision
    assert current['references'][0]['name'] == 'fixture-group'
    group_rows = client.get('/api/v1/groups', headers=h).json()
    target = next(row for row in group_rows if row['id'] == group['id'])
    assert target['members_v2'][0] == {'kind': 'node', 'ref': uid}
    assert target['proxies'][0] == 'Renamed Node'
    replay = client.post('/api/v1/nodes/rename-apply', headers=h, json={
        'preview_id': preview.json()['preview_id'],
        'expected_catalog_revision': page['catalog_revision']})
    assert replay.status_code == 409
    assert replay.json()['detail']['code'] == 'preview_consumed'


def test_signed_preview_survives_app_restart_and_actor_is_bound(client):
    from app.main import create_app
    from fastapi.testclient import TestClient
    h = admin(client)
    make_local(client, h)
    page = client.get('/api/v1/nodes', headers=h).json()
    uid = page['items'][0]['node_uid']
    preview = client.post('/api/v1/nodes/rename-preview', headers=h, json={
        'node_uids': [uid], 'names': {uid: 'Restart Fixture'},
        'expected_catalog_revision': page['catalog_revision']}).json()
    cookie = client.cookies.get('mp_session')
    client.cookies.clear()
    with TestClient(create_app()) as restarted:
        restarted.cookies.set('mp_session', cookie)
        other = restarted.post('/api/v1/users', headers=h, json={
            'username': 'fixture-actor-two', 'password': 'example-actor-password',
            'display_name': '第二人', 'role': 'operator'}).json()
        login = restarted.post('/api/v1/auth/login', json={
            'username': 'fixture-actor-two', 'password': 'example-actor-password'})
        second = auth_headers(login.json()['csrf_token'])
        mismatch = restarted.post('/api/v1/nodes/rename-apply', headers=second, json={
            'preview_id': preview['preview_id'],
            'expected_catalog_revision': page['catalog_revision']})
        assert mismatch.status_code == 403
        assert mismatch.json()['detail']['code'] == 'preview_actor_mismatch'
        admin_login = restarted.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': 'admin-pass-1'})
        admin_after = auth_headers(admin_login.json()['csrf_token'])
        applied = restarted.post('/api/v1/nodes/rename-apply', headers=admin_after, json={
            'preview_id': preview['preview_id'],
            'expected_catalog_revision': page['catalog_revision']})
        assert applied.status_code == 200, applied.text
