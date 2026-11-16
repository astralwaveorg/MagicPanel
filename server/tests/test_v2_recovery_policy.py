"""auto_stable_v1 策略与调度离线合同。"""
import pytest
import subprocess
import sys


def test_region_sampling_never_treats_unknown_as_failed_vote():
    from app.services.recovery_policy import defaults, region_action
    policy = defaults()

    def rows(states):
        return [{'state': state, 'fault_domain': str(i)}
                for i, state in enumerate(states)]

    assert policy['mode'] == 'auto_stable_v1'
    assert region_action(rows(['observed-ok', 'observed-ok', 'blocked']),
                         control_ok=True, policy=policy) == 'keep'
    assert region_action(rows(['observed-ok', 'blocked', 'blocked']),
                         control_ok=True, policy=policy) == 'confirm_region'
    assert region_action(rows(['unknown', 'unknown', 'blocked']),
                         control_ok=True, policy=policy) == 'measurement_degraded'
    assert region_action(rows(['blocked'] * 3), control_ok=False,
                         policy=policy) == 'measurement_degraded'


def test_defaults_match_auto_stable_contract():
    from app.services.recovery_policy import defaults
    policy = defaults()
    assert policy['schedule'] == {
        'weekly': {'weekday': 0, 'hour': 4, 'minute': 0},
        'daily_region': {'hour': 8, 'minute': 0},
        'sentinel_seconds': 300,
    }
    assert policy['google']['order'] == ['US', 'SG', 'JP']
    assert policy['budgets']['shared'] == {'requests': 30000, 'bytes': 2_500_000_000}


def test_schedule_timezone_available_without_system_iana(tmp_path):
    import os
    result = subprocess.run(
        [sys.executable, '-c',
         "from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Shanghai').key)"],
        cwd=tmp_path, env={**os.environ, 'PYTHONTZPATH': ''},
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'Asia/Shanghai'


def test_weekly_tick_and_restart_do_not_duplicate(client):
    from app import db
    from app.services import probe_schedule, probe_store
    from v2_helpers import at
    with db.tx() as conn:
        probe_schedule.configure(conn, enabled=True, timezone='Asia/Shanghai',
            weekday=0, hour=4, minute=0, observer_id='fixture', now=at(15))
        first = probe_schedule.tick(conn, at(16))
    with db.tx() as conn:
        second = probe_schedule.tick(conn, at(16))
        assert len(first) == 1 and second == []
        assert probe_store.list_jobs(conn, limit=10, offset=0)['total'] == 1
        assert probe_schedule.on_revision_changed(conn, 'n', 2, at(16)) == []


def test_probe_store_claim_finish_and_cancel(client):
    from app import db
    from app.services import probe_store
    from app.services.probe_models import NodeKey
    from v2_helpers import at
    with db.tx() as conn:
        job = probe_store.enqueue(conn, trigger='event', observer_id='fixture',
            nodes=[NodeKey('node-a', 1)], services=('basic',), schedule_key=None,
            now=at(10), deadline=at(240))
        first = probe_store.claim(conn, worker_id='one', now=at(11))
        second = probe_store.claim(conn, worker_id='two', now=at(11))
        assert first and not second
        probe_store.finish(conn, first['id'], worker_id='one',
            result={'result_state': 'observed-ok'}, now=at(12))
        with pytest.raises(ValueError):
            probe_store.cancel(conn, job['id'], expected_revision=job['revision'] - 1,
                               now=at(13))
