"""旧 feed 冻结层离线合同。"""


def test_freeze_keeps_config_overlay_and_global_legacy_bytes(tmp_path, client):
    from app.services.feed_freeze import arm_freeze, lookup_frozen, prepare_freeze
    config_path = '/feed/' + ('f' * 24) + '/config.yaml'
    data = {'routes': [
        {'path': config_path, 'query': '', 'body': b'final-overlay-v1',
         'content_type': 'application/yaml', 'references': ['/res/rule/shared']},
        {'path': '/res/rule/shared', 'query': '', 'body': b'old-rule',
         'content_type': 'application/yaml', 'references': []},
    ]}
    manifest = prepare_freeze(data, destination=tmp_path)
    arm_freeze(tmp_path, expected_sha=manifest['contract_sha'])
    found = lookup_frozen(tmp_path, path=config_path, query='', method='GET')
    assert found['body'] == b'final-overlay-v1'
    assert lookup_frozen(tmp_path, path='/res/rule/shared', query='', method='HEAD')['body'] == b'old-rule'
    assert found['etag']


def test_frozen_exact_query_and_identity_are_required(tmp_path, client):
    from app.services.feed_freeze import arm_freeze, lookup_frozen, prepare_freeze
    route = {'path': '/feed/token/config.yaml', 'query': 'preview=1',
             'body': b'preview', 'content_type': 'text/yaml', 'references': []}
    manifest = prepare_freeze({'routes': [route]}, destination=tmp_path)
    arm_freeze(tmp_path, expected_sha=manifest['contract_sha'])
    assert lookup_frozen(tmp_path, path=route['path'], query='', method='GET') is None
    assert lookup_frozen(tmp_path, path=route['path'], query='preview=1',
                         method='GET', identity_ok=False) is None
    assert lookup_frozen(tmp_path, path=route['path'], query='preview=1',
                         method='POST') is None


def test_release_requires_receipt_and_stops_armed_serving(tmp_path, client):
    from app.services.feed_freeze import arm_freeze, lookup_frozen, prepare_freeze, release_freeze
    import pytest
    route = {'path': '/res/rule/shared', 'query': '', 'body': b'old-rule',
             'content_type': 'application/yaml', 'references': []}
    manifest = prepare_freeze({'routes': [route]}, destination=tmp_path)
    arm_freeze(tmp_path, expected_sha=manifest['contract_sha'])
    with pytest.raises(ValueError):
        release_freeze(tmp_path, expected_sha=manifest['contract_sha'], receipt={})
    released = release_freeze(tmp_path, expected_sha=manifest['contract_sha'], receipt={
        'contract_sha': manifest['contract_sha'],
        'owner_load_receipts': [{'owner': 'r6s', 'loaded': True}]})
    assert released['state'] == 'released'
    assert lookup_frozen(tmp_path, path=route['path'], query='', method='GET') is None
