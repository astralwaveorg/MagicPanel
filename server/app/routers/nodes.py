"""安全节点目录 HTTP API；材料正文只在显式 reveal 返回。"""
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import db, security
from ..deps import CurrentUser, RequireCapabilities
from ..services import local_nodes, node_catalog, node_dto, policy_mutations

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])


class MetadataBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_catalog_revision: int = Field(ge=0)
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    meta: dict | None = None


class ConfigurationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    protocol: str | None = Field(default=None, min_length=1, max_length=32)
    server: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    public_params: dict = Field(default_factory=dict)
    secret_set: dict = Field(default_factory=dict)
    secret_clear: list[str] = Field(default_factory=list)
    extra_yaml_set: str | None = Field(default=None, max_length=20_000)
    clear_extra_yaml: bool = False


class RenamePreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_uids: list[str] = Field(min_length=1, max_length=200)
    names: dict[str, str]
    expected_catalog_revision: int = Field(ge=0)


class RenameApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=16, max_length=20_000)
    expected_catalog_revision: int = Field(ge=0)


def _error(exc: ValueError, *, expected=None, current=None):
    detail = {'code': str(exc), 'message': '节点目录操作被拒绝',
              'request_id': uuid4().hex}
    if expected is not None:
        detail['expected_revision'] = expected
    if current is not None:
        detail['current_revision'] = current
    status = 403 if str(exc) == 'preview_actor_mismatch' else (
        409 if str(exc) in {'stale_revision', 'preview_expired', 'preview_consumed'} else 400)
    return HTTPException(status, detail)


def _catalog_revision(conn) -> int:
    return int(db.one(conn, 'SELECT revision FROM catalog_state WHERE id=1')['revision'])


def _entry(row) -> dict:
    entry = node_catalog._entry(row)
    public = json.loads(row['public_config_json'])
    entry.update(public)
    return entry


def _summary(conn, node_uid: str) -> dict | None:
    row = db.one(conn, 'SELECT c.*,r.public_config_json FROM node_catalog c '
                       'JOIN node_revisions r ON r.node_uid=c.node_uid AND r.revision=c.current_revision '
                       'WHERE c.node_uid=? AND c.retired=0', (node_uid,))
    return _entry(row) if row else None


def _references(conn, node_uid: str, emit_name: str, local_id: int | None) -> list[dict]:
    references = []
    for group in db.all_(conn, 'SELECT id,name,type,variant_id,members_format,members_v2,proxies,local_nodes '
                               'FROM proxy_groups ORDER BY variant_id,sort,id'):
        typed = json.loads(group['members_v2'] or '[]')
        used = (group['members_format'] == 'typed-v2' and
                {'kind':'node','ref':node_uid} in typed)
        legacy_used = (group['members_format'] != 'typed-v2' and (
            emit_name in json.loads(group['proxies'] or '[]') or
            (local_id is not None and local_id in json.loads(group['local_nodes'] or '[]'))))
        if used or legacy_used:
            references.append({'kind':'group','ref':str(group['id']),'name':group['name'],
                               'variant_id':int(group['variant_id'] or 0)})
    return references


def _row404(conn, node_uid: str):
    row = db.one(conn, 'SELECT * FROM node_catalog WHERE node_uid=? AND retired=0', (node_uid,))
    if not row:
        raise HTTPException(404, {'code':'node_missing','message':'节点不存在',
                                  'request_id':uuid4().hex})
    return row


@router.get('')
def list_nodes(limit: int = 50, offset: int = 0, user=CurrentUser):
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    with db.connect() as conn:
        total = db.one(conn, 'SELECT COUNT(*) AS n FROM node_catalog WHERE retired=0')['n']
        rows = db.all_(conn, 'SELECT c.*,r.public_config_json FROM node_catalog c '
                             'JOIN node_revisions r ON r.node_uid=c.node_uid AND r.revision=c.current_revision '
                             'WHERE c.retired=0 ORDER BY c.ordinal LIMIT ? OFFSET ?', (limit, offset))
        revision = _catalog_revision(conn)
    return {'items': [_entry(row) for row in rows], 'total': total,
            'limit': limit, 'offset': offset, 'catalog_revision': revision}


@router.get('/{node_uid}')
def node_detail(node_uid: str, user=CurrentUser):
    with db.connect() as conn:
        row = _row404(conn, node_uid)
        data = _summary(conn, node_uid)
        data.update(catalog_revision=_catalog_revision(conn),
                    references=_references(conn, node_uid, row['emit_name'], row['local_node_id']))
    return data


@router.patch('/{node_uid}/metadata')
def patch_metadata(node_uid: str, body: MetadataBody, user=CurrentUser):
    with db.tx(immediate=True) as conn:
        row = _row404(conn, node_uid)
        current = _catalog_revision(conn)
        if body.expected_catalog_revision != current:
            raise _error(ValueError('stale_revision'), expected=body.expected_catalog_revision,
                         current=current)
        display = row['display_name'] if body.display_name is None else body.display_name.strip()
        meta = json.loads(row['meta_json'])
        if body.meta is not None:
            unknown = set(body.meta) - {'labels', 'note', 'claimed_country'}
            if unknown:
                raise _error(ValueError('catalog_material_invalid'))
            meta.update(body.meta)
        security.audit(conn, user['username'], '修改节点目录属性', 'node_catalog', node_uid,
                       {'fields': sorted(k for k in ('display_name', 'meta') if getattr(body,k) is not None)})
        changed = (display != row['display_name'] or meta != json.loads(row['meta_json']))
        if changed:
            conn.execute('UPDATE node_catalog SET display_name=?,meta_json=?,last_seen=? WHERE node_uid=?',
                         (display, json.dumps(meta, ensure_ascii=False), db.now(), node_uid))
            conn.execute('UPDATE catalog_state SET revision=revision+1 WHERE id=1')
        current = _catalog_revision(conn)
        result = {'ok': True, **(_summary(conn, node_uid) or {}), 'catalog_revision': current}
    return result


@router.post('/{node_uid}/reveal')
def reveal_node(node_uid: str, response: Response, user=RequireCapabilities('reveal')):
    response.headers['Cache-Control'] = 'no-store'
    with db.tx() as conn:
        row = _row404(conn, node_uid)
        if row['origin_kind'] != 'local' or not row['local_node_id']:
            raise _error(ValueError('catalog_source_patch_unsupported'))
        local = db.one(conn, 'SELECT * FROM local_nodes WHERE id=?', (row['local_node_id'],))
        security.audit(conn, user['username'], '查看节点凭据', 'node_catalog', node_uid,
                       {'fields': ['params', 'extra_yaml']})
        result = {'node_uid': node_uid, 'revision': int(row['current_revision']),
                  **node_dto.reveal_configuration(local)}
    return result


@router.patch('/{node_uid}/configuration')
def patch_configuration(node_uid: str, body: ConfigurationBody, user=RequireCapabilities('edit', 'reveal')):
    with db.tx(immediate=True) as conn:
        row = _row404(conn, node_uid)
        if row['origin_kind'] != 'local' or not row['local_node_id']:
            raise _error(ValueError('catalog_source_patch_unsupported'))
        if body.expected_revision != int(row['current_revision']):
            raise _error(ValueError('stale_revision'), expected=body.expected_revision,
                         current=int(row['current_revision']))
        local = dict(db.one(conn, 'SELECT * FROM local_nodes WHERE id=?', (row['local_node_id'],)))
        revealed = node_dto.reveal_configuration(local)
        current = node_dto.configuration(local['protocol'], revealed['params'], revealed['extra_yaml'])
        patch = {
            'public_params': body.public_params,
            'secret_set': body.secret_set,
            'secret_clear': body.secret_clear,
        }
        if body.extra_yaml_set is not None:
            patch['extra_yaml'] = body.extra_yaml_set
        if body.clear_extra_yaml:
            patch['clear_extra_yaml'] = True
        protocol = body.protocol or local['protocol']
        try:
            node_dto.validate_patch(protocol, patch)
            merged = node_dto.merge_configuration(current, patch)
            params = {**merged['public_params'], **merged['secrets']}
            local_nodes.normalize_params(protocol, params)
            local_nodes.parse_extra(merged['extra_yaml'])
        except ValueError as exc:
            raise HTTPException(400, {'code':'catalog_material_invalid',
                'message':f'节点配置无效，当前数据未修改：{exc or "请检查字段及必填凭据"}',
                'request_id':uuid4().hex}) from None
        conn.execute('UPDATE local_nodes SET protocol=?,server=?,port=?,params_enc=?,extra_yaml_enc=?,updated_at=? WHERE id=?',
                     (protocol, body.server or local['server'],
                      body.port or local['port'], security.encrypt_text(json.dumps(params, ensure_ascii=False)),
                      security.encrypt_text(merged['extra_yaml']), db.now(), local['id']))
        security.audit(conn, user['username'], '修改节点连接配置', 'node_catalog', node_uid,
                       {'fields': sorted(k for k in body.model_fields_set if k != 'secret_set')})
        node_catalog.sync_local_node(conn, local['id'])
        revision = int(db.one(conn, 'SELECT current_revision FROM node_catalog WHERE node_uid=?', (node_uid,))['current_revision'])
        result = {'ok': True, **(_summary(conn, node_uid) or {}), 'revision': revision}
    return result


@router.post('/rename-preview')
def rename_preview(body: RenamePreviewBody, user=CurrentUser):
    with db.connect() as conn:
        try:
            return policy_mutations.preview_rename(conn, node_uids=body.node_uids,
                names=body.names, expected_catalog_revision=body.expected_catalog_revision,
                actor_id=user['id'])
        except ValueError as exc:
            raise _error(exc, expected=body.expected_catalog_revision,
                         current=_catalog_revision(conn)) from None


@router.post('/rename-apply')
def rename_apply(body: RenameApplyBody, user=CurrentUser):
    with db.tx(immediate=True) as conn:
        try:
            result = policy_mutations.apply_rename(conn, preview_id=body.preview_id,
                expected_catalog_revision=body.expected_catalog_revision, actor_id=user['id'])
        except ValueError as exc:
            raise _error(exc, expected=body.expected_catalog_revision,
                         current=_catalog_revision(conn)) from None
        security.audit(conn, user['username'], '应用节点改名', 'node_catalog',
                       ','.join(item['node_uid'] for item in result['changes']),
                       {'catalog_revision': result['catalog_revision']})
    return result
