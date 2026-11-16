"""只读探测任务视图；不触发任何探测请求。"""
import json

from fastapi import APIRouter

from .. import db
from ..deps import CurrentUser

router = APIRouter(prefix='/api/v1/probe-jobs', tags=['probe-jobs'])


def _public(row) -> dict:
    data = db.row_to_dict(row)
    for source, target in (('scope_json','scope'),('budget_json','budget'),
                           ('reason_codes_json','reason_codes')):
        data[target] = json.loads(data.pop(source))
    return data


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
