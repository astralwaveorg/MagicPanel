"""auto_stable_v1 调度状态；staged 模式只建影子任务，不发真实请求。"""
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from .. import db
from . import probe_store


def _iso(value) -> str:
    return value.isoformat()


def configure(conn, *, enabled: bool, timezone: str, weekday: int, hour: int,
              minute: int, observer_id: str, now) -> None:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    zone = ZoneInfo(timezone)
    if not (0 <= weekday <= 6 and 0 <= hour <= 23 and 0 <= minute <= 59 and observer_id):
        raise ValueError('probe_schedule_invalid')
    local = now.astimezone(zone).replace(hour=hour, minute=minute, second=0, microsecond=0)
    due = local.astimezone(now.tzinfo)
    conn.execute('INSERT INTO probe_schedule_state(kind,observer_id,scope,next_due_at,cursor_json,revision) '
                 "VALUES('weekly',?,'global',?, ?,1) "
                 'ON CONFLICT(kind,observer_id,scope) DO UPDATE SET '
                 'next_due_at=excluded.next_due_at,cursor_json=excluded.cursor_json,revision=revision+1',
                 (observer_id, _iso(due), json.dumps({'enabled': bool(enabled), 'timezone': timezone,
                                                      'weekday': weekday, 'hour': hour, 'minute': minute},
                                                     sort_keys=True, separators=(',', ':'))))


def tick(conn, now) -> list[str]:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    rows = db.all_(conn, "SELECT * FROM probe_schedule_state WHERE next_due_at<=? ORDER BY next_due_at",
                   (_iso(now),))
    created = []
    for row in rows:
        cursor = json.loads(row['cursor_json'])
        if not cursor.get('enabled'):
            continue
        zone = ZoneInfo(cursor['timezone'])
        local = now.astimezone(zone)
        week_start = (local.date() - timedelta(days=local.weekday())).isoformat()
        key = f"weekly:{cursor['timezone']}:{week_start}"
        from .node_catalog import list_active_nodes
        nodes = [(item['node_uid'], item['revision']) for item in list_active_nodes(conn)]
        job = probe_store.enqueue(conn, trigger='weekly', observer_id=row['observer_id'],
            nodes=nodes, services=('basic',), schedule_key=key, now=now,
            deadline=now + timedelta(hours=4))
        created.append(job['id'])
        local_due = local.replace(hour=cursor['hour'], minute=cursor['minute'], second=0,
                                  microsecond=0)
        if local_due <= local:
            local_due += timedelta(days=7 - (local_due.weekday() - local.weekday()) % 7)
        conn.execute('UPDATE probe_schedule_state SET next_due_at=?,revision=revision+1 WHERE kind=? '
                     'AND observer_id=? AND scope=?', (_iso(local_due.astimezone(now.tzinfo)),
                                                       row['kind'], row['observer_id'], row['scope']))
    return created


def on_revision_changed(conn, node_uid: str, new_revision: int, now) -> list[str]:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    if db.get_setting(conn, 'v2_runtime_activation', 'staged') != 'active':
        return []
    return [f'material:{node_uid}:{new_revision}']
