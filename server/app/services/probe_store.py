"""持久探测队列；网络与耗时操作必须由 worker 在事务外执行。"""
import json
import uuid
from datetime import timedelta

from .. import db
from .probe_models import JOB_STATES, NodeKey, RESULT_STATES


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _iso(value) -> str:
    return value.isoformat()


def enqueue(conn, *, trigger: str, observer_id: str, nodes: list[NodeKey],
            services: tuple[str, ...], schedule_key: str | None, now,
            deadline) -> dict:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    if not trigger or not observer_id or not services or not all(isinstance(s, str) and s for s in services):
        raise ValueError('probe_scope_invalid')
    keys = [node if isinstance(node, NodeKey) else NodeKey(node[0], int(node[1])) for node in nodes]
    job_id = uuid.uuid4().hex
    created = _iso(now)
    conn.execute('INSERT INTO probe_jobs(id,revision,trigger,schedule_key,observer_id,state,'
                 'scope_json,budget_json,created_at,updated_at,deadline_at,lease_owner,lease_until,'
                 'cancel_requested,reason_codes_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 (job_id, 1, trigger, schedule_key, observer_id, 'queued',
                  _json({'nodes': [{'node_uid': key.node_uid, 'revision': key.revision} for key in keys],
                         'services': list(services)}),
                  _json({'kind': 'deep', 'requests_reserved': 0, 'bytes_reserved': 0}),
                  created, created, _iso(deadline), None, None, 0, _json([])))
    for node in keys:
        for service in services:
            conn.execute('INSERT INTO probe_items(id,job_id,node_uid,node_revision,service_key,'
                         'source_bucket,fault_bucket,state,attempts,next_at,lease_owner,lease_until) '
                         'VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)',
                         (uuid.uuid4().hex, job_id, node.node_uid, node.revision, service,
                          '', '', 'queued', 0, _iso(now)))
    return dict(db.one(conn, 'SELECT * FROM probe_jobs WHERE id=?', (job_id,)))


def list_jobs(conn, *, limit: int, offset: int) -> dict:
    page = db.paged(conn, 'probe_jobs', order='created_at DESC, id', limit=limit, offset=offset)
    for row in page['items']:
        row['scope'] = json.loads(row.pop('scope_json'))
        row['budget'] = json.loads(row.pop('budget_json'))
        row['reason_codes'] = json.loads(row.pop('reason_codes_json'))
    return page


def claim(conn, *, worker_id: str, now, lease_seconds: int = 60) -> dict | None:
    """CAS 抢占下一个到期 item；调用方必须提供 IMMEDIATE 事务。"""
    if not worker_id:
        raise ValueError('probe_worker_invalid')
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    job = db.one(conn, "SELECT * FROM probe_jobs WHERE state='queued' AND cancel_requested=0 "
                 "AND deadline_at>=? ORDER BY created_at,id LIMIT 1", (_iso(now),))
    if job is None:
        return None
    item = db.one(conn, "SELECT * FROM probe_items WHERE job_id=? AND state='queued' "
                  "AND (next_at IS NULL OR next_at<=?) ORDER BY next_at,id LIMIT 1",
                  (job['id'], _iso(now)))
    if item is None:
        return None
    until = _iso(now.replace(microsecond=0) + timedelta(seconds=lease_seconds))
    changed = conn.execute("UPDATE probe_items SET state='running',lease_owner=?,lease_until=?,"
                           "attempts=attempts+1 WHERE id=? AND state='queued'",
                           (worker_id, until, item['id'])).rowcount
    if not changed:
        return None
    conn.execute("UPDATE probe_jobs SET state='running',lease_owner=?,updated_at=? "
                 "WHERE id=? AND state IN ('queued','running')", (worker_id, _iso(now), job['id']))
    return {'id': item['id'], 'job_id': job['id'], 'node_uid': item['node_uid'],
            'node_revision': item['node_revision'], 'service_key': item['service_key'],
            'lease_until': until}

def finish(conn, item_id: str, worker_id: str, result: dict, now) -> None:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    item = db.one(conn, 'SELECT * FROM probe_items WHERE id=?', (item_id,))
    job = db.one(conn, 'SELECT * FROM probe_jobs WHERE id=?', (item['job_id'],)) if item else None
    if not item or not job or item['state'] != 'running' or item['lease_owner'] != worker_id:
        raise ValueError('probe_lease_invalid')
    state = result.get('result_state')
    if state not in RESULT_STATES:
        raise ValueError('probe_result_invalid')
    requests = max(int(result.get('request_count', 0)), 0)
    read = max(int(result.get('bytes_read', 0)), 0)
    written = max(int(result.get('bytes_written', 0)), 0)
    conn.execute('INSERT OR REPLACE INTO probe_results(id,item_id,observer_id,path_epoch,probe_id,'
                 'probe_version,transport_state,result_state,reason_code,http_status,egress_json,'
                 'evidence_json,request_count,bytes_read,bytes_written,measured_at,valid_until) '
                 'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 (uuid.uuid4().hex, item_id, job['observer_id'], int(result.get('path_epoch', 0)),
                  str(result.get('probe_id', 'basic')), str(result.get('probe_version', 'v1')),
                  str(result.get('transport_state', 'unknown')), state,
                  str(result.get('reason_code', '')), result.get('http_status'),
                  _json(result.get('egress', {})), _json(result.get('evidence', {})),
                  requests, read, written, _iso(now),
                  _iso(result.get('valid_until', now))))
    conn.execute("UPDATE probe_items SET state='completed',lease_owner=NULL,lease_until=NULL WHERE id=?",
                 (item_id,))
    remaining = db.one(conn, "SELECT COUNT(*) AS n FROM probe_items WHERE job_id=? AND state!='completed'",
                       (job['id'],))['n']
    job_state = 'completed' if remaining == 0 else 'incomplete'
    conn.execute('UPDATE probe_jobs SET state=?,updated_at=? WHERE id=?',
                 (job_state, _iso(now), job['id']))


def cancel(conn, job_id: str, expected_revision: int, now) -> dict:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    changed = conn.execute('UPDATE probe_jobs SET cancel_requested=1,revision=revision+1,updated_at=? '
                           'WHERE id=? AND revision=? AND cancel_requested=0',
                           (_iso(now), job_id, expected_revision)).rowcount
    if not changed:
        raise ValueError('probe_job_stale')
    conn.execute("UPDATE probe_items SET state='cancelled',lease_owner=NULL,lease_until=NULL "
                 "WHERE job_id=? AND state IN ('queued','running')", (job_id,))
    conn.execute("UPDATE probe_jobs SET state='cancelled' WHERE id=?", (job_id,))
    return dict(db.one(conn, 'SELECT * FROM probe_jobs WHERE id=?', (job_id,)))
