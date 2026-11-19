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


def test_google_prefers_usable_self_hosted_us_over_faster_airport():
    from app.services.routing_planner import select_google_tier
    from v2_helpers import at

    base = {"country": "US", "google_state": "observed-ok"}
    selfhosted = dict(base, origin_kind="local", node_uid="self", latency_ms=400)
    provider = dict(base, origin_kind="source", node_uid="provider", latency_ms=100)
    assert select_google_tier([provider, selfhosted], [], evaluation_at=at())["candidate_uids"] == ["self", "provider"]
    assert select_google_tier(
        [provider, {**selfhosted, "google_state": "unknown"}], [], evaluation_at=at()
    )["candidate_uids"] == ["provider"]


def test_service_candidates_do_not_confuse_reachability_or_region_with_unlock():
    from app.services.routing_planner import service_candidates

    netflix = {"state": "unlocked", "status": 200, "region": "JP",
               "extra": {"catalog": "licensed_sample"}}
    ai = {"state": "unlocked", "status": 200}
    base = {"checked_at": 100, "qualified": True, "delay_ms": 100,
            "country": "JP", "origin_kind": "local", "probes": {"netflix": netflix, "claude": ai}}
    rows = [
        dict(base, name="日本自建"),
        dict(base, name="美国自建", country="US", delay_ms=80,
             probes={"netflix": dict(netflix, region="US"), "claude": ai}),
        dict(base, name="日本订阅", origin_kind="source", delay_ms=20,
             probes={"netflix": dict(netflix, extra={"catalog": "originals_sample"}), "claude": ai}),
        dict(base, name="旧记录", checked_at=9),
        dict(base, name="校验页", probes={
            "netflix": dict(netflix, status=403),
            "claude": dict(ai, status=403, extra={"reason": "challenge"})}),
        dict(base, name="网页有响应", probes={"claude": dict(ai, state="reachable")}),
    ]
    assert [n["name"] for n in service_candidates(rows, "netflix", earliest=10)] == ["日本自建"]
    assert [n["name"] for n in service_candidates(rows, "claude", earliest=10)] == ["美国自建", "日本自建", "日本订阅"]
    assert service_candidates(rows, "perplexity", earliest=10) == []
