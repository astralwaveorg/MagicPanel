"""DNS 意图、共享 scope 与离线 owner bundle。"""
import pytest

from app.compiler.dns_intent import IntentError, compile_agh, normalize_intent
from app.services.dns_bundles import ScopeConflict, combine_scopes, prepare_bundle


def test_shared_scope_conflict_and_exact_not_widened():
    a = {'owner_target': 'agh-home', 'dns_scope': 'shared', 'variant_id': 0,
         'entries': [{'kind': 'suffix', 'domain': 'example.test', 'resolver': 'domestic',
                      'priority': 1}]}
    b = dict(a, variant_id=1, entries=[dict(a['entries'][0], resolver='overseas')])
    with pytest.raises(ScopeConflict):
        combine_scopes([a, b])
    intent = normalize_intent([{'kind': 'exact', 'domain': 'a.example.test',
                                'resolver': 'overseas', 'priority': 1}], version='1')
    with pytest.raises(IntentError, match='exact_not_supported'):
        compile_agh(intent, capabilities={'suffix': True, 'exact': False})


def test_normalize_idna_and_reject_wildcards():
    from app.compiler.dns_intent import normalize_domain
    assert normalize_domain('中文.Example.Test.') == 'xn--fiq228c.example.test'
    for value in ('*.example.test', '', 'a/b', 'tld'):
        try:
            normalize_domain(value)
        except ValueError as exc:
            assert str(exc) == 'invalid_dns_domain'
        else:
            raise AssertionError(value)


def test_bundle_is_stable_and_records_predecessor():
    artifact = {'kind': 'config', 'path': '/feed/token/config.yaml', 'body': b'config'}
    owner = {'owner_target': 'agh-home', 'output': b'dns-rules'}
    first = prepare_bundle([artifact], [owner], predecessor_sha=None)
    second = prepare_bundle([artifact], [owner], predecessor_sha=first['bundle_sha'])
    assert second['predecessor_sha'] == first['bundle_sha']
    assert prepare_bundle([artifact], [owner], predecessor_sha=None) == first
    assert 'token' not in str(first['safe_manifest'])
