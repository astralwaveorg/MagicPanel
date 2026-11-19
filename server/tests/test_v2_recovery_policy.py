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
    """staged（默认）不入队；active 后 weekly tick 入队且重启不重复。

    2026-11-18 改语义：影子任务没有执行者与清理，staged 下照常入队只会
    让 probe 三张表单调膨胀——weekly 入队从此尊重 v2_runtime_activation。
    """
    from app import db
    from app.services import probe_schedule, probe_store
    from v2_helpers import at
    with db.tx() as conn:
        probe_schedule.configure(conn, enabled=True, timezone='Asia/Shanghai',
            weekday=0, hour=4, minute=0, observer_id='fixture', now=at(15))
        # staged：不入队
        staged = probe_schedule.tick(conn, at(16))
        assert staged == []
        assert probe_store.list_jobs(conn, limit=10, offset=0)['total'] == 0
        assert probe_schedule.on_revision_changed(conn, 'n', 2, at(16)) == []
        # active：到下一次到期时间才入队（weekday 修复后 next_due 是
        # 下一个配置星期几 = 周一 04:00 = at(10080)），重复 tick 不重复
        db.set_setting(conn, 'v2_runtime_activation', 'active')
        first = probe_schedule.tick(conn, at(10085))
    with db.tx() as conn:
        second = probe_schedule.tick(conn, at(16))
        assert len(first) == 1 and second == []
        assert probe_store.list_jobs(conn, limit=10, offset=0)['total'] == 1


def test_probe_store_claim_finish_and_cancel(client):
    from app import db
    from app.services import probe_store
    from app.services.probe_models import NodeKey
    from v2_helpers import at
    with db.tx() as conn:
        job = probe_store.enqueue(conn, trigger='event', observer_id='fixture',
            nodes=[NodeKey('node-a', 1)], services=('basic',), schedule_key=None,
            now=at(10), deadline=at(240))
        first = probe_store.claim(conn, worker_id='one', now=at(11), lease_seconds=120)
        second = probe_store.claim(conn, worker_id='two', now=at(11))
        assert first and not second
        probe_store.finish(conn, first['id'], worker_id='one',
            result={'result_state': 'observed-ok'}, now=at(12))
        with pytest.raises(ValueError):
            probe_store.cancel(conn, job['id'], expected_revision=job['revision'] - 1,
                               now=at(13))


def test_multi_item_probe_queue_continues_after_expired_lease_without_resending(client):
    from app import db
    from app.services import probe_store
    from v2_helpers import at

    with db.tx(immediate=True) as conn:
        job = probe_store.enqueue(conn, trigger='manual', observer_id='nas',
            nodes=[('A', 1), ('B', 1), ('C', 1)], services=('google:critical',),
            schedule_key=None, now=at(0), deadline=at(30))
        assert probe_store.claim(conn, worker_id='test', observer_id='other', now=at(1)) is None
        first = probe_store.claim(conn, worker_id='test', observer_id='nas', now=at(1))
        assert first['observer_id'] == 'nas'
        assert probe_store.claim(conn, worker_id='parallel', now=at(1)) is None
        assert probe_store.claim(conn, worker_id='test', now=at(2))['id'] != first['id']
        with pytest.raises(ValueError, match='probe_lease_invalid'):
            probe_store.finish(conn, first['id'], worker_id='test', now=at(2),
                               result={'result_state': 'observed-ok'})
        running = conn.execute("SELECT id FROM probe_items WHERE state='running'").fetchone()[0]
        probe_store.finish(conn, running, worker_id='test', now=at(2),
                           result={'result_state': 'challenge'})
        last = probe_store.claim(conn, worker_id='test', now=at(3))
        assert last['id'] not in {first['id'], running}
        probe_store.finish(conn, last['id'], worker_id='test', now=at(3),
                           result={'result_state': 'observed-ok'})
        assert probe_store.claim(conn, worker_id='test', now=at(4)) is None
        assert conn.execute("SELECT state FROM probe_jobs WHERE id=?", (job['id'],)).fetchone()[0] == 'incomplete'
        assert conn.execute("SELECT attempts FROM probe_items WHERE id=?", (first['id'],)).fetchone()[0] == 1
