"""可重放能力评估与语义指纹。"""
import pytest


def test_noise_does_not_change_eligibility_but_revision_does():
    from app.services.capability_evaluation import evaluate
    from app.services.fingerprints import digest
    from v2_helpers import at, node
    n = node('n')
    a = {'node_uid': 'n', 'revision': 1, 'scope': 'web-entry', 'observer_id': 'vps',
         'path_qualified': True, 'result_state': 'observed-ok',
         'measured_at': at().isoformat(), 'valid_until': at(22).isoformat(), 'delay_ms': 80}
    x = evaluate([n], [a], evaluation_at=at(16), previous=None)
    y = evaluate([n], [dict(a, delay_ms=82)], evaluation_at=at(16), previous=None)
    assert x['eligibility_sha'] == y['eligibility_sha']
    z = evaluate([dict(n, revision=2)], [a], evaluation_at=at(16), previous=None)
    assert z['eligibility_sha'] != x['eligibility_sha']
    assert digest({'b': 1, 'a': 2}) == digest({'a': 2, 'b': 1})


def test_expired_or_unqualified_observation_is_not_eligible():
    from app.services.capability_evaluation import evaluate
    from v2_helpers import at, node
    n = node('n')
    base = {'node_uid': 'n', 'revision': 1, 'scope': 'web-entry', 'observer_id': 'vps',
            'path_qualified': True, 'result_state': 'observed-ok',
            'measured_at': at().isoformat(), 'valid_until': at(22).isoformat()}
    x = evaluate([n], [base], evaluation_at=at(16), previous=None)
    assert x['eligible'][0]['fresh'] is True
    stale = evaluate([n], [dict(base, valid_until=at(14*24*60).isoformat())], evaluation_at=at(8*24*60 + 1), previous=None)
    assert stale['eligible'][0]['fresh'] is False
    expired = evaluate([n], [dict(base, valid_until=at(15).isoformat())],
                       evaluation_at=at(16), previous=None)
    assert expired['eligible'] == []
    bad_path = evaluate([n], [dict(base, path_qualified=False)],
                        evaluation_at=at(16), previous=None)
    assert bad_path['eligible'] == []
