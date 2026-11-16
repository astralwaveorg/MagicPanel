"""只读探测任务视图；不触发任何探测请求。"""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .. import db
from ..deps import CurrentUser, RequireCapabilities
from ..services import probe_store
from ..services.preview_tokens import PreviewTokenError, issue_preview, open_preview, payload_digest

router = APIRouter(prefix='/api/v1/probe-jobs', tags=['probe-jobs'])


def _public(row) -> dict:
    data = db.row_to_dict(row)
    for source, target in (('scope_json','scope'),('budget_json','budget'),
                           ('reason_codes_json','reason_codes')):
        data[target] = json.loads(data.pop(source))
    return data


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    variant_id: int = 0
    node_keys: list[dict] = Field(default_factory=list)
    service_ids: list[str] = Field(default_factory=list)
    observer_id: str
    trigger: str


class CreateBody(PreviewBody):
    preview_token: str
    expected_preview_digest: str
    idempotency_key: str = Field(min_length=8, max_length=128)


def _preview_state(conn, body: PreviewBody, user):
    revision = db.one(conn, 'SELECT revision FROM catalog_state WHERE id=1')['revision']
    observer = db.one(conn, 'SELECT * FROM probe_observers WHERE id=?', (body.observer_id,))
    blockers = []
    if not observer or not observer['enabled']:
        blockers.append('observer_not_qualified')
    elif observer['kind'] == 'fixture':
        blockers.append('observer_fixture_not_production')
    if not body.node_keys or not body.service_ids:
        blockers.append('probe_scope_empty')
    result = {'blockers': sorted(blockers), 'expected_revisions': {'catalog_revision': revision,
              'budget_revision': 0}, 'observer_id': body.observer_id,
              'service_ids': body.service_ids}
    result['input_sha'] = json.dumps(result['expected_revisions'], sort_keys=True,
                                     separators=(',', ':'))
    return result


@router.post('/preview')
def preview_jobs(body: PreviewBody, user=CurrentUser):
    with db.connect() as conn:
        state = _preview_state(conn, body, user)
    now = datetime.now(timezone.utc)
    scope = {'catalog_revision': state['expected_revisions']['catalog_revision'],
             'node_keys': body.node_keys, 'observer_id': body.observer_id}
    token = issue_preview(purpose='probe-job-create', actor_id=user['id'],
        normalized_payload={'variant_id': body.variant_id, 'services': body.service_ids},
        scope=scope, evaluation_at=now,
        expected_revisions=state['expected_revisions'],
        input_sha=state['input_sha'], digest=state['input_sha'], now=now)
    return {**state, **token}


@router.post('')
def create_jobs(body: CreateBody, user=RequireCapabilities('probe')):
    now = datetime.now(timezone.utc)
    try:
        claims = open_preview(body.preview_token, purpose='probe-job-create',
                              actor_id=user['id'], now=now)
    except PreviewTokenError as exc:
        raise HTTPException(403 if exc.code == 'preview_invalid' else 409, exc.code)
    if claims['digest'] != body.expected_preview_digest:
        raise HTTPException(409, 'preview_digest_stale')
    with db.tx(immediate=True) as conn:
        state = _preview_state(conn, body, user)
        if state['blockers'] or claims['digest'] != state['input_sha']:
            raise HTTPException(409, 'preview_digest_stale')
        nodes = []
        for key in body.node_keys:
            try:
                from ..services.probe_models import NodeKey
                nodes.append(NodeKey(str(key['node_uid']), int(key['revision'])))
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(400, 'preview_node_key_invalid') from exc
        job = probe_store.enqueue(conn, trigger=body.trigger, observer_id=body.observer_id,
            nodes=nodes, services=tuple(body.service_ids), schedule_key=None, now=now,
            deadline=now + timedelta(hours=4))
        state['expected_revisions']['catalog_revision']
    return {'job_id': job['id'], 'state': job['state'], 'digest': claims['digest']}


@router.get('')
def list_jobs(limit: int = 50, offset: int = 0, user=CurrentUser):
    with db.connect() as conn:
        return db.paged(conn, 'probe_jobs', order='created_at DESC, id',
                        limit=limit, offset=offset)


@router.get('/{job_id}')
def job_detail(job_id: str, user=CurrentUser):
    with db.connect() as conn:
        row = db.one(conn, 'SELECT * FROM probe_jobs WHERE id=?', (job_id,))
        if row is None:
            from fastapi import HTTPException
            raise HTTPException(404, '探测任务不存在')
        items = db.all_(conn, 'SELECT id,node_uid,node_revision,service_key,state,attempts,next_at '
                              'FROM probe_items WHERE job_id=? ORDER BY node_uid,service_key', (job_id,))
        result = {'job': _public(row), 'items': [db.row_to_dict(item) for item in items]}
        if row['state'] == 'completed':
            result['results'] = [db.row_to_dict(item) for item in db.all_(
                conn, 'SELECT r.* FROM probe_results r JOIN probe_items i ON i.id=r.item_id '
                      'WHERE i.job_id=?', (job_id,))]
    return result
