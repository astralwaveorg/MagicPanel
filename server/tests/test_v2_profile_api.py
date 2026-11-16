"""运行档案API与版本锁集成。"""

def _target(client, headers):
    response = client.post('/api/v1/targets', headers=headers, json={
        'name': 'fixture-linux', 'engine': 'mihomo', 'platform': 'linux'})
    assert response.status_code == 201
    return response.json()


def test_unknown_profile_is_rejected_by_target_and_device_api(client):
    from v2_helpers import admin
    h = admin(client)
    bad = client.post('/api/v1/targets', headers=h, json={
        'name': 'bad', 'engine': 'mihomo', 'platform': 'linux',
        'default_runtime_profile': 'openclash-v2'})
    assert bad.status_code == 400
    target = _target(client, h)
    bad = client.post('/api/v1/devices', headers=h, json={
        'name': 'bad-device', 'platform': 'linux', 'target_id': target['id'],
        'runtime_profile': 'terminal-v2'})
    assert bad.status_code == 400


def test_target_profile_uses_explicit_revision_and_legacy_put_preserves_it(client):
    from v2_helpers import admin
    h = admin(client)
    target = _target(client, h)
    assert target['default_runtime_profile'] == 'legacy-v1'
    assert target['config_revision'] == 1
    body = {'name': target['name'], 'engine': 'mihomo', 'platform': 'linux',
            'default_runtime_profile': 'legacy-v1'}
    path = f"/api/v1/targets/{target['id']}"
    assert client.put(path, headers=h, json=body).status_code == 409
    body['expected_config_revision'] = 1
    changed = client.put(path, headers=h, json=body)
    assert changed.status_code == 200
    assert changed.json()['config_revision'] == 2
    assert client.put(path, headers=h, json=body).status_code == 409
    body.pop('default_runtime_profile')
    body.pop('expected_config_revision')
    legacy = client.put(path, headers=h, json=body)
    assert legacy.status_code == 200
    assert legacy.json()['default_runtime_profile'] == 'legacy-v1'


def test_device_override_and_inherit_clear_are_revision_guarded(client):
    from v2_helpers import admin
    h = admin(client)
    target = _target(client, h)
    body = {'name': 'fixture-device', 'platform': 'linux', 'target_id': target['id']}
    created = client.post('/api/v1/devices', headers=h, json=body)
    assert created.status_code == 201
    device = created.json()
    assert device['runtime_profile'] is None
    assert device['config_revision'] == 1
    path = f"/api/v1/devices/{device['id']}"
    body.update(runtime_profile='legacy-v1')
    assert client.put(path, headers=h, json=body).status_code == 409
    body['expected_config_revision'] = 1
    applied = client.put(path, headers=h, json=body)
    assert applied.status_code == 200
    assert applied.json()['runtime_profile'] == 'legacy-v1'
    body['runtime_profile'] = None
    assert client.put(path, headers=h, json=body).status_code == 409
    body['expected_config_revision'] = 2
    cleared = client.put(path, headers=h, json=body)
    assert cleared.status_code == 200
    assert cleared.json()['runtime_profile'] is None


def test_scope_api_exposes_the_same_resolver_fingerprint(client):
    from v2_helpers import admin
    from app.services.config_resolution import resolve_layers
    h = admin(client)
    _target(client, h)
    result = client.get('/api/v1/base-config?engine=mihomo&platform=linux', headers=h)
    assert result.status_code == 200
    expected = resolve_layers(engine='mihomo', platform='linux')
    assert result.json()['runtime_profile'] == 'legacy-v1'
    assert result.json()['input_sha256'] == expected['input_sha256']
    assert result.json()['inherited'] == expected['inherited']


def test_preview_rejects_tampered_target_and_device_profile(client):
    from v2_helpers import admin
    from app import db
    h = admin(client)
    target = _target(client, h)
    device = client.post('/api/v1/devices', headers=h, json={
        'name': 'preview-device', 'platform': 'linux',
        'target_id': target['id']}).json()
    with db.tx() as conn:
        conn.execute("UPDATE targets SET default_runtime_profile='unknown' WHERE id=?", (target['id'],))
    assert client.post('/api/v1/base-config/preview', headers=h,
        json={'engine': 'mihomo', 'platform': 'linux'}).status_code == 400
    with db.tx() as conn:
        conn.execute("UPDATE targets SET default_runtime_profile='legacy-v1' WHERE id=?", (target['id'],))
        conn.execute("UPDATE devices SET runtime_profile='unknown' WHERE id=?", (device['id'],))
    assert client.post('/api/v1/base-config/preview', headers=h,
        json={'engine': 'mihomo', 'platform': 'linux',
              'device_id': device['id']}).status_code == 400


def test_snapshot_freezes_profiles_and_same_effective_profile_needs_no_device_artifact(client):
    from conftest import auth_headers, setup_admin
    from test_api import make_policy
    from app import db
    from app.routers.builds import collect_snapshot
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    target = client.get('/api/v1/targets', headers=h).json()[0]
    device = client.post('/api/v1/devices', headers=h, json={
        'name': 'same-profile-device', 'platform': target['platform'],
        'target_id': target['id'], 'runtime_profile': 'legacy-v1'}).json()
    with db.connect() as conn:
        snapshot = collect_snapshot(conn)
    frozen_target = next(item for item in snapshot['targets'] if item['id'] == target['id'])
    frozen_device = next(item for item in snapshot['devices'] if item['id'] == device['id'])
    assert frozen_target['default_runtime_profile'] == 'legacy-v1'
    assert frozen_device['runtime_profile'] == 'legacy-v1'
    built = client.post('/api/v1/builds', headers=h, json={}).json()
    assert built['verify_status'] == 'success'
    assert 'same-profile-device' not in built['results']


def test_batch_metadata_change_invalidates_old_profile_revision(client):
    from v2_helpers import admin
    h = admin(client)
    target = _target(client, h)
    body = {'name': 'revision-device', 'platform': 'linux', 'target_id': target['id']}
    device = client.post('/api/v1/devices', headers=h, json=body).json()
    changed = client.patch('/api/v1/devices/batch', headers=h,
        json={'ids': [device['id']], 'note': 'updated'})
    assert changed.status_code == 200
    body.update(runtime_profile='legacy-v1', expected_config_revision=1)
    assert client.put(f"/api/v1/devices/{device['id']}", headers=h,
                      json=body).status_code == 409


def _movable_device(client, headers):
    target = _target(client, headers)
    destination = client.post('/api/v1/targets', headers=headers, json={
        'name': 'fixture-ios', 'engine': 'stash', 'platform': 'ios'}).json()
    device = client.post('/api/v1/devices', headers=headers, json={
        'name': 'moved-device', 'platform': 'linux', 'target_id': target['id']}).json()
    response = client.put(f"/api/v1/base-config?engine=mihomo&platform=linux&device_id={device['id']}",
        headers=headers, json={'content': 'hosts:\n  move.example.com: 10.0.1.2\n'})
    assert response.status_code == 200, response.text
    return target, destination, device


def test_batch_target_move_rekeys_device_configuration(client):
    from v2_helpers import admin
    h = admin(client)
    target, destination, device = _movable_device(client, h)
    response = client.patch('/api/v1/devices/batch', headers=h,
        json={'ids': [device['id']], 'target_id': destination['id']})
    assert response.status_code == 200
    scope = client.get(f"/api/v1/base-config?engine=stash&platform=ios&device_id={device['id']}", headers=h)
    assert scope.status_code == 200
    assert scope.json()['effective'].get('hosts', {}).get('move.example.com') == '10.0.1.2'


def test_forced_target_move_rekeys_device_configuration(client):
    from v2_helpers import admin
    h = admin(client)
    target, destination, device = _movable_device(client, h)
    response = client.delete(
        f"/api/v1/targets/{target['id']}?force=true&move_to={destination['id']}", headers=h)
    assert response.status_code == 200
    scope = client.get(f"/api/v1/base-config?engine=stash&platform=ios&device_id={device['id']}", headers=h)
    assert scope.status_code == 200
    assert scope.json()['effective'].get('hosts', {}).get('move.example.com') == '10.0.1.2'


def test_feed_distinguishes_frozen_build_and_live_device_envelope(client):
    import yaml
    from conftest import auth_headers, setup_admin
    from test_api import make_policy, publish_to_prod
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    target = client.get('/api/v1/targets', headers=h).json()[0]
    plain = client.post('/api/v1/devices', headers=h, json={
        'name': 'plain-device', 'platform': target['platform'],
        'target_id': target['id']}).json()
    enveloped = client.post('/api/v1/devices', headers=h, json={
        'name': 'enveloped-device', 'platform': target['platform'],
        'target_id': target['id']}).json()
    built = client.post('/api/v1/builds', headers=h, json={}).json()
    publish_to_prod(client, h, built['id'])
    saved = client.put(
        f"/api/v1/base-config?engine={target['engine']}&platform={target['platform']}"
        f"&device_id={enveloped['id']}", headers=h,
        json={'content': 'hosts:\n  feed.example.test: 10.0.1.2\n'})
    assert saved.status_code == 200, saved.text

    frozen = client.get(f"/feed/{plain['token']}/config.yaml")
    assert frozen.status_code == 200
    assert frozen.headers['x-magicpanel-config-source'] == 'frozen-build'
    live = client.get(f"/feed/{enveloped['token']}/config.yaml")
    assert live.status_code == 200
    assert live.headers['x-magicpanel-config-source'] == 'live-envelope'
    assert yaml.safe_load(live.text).get('hosts', {}).get('feed.example.test') == '10.0.1.2'


def test_feed_rejects_tampered_unknown_profile(client):
    from conftest import auth_headers, setup_admin
    from test_api import make_policy, publish_to_prod
    from app import db
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    target = client.get('/api/v1/targets', headers=h).json()[0]
    device = client.post('/api/v1/devices', headers=h, json={
        'name': 'bad-profile-device', 'platform': target['platform'],
        'target_id': target['id']}).json()
    publish_to_prod(client, h, client.post('/api/v1/builds', headers=h, json={}).json()['id'])
    with db.tx() as conn:
        conn.execute("UPDATE devices SET runtime_profile='unknown' WHERE id=?", (device['id'],))
    response = client.get(f"/feed/{device['token']}/config.yaml")
    assert response.status_code == 500
    assert response.text == 'runtime_profile_invalid'


def test_profile_changes_require_edit_capability(client):
    from conftest import auth_headers
    from v2_helpers import admin
    h = admin(client)
    target = _target(client, h)
    device = client.post('/api/v1/devices', headers=h, json={
        'name': 'viewer-device', 'platform': 'linux',
        'target_id': target['id']}).json()
    created = client.post('/api/v1/users', headers=h, json={
        'username': 'fixture-viewer', 'password': 'example-viewer-password',
        'display_name': '只读', 'role': 'viewer'})
    assert created.status_code == 201
    login = client.post('/api/v1/auth/login', json={
        'username': 'fixture-viewer', 'password': 'example-viewer-password'})
    assert login.status_code == 200
    viewer = auth_headers(login.json()['csrf_token'])
    target_body = {'name': target['name'], 'engine': 'mihomo', 'platform': 'linux',
                   'default_runtime_profile': 'legacy-v1',
                   'expected_config_revision': target['config_revision']}
    assert client.put(f"/api/v1/targets/{target['id']}", headers=viewer,
                      json=target_body).status_code == 403
    device_body = {'name': device['name'], 'platform': 'linux',
                   'target_id': target['id'], 'runtime_profile': 'legacy-v1',
                   'expected_config_revision': device['config_revision']}
    assert client.put(f"/api/v1/devices/{device['id']}", headers=viewer,
                      json=device_body).status_code == 403
