"""发布指针 CAS、幂等与双指针保护。"""


def test_bundle_rejection_preserves_both_release_pointers(client, monkeypatch):
    from app import db
    from app.services import releases, publish_gate
    from conftest import auth_headers, setup_admin
    from test_api import make_policy
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    bid = client.post('/api/v1/builds', headers=h, json={}).json()['id']

    def reject(*args, **kwargs):
        raise releases.ReleaseError('bundle_not_ready')

    monkeypatch.setattr(publish_gate, 'prepare_ticket', reject)
    response = client.post(f'/api/v1/builds/{bid}/publish-to-test', headers=h, json={})
    assert response.status_code in (400, 409)
    with db.connect() as conn:
        assert releases.current(conn, 'testing') is None
        assert releases.current(conn, 'production') is None


def test_same_release_revision_only_one_concurrent_publish_wins(client):
    from concurrent.futures import ThreadPoolExecutor
    from conftest import auth_headers, setup_admin
    from test_api import make_policy
    from app import db
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    ids = [client.post('/api/v1/builds', headers=h, json={}).json()['id'] for _ in range(2)]

    def publish(bid):
        body = {'reason': 'fixture', 'expected_release_revision': 0,
                'idempotency_key': f'publish-{bid}'}
        return bid, client.post(f'/api/v1/builds/{bid}/publish-to-test', headers=h, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ids))
    assert sorted(response.status_code for _, response in results) == [200, 409]
    winner = next(bid for bid, response in results if response.status_code == 200)
    retry = client.post(f'/api/v1/builds/{winner}/publish-to-test', headers=h, json={
        'reason': 'fixture', 'expected_release_revision': 0,
        'idempotency_key': f'publish-{winner}'})
    assert retry.status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT revision FROM release_state WHERE env='testing'").fetchone()[0] == 1
