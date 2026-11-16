"""纯路由 planner：AI 无成本排序与 Google 严格档位。"""
import copy


def test_healthy_current_is_not_replaced_by_weekly_better_rank():
    from app.services.recovery_policy import defaults
    from app.services.routing_planner import recovery_plan
    from v2_helpers import at
    snapshot = {'policy': defaults(), 'current': {'selection_revision': 1,
                'selected_ref': {'kind': 'node', 'ref': 'a'}},
                'health': {'confirmed_failure': False},
                'ordered_candidates': [{'kind': 'node', 'ref': 'b'}, {'kind': 'node', 'ref': 'a'}],
                'manual_locks': [], 'scope_sha': 'fixture-scope'}
    before = copy.deepcopy(snapshot)
    result = recovery_plan(snapshot, evaluation_at=at())
    assert result['action'] == 'keep'
    assert snapshot == before


def test_all_nodes_failed_does_not_change_direct_or_dns():
    from app.services.recovery_policy import defaults
    from app.services.routing_planner import recovery_plan
    from v2_helpers import at
    snapshot = {'policy': defaults(), 'current': {'selection_revision': 1,
                'selected_ref': {'kind': 'node', 'ref': 'a'}},
                'health': {'confirmed_failure': True}, 'ordered_candidates': [],
                'all_applicable_failed': True, 'manual_locks': [],
                'scope_sha': 'fixture-scope', 'core_health': 'healthy'}
    result = recovery_plan(snapshot, evaluation_at=at())
    assert result['action'] == 'wait' and result['proposed_ref'] is None
    assert not ({'dns', 'routes', 'gateway_mode', 'direct_policy'} & set(result))


def test_airport_wins_cost_is_ignored_and_google_does_not_skip_unknown():
    from app.services.routing_planner import rank_ai, select_google_tier
    from v2_helpers import at
    a = {'node_uid': 'airport', 'coverage': 4, 'reputation': 2, 'stability': 99,
         'latency_ms': 80, 'cost': 999, 'origin_kind': 'source', 'eligible': True}
    b = dict(a, node_uid='self', coverage=3, cost=0, origin_kind='local')
    assert rank_ai([b, a]) == ['airport', 'self']
    assert rank_ai([dict(a, cost=0), dict(b, cost=9999)]) == ['airport', 'self']
    us = dict(a, node_uid='us', country='US', google_state='unknown')
    sg = dict(a, node_uid='sg', country='SG', google_state='observed-ok')
    held = select_google_tier([us, sg], [], evaluation_at=at())
    assert held['state'] == 'needs_review' and held['tier'] is None
    us_ok = dict(us, google_state='observed-ok', latency_ms=900)
    assert select_google_tier([us_ok, sg], [], evaluation_at=at())['tier'] == 'US'


def test_google_requires_complete_fresh_higher_tier_exhaustion():
    from app.services.routing_planner import select_google_tier
    from v2_helpers import at
    us = {'node_uid': 'us', 'country': 'US', 'google_state': 'unknown', 'scope_sha': 'scope'}
    sg = {'node_uid': 'sg', 'country': 'SG', 'google_state': 'observed-ok', 'scope_sha': 'scope'}
    old = [{'country': 'US', 'scope_sha': 'scope', 'complete': True,
            'state': 'all_failed', 'valid_until': '2026-11-15T03:00:00+00:00'}]
    assert select_google_tier([us, sg], old, evaluation_at=at())['tier'] is None
    fresh = [dict(old[0], valid_until='2027-01-05T04:00:00+00:00')]
    assert select_google_tier([us, sg], fresh, evaluation_at=at())['tier'] == 'SG'
