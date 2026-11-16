"""实际引用字节的版本化；复用 01 加密 BLOB。"""
import hashlib
import uuid

from .. import db
from . import resource_store


KINDS = frozenset({'provider', 'rule', 'dns-owner', 'artifact'})


def _metadata(conn, *, kind: str, name: str, behavior: str, format: str,
              schema_version: str, body: bytes, blob_id: str) -> tuple[str, bool]:
    if kind not in KINDS or not name or format != format.lower():
        raise ValueError('resource_metadata_invalid')
    content_sha = hashlib.sha256(body).hexdigest()
    row = db.one(conn, 'SELECT id FROM resource_revisions WHERE kind=? AND logical_name=? AND '
                       'content_sha=? AND schema_version=? AND behavior=? AND format=? AND revoked_at IS NULL',
                 (kind, name, content_sha, schema_version, behavior, format.lower()))
    if row:
        return row['id'], False
    resource_id = uuid.uuid4().hex
    conn.execute('INSERT INTO resource_revisions(id,kind,logical_name,content_sha,blob_id,'
                 'behavior,format,byte_length,schema_version,created_at) '
                 'VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (resource_id, kind, name, content_sha, blob_id, behavior, format.lower(),
                  len(body), schema_version, db.now()))
    return resource_id, True


def freeze_bytes(conn, *, kind: str, name: str, body: bytes, behavior: str | None,
                 format: str, schema_version: str = 'v1') -> dict:
    if not conn.in_transaction:
        raise ValueError('resource_transaction_required')
    body = bytes(body)
    store_kind = 'artifact' if kind not in ('node-material',) else kind
    blob = resource_store.put_private(conn, store_kind, body)
    resource_id, created = _metadata(conn, kind=kind, name=name,
                                     behavior=behavior or '', format=format,
                                     schema_version=schema_version, body=body,
                                     blob_id=blob['blob_id'])
    row = db.one(conn, 'SELECT * FROM resource_revisions WHERE id=?', (resource_id,))
    result = db.row_to_dict(row)
    result['created'] = created
    return result


def read_revision(conn, resource_id: str) -> bytes:
    row = db.one(conn, 'SELECT blob_id,revoked_at FROM resource_revisions WHERE id=?',
                 (resource_id,))
    if not row or row['revoked_at']:
        raise ValueError('resource_revision_missing')
    return resource_store.get_private(conn, row['blob_id'])
