from v2_helpers import admin, make_local, assert_no_secrets


def test_local_list_is_safe_even_for_admin(client):
    h = admin(client)
    node = make_local(client, h)
    assert_no_secrets(node)
    rows = client.get('/api/v1/local-nodes', headers=h).json()
    assert_no_secrets(rows)
    assert 'params' not in rows[0] and 'extra_yaml' not in rows[0]
    assert rows[0]['has_credentials'] is True
    assert 'password' in rows[0]['configured_secret_fields']


def test_patch_never_clears_omitted_secret(client):
    from app.services.node_dto import merge_configuration
    current = {'public_params': {'udp': True}, 'secrets': {'password': 'example-test-password'}, 'extra_yaml': 'udp: true\n'}
    changed = merge_configuration(current, {'public_params': {'udp': False}})
    assert changed['secrets'] == current['secrets']
    assert changed['extra_yaml'] == current['extra_yaml']
    assert merge_configuration(current, {'secret_clear': ['password']})['secrets'] == {}


def test_legacy_put_preserves_omitted_credentials(client):
    h = admin(client)
    node = make_local(client, h)
    body = {'name': node['name'], 'protocol': 'ss', 'server': node['server'], 'port': node['port'], 'params': {'udp': False}}
    r = client.put(f"/api/v1/local-nodes/{node['id']}", headers=h, json=body)
    assert r.status_code == 200, r.text
    revealed = client.post(f"/api/v1/local-nodes/{node['id']}/reveal", headers=h)
    assert revealed.json()['params']['password'] == 'example-test-password'
    assert revealed.headers['cache-control'] == 'no-store'


def test_secret_clear_required_rejected(client):
    h = admin(client)
    node = make_local(client, h)
    body = {'name': node['name'], 'protocol': 'ss', 'server': node['server'], 'port': node['port'], 'secret_clear': ['password']}
    r = client.put(f"/api/v1/local-nodes/{node['id']}", headers=h, json=body)
    assert r.status_code == 400
    assert_no_secrets(r.json())


def test_schema_nested_and_custom(client):
    from app.schemas.nodes import split_parameters
    public, secrets = split_parameters('http', {'tls': True, 'username': 'test-user', 'auth': {'password': 'example-test-password'}})
    assert public == {'tls': True}
    assert secrets['auth']['password'] == 'example-test-password'
    assert secrets['username'] == 'test-user'
    assert split_parameters('custom', {'anything': 'private'}) == ({}, {'anything': 'private'})


def test_build_public_never_returns_snapshot(client):
    from app.services.releases import build_public
    from app import db, security
    row = dict(id=1, created_at=db.now(), created_by='admin', status='BUILT', verify_status='success', policy_sha='hash', note='', published_at='', published_by='', publish_reason='', status_updated_at='', results='{}', snapshot=security.encrypt_payload('{"password":"example-test-password"}'))
    result = build_public(row, with_results=True)
    assert 'snapshot' not in result
    assert_no_secrets(result)

def test_patch_rejects_conflicts_and_unknown(client):
    import pytest
    from app.services.node_dto import merge_configuration
    for patch in ({'unknown': 'example-test-password'}, {'secret_set': {'password': 'p'}, 'secret_clear': ['password']}, {'extra_yaml': 'x', 'clear_extra_yaml': True}):
        with pytest.raises(ValueError):
            merge_configuration({}, patch)


def test_ordinary_diff_returns_metadata_only(client):
    from app import db, security, config
    h = admin(client)
    with db.tx() as conn:
        for bid in (1, 2):
            conn.execute("INSERT INTO builds(id,created_at,created_by,status,verify_status,policy_sha,snapshot,results,note,status_updated_at) VALUES(?,?,?,'BUILT','success','hash',?,'{}','',?)", (bid, db.now(), 'admin', security.encrypt_payload('{}'), db.now()))
            folder = config.BUILDS_DIR / str(bid)
            folder.mkdir(parents=True)
            (folder / 'fixture.yaml').write_text(f'password: example-test-password-{bid}', encoding='utf-8')
    result = client.get('/api/v1/builds/2/diff/1', headers=h)
    assert result.status_code == 200
    assert_no_secrets(result.json())
    assert result.json()['targets']['fixture']['changed'] is True


def test_operator_reveal_denied(client):
    from app import db
    h = admin(client)
    node = make_local(client, h)
    with db.tx() as conn:
        conn.execute("UPDATE users SET role='operator' WHERE username='admin'")
    assert client.post(f"/api/v1/local-nodes/{node['id']}/reveal", headers=h).status_code == 403

def test_nested_secret_patch_preserves_omitted_fields(client):
    from app.services.node_dto import merge_configuration
    result = merge_configuration({'secrets': {'auth': {'username': 'user', 'password': 'example-test-password'}}}, {'secret_set': {'auth': {'username': 'next'}}})
    assert result['secrets']['auth'] == {'username': 'next', 'password': 'example-test-password'}


def test_extra_yaml_clear_is_explicit(client):
    h = admin(client)
    node = make_local(client, h)
    path = f"/api/v1/local-nodes/{node['id']}"
    body = {'name': node['name'], 'protocol': 'ss', 'server': node['server'], 'port': node['port'], 'extra_yaml': 'password: example-test-password\n'}
    assert client.put(path, headers=h, json=body).status_code == 200
    body['extra_yaml'] = ''
    assert client.put(path, headers=h, json=body).status_code == 200
    assert client.post(path + '/reveal', headers=h).json()['extra_yaml']
    body['clear_extra_yaml'] = True
    assert client.put(path, headers=h, json=body).status_code == 200
    assert client.post(path + '/reveal', headers=h).json()['extra_yaml'] == ''

def test_reveal_audit_contains_field_names_only(client):
    import json
    from app import db
    h = admin(client)
    node = make_local(client, h)
    response = client.post(f"/api/v1/local-nodes/{node['id']}/reveal", headers=h)
    assert response.status_code == 200
    with db.connect() as conn:
        rows = [dict(r) for r in db.all_(conn, 'SELECT * FROM audit')]
    assert_no_secrets(rows)
    assert 'extra_yaml' in json.dumps(rows)


def test_unknown_parameter_and_protocol_change_rejected(client):
    h = admin(client)
    node = make_local(client, h)
    path = f"/api/v1/local-nodes/{node['id']}"
    body = {'name': node['name'], 'protocol': 'ss', 'server': node['server'], 'port': node['port'], 'params': {'unknown': 'example-test-password'}}
    result = client.put(path, headers=h, json=body)
    assert result.status_code == 400
    assert_no_secrets(result.json())
    body.update(protocol='trojan', params={})
    assert client.put(path, headers=h, json=body).status_code == 400


def test_validation_error_never_echoes_secret_payload(client):
    h = admin(client)
    node = make_local(client, h)
    response = client.put(f"/api/v1/local-nodes/{node['id']}", headers=h, json={'name': node['name'], 'protocol': 'ss', 'server': node['server'], 'port': node['port'], 'secret_set': ['example-test-password']})
    assert response.status_code == 422
    assert_no_secrets(response.json())


def test_validation_error_nested_body_does_not_echo_input(client):
    h = admin(client)
    response = client.post('/api/v1/local-nodes', headers=h, json={'name': {'password': 'example-test-password'}, 'protocol': 'ss', 'server': 'node.example.com', 'port': 0, 'extra_yaml': {'password': 'example-test-password'}})
    assert response.status_code == 422
    assert_no_secrets(response.json())
    assert isinstance(response.json()['detail'], list)
    for error in response.json()['detail']:
        assert set(error) == {'loc', 'type', 'msg'}
        assert error['msg']
