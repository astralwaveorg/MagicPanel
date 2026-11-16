"""独立 observer、路径资格与基础探针离线合同。"""
import pytest


def test_unknown_nas_path_is_not_vps_and_basic_probe_is_separate(client):
    from app import db
    from app.services import probe_observers as o
    from v2_helpers import at
    with db.tx() as conn:
        o.register(conn, {'id': 'nas', 'kind': 'nas', 'config_revision': 1, 'enabled': True})
        with pytest.raises(o.PathNotQualified):
            o.require_path(conn, 'nas', 1, 'ranking', at(1))
        assert o.admit_target('https://health.example.test/204', google=False,
                              country=None, egress_scope='unknown') is True
        assert o.admit_target('https://www.google.com/', google=True,
                              country='SG', egress_scope='google') is True
        assert o.admit_target('https://evil.example/', google=True,
                              country='SG', egress_scope='google') is False


def test_qualify_requires_signed_path_and_scope(client):
    import hashlib
    import hmac
    import json
    from app import db
    from app.services import probe_observers as o
    from v2_helpers import at
    contract = {'scopes': ['ranking'], 'network': 'test', 'config_revision': 1}
    body = json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()
    signature = hmac.new(b'fixture-key', body, hashlib.sha256).hexdigest()
    with db.tx() as conn:
        o.register(conn, {'id': 'nas', 'kind': 'nas', 'config_revision': 1,
                          'enabled': True, 'public_key': 'fixture-key'})
        path = o.qualify(conn, observer_id='nas', contract=contract,
                         proof={'signed_at': at(0).isoformat(), 'nonce': 'nonce-1',
                                'signature': signature, 'observation_sha': 'a' * 64},
                         now=at(1))
        assert path['state'] == 'verified'
        assert o.require_path(conn, 'nas', path['epoch'], 'ranking', at(2))
        with pytest.raises(o.PathNotQualified):
            o.require_path(conn, 'nas', path['epoch'], 'media', at(2))


def test_runner_records_small_result_without_material(client):
    from app.services import probe_observers as o
    from app.services import probe_runner
    from v2_helpers import at
    calls = []

    def transport(request, url, *, headers, body, max_read, deadline):
        calls.append({'url': url, 'max_read': max_read, 'deadline': deadline})
        return {'status': 204, 'body': b'', 'bytes_read': 0, 'bytes_written': 0}

    item = {'node_uid': 'node-a', 'node_revision': 1, 'service_key': 'basic',
            'observer_id': 'nas', 'path_epoch': 1, 'url': 'https://health.example.test/204',
            'google': False, 'country': None, 'egress_scope': 'unknown',
            'secret': 'never-leak'}
    result = probe_runner.run_item(item, transport, now=at(0))
    assert result['result_state'] == 'observed-ok'
    assert calls[0]['max_read'] == 8192
    assert calls[0]['deadline'] <= 6
    assert 'secret' not in str(result)
    assert result['request_count'] == 1
