"""滚动预算与公平轮转纯逻辑。"""
import pytest

from app.services.probe_budget import round_robin, shared_remaining
from app.services.recovery_policy import defaults


def test_child_budget_cannot_bypass_shared_parent():
    policy = defaults()['budgets']
    usage = {'deep': {'requests': 22000, 'bytes': 2_000_000_000},
             'sentinel': {'requests': 2000, 'bytes': 90_000_000}}
    result = shared_remaining(policy, usage, reserved={})
    assert result['deep']['requests'] == 0
    assert result['deep']['bytes'] == 0
    assert result['sentinel']['requests'] == 6000
    assert result['sentinel']['bytes'] == 10_663_296


def test_reserved_capacity_is_not_double_booked():
    policy = defaults()['budgets']
    result = shared_remaining(policy, {'deep': {'requests': 1000, 'bytes': 0}},
                              reserved={'event': {'requests': 900, 'bytes': 0}})
    assert result['deep']['requests'] == 7000
    assert result['event']['requests'] == 0


def test_negative_usage_is_rejected():
    with pytest.raises(ValueError):
        shared_remaining(defaults()['budgets'],
                         {'deep': {'requests': -1, 'bytes': 0}}, reserved={})


def test_round_robin_fairly_interleaves_buckets():
    assert round_robin({'source': ['s1', 's2'], 'local': ['l1']}) == \
        ['local:l1', 'source:s1', 'source:s2']
