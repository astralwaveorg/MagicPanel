"""预算预演零写与创建重核合同。"""


def test_preview_is_pure_and_create_rechecks_digest(client):
    from app import db
    from conftest import auth_headers, setup_admin
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    body = {'variant_id': 0, 'node_keys': [], 'service_ids': ['basic'],
            'observer_id': 'unqualified', 'trigger': 'manual'}
    response = client.post('/api/v1/probe-jobs/preview', headers=h, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['blockers']
    stale = client.post('/api/v1/probe-jobs', headers=h, json=dict(
        body, preview_token=response.json()['preview_token'],
        expected_preview_digest='stale', idempotency_key='fixture-once'))
    assert stale.status_code == 409
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM probe_jobs').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM probe_reservations').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM routing_plans').fetchone()[0] == 0


def test_probe_consumes_real_01_catalog_dto_without_per_node_catalog_revision(client):
    from conftest import auth_headers, setup_admin
    from v2_helpers import make_local
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_local(client, h)
    response = client.get('/api/v1/nodes?limit=50&offset=0', headers=h)
    assert response.status_code == 200, response.text
    page = response.json()
    entry = page['items'][0]
    assert 'catalog_revision' not in entry
    body = {'variant_id': 0,
            'node_keys': [{'node_uid': entry['node_uid'], 'revision': entry['revision']}],
            'service_ids': ['basic'], 'observer_id': 'unqualified', 'trigger': 'manual'}
    preview = client.post('/api/v1/probe-jobs/preview', headers=h, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['expected_revisions']['catalog_revision'] == page['catalog_revision']
