"""观测视角注册、路径资格与探测目标白名单。"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .. import db


class PathNotQualified(ValueError):
    pass


OBSERVER_KINDS = frozenset({'fixture', 'independent_vps', 'nas', 'router', 'client'})
GOOGLE_PROBE_HOST_ALLOWLIST = frozenset({'www.google.com', 'mail.google.com',
                                         'www.youtube.com', 'gemini.google.com'})
BASIC_PROBE_HOST_ALLOWLIST = frozenset({'health.example.test'})


def admit_target(url: str, *, google: bool, country: str | None, egress_scope: str) -> bool:
    """目标先过固定白名单；country 只是观测标签，不构成禁令。"""
    host = urlsplit(url).hostname or ''
    if not host:
        return False
    if google:
        return host in GOOGLE_PROBE_HOST_ALLOWLIST
    return host in BASIC_PROBE_HOST_ALLOWLIST


def register(conn, observer: dict) -> dict:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    observer_id = observer.get('id')
    kind = observer.get('kind')
    revision = observer.get('config_revision')
    if not observer_id or kind not in OBSERVER_KINDS or type(revision) is not int or revision < 1:
        raise ValueError('observer_invalid')
    conn.execute('INSERT INTO probe_observers(id,kind,public_key,config_revision,enabled) '
                 'VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,'
                 'public_key=excluded.public_key,config_revision=excluded.config_revision,'
                 'enabled=excluded.enabled',
                 (observer_id, kind, observer.get('public_key', ''), revision,
                  int(bool(observer.get('enabled', True)))))
    return dict(db.one(conn, 'SELECT * FROM probe_observers WHERE id=?', (observer_id,)))


def _text(value) -> str:
    return value.isoformat()


def _time(value: str | datetime) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _signed(contract: dict, proof: dict, public_key: str) -> bool:
    body = json.dumps(contract, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()
    expected = hmac.new(public_key.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(proof.get('signature', '')), expected)


def qualify(conn, *, observer_id: str, contract: dict, proof: dict, now) -> dict:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    observer = db.one(conn, 'SELECT * FROM probe_observers WHERE id=?', (observer_id,))
    if not observer or not observer['enabled']:
        raise ValueError('observer_missing')
    signed_at = proof.get('signed_at')
    nonce = proof.get('nonce')
    observation_sha = proof.get('observation_sha')
    if not isinstance(contract, dict) or not isinstance(proof, dict):
        raise ValueError('path_contract_invalid')
    if (not isinstance(signed_at, (str, datetime)) or not isinstance(nonce, str) or not nonce or
            not isinstance(observation_sha, str) or len(observation_sha) != 64 or
            contract.get('config_revision') != observer['config_revision'] or
            not contract.get('scopes')):
        raise ValueError('path_contract_invalid')
    measured = _time(signed_at)
    if not measured or abs((_time(now) - measured).total_seconds()) > 300:
        raise ValueError('path_clock_skew')
    if not _signed(contract, proof, observer['public_key']):
        raise ValueError('path_signature_invalid')
    duplicate = db.one(conn, 'SELECT id FROM probe_paths WHERE proof_json LIKE ?',
                       (f'%{json.dumps(nonce)}%',))
    if duplicate:
        raise ValueError('path_nonce_reused')
    epoch_row = db.one(conn, 'SELECT COALESCE(MAX(epoch),0)+1 AS epoch FROM probe_paths '
                             'WHERE observer_id=?', (observer_id,))
    epoch = int(epoch_row['epoch'])
    state = 'fixture' if observer['kind'] == 'fixture' else 'verified'
    path_id = uuid.uuid4().hex
    conn.execute('INSERT INTO probe_paths(id,observer_id,epoch,contract_json,proof_json,state,'
                 'qualified_at,expires_at) VALUES(?,?,?,?,?,?,?,?)',
                 (path_id, observer_id, epoch, json.dumps(contract, ensure_ascii=False,
                                                          sort_keys=True, separators=(',', ':')),
                  json.dumps({'nonce': nonce, 'signed_at': signed_at,
                              'observation_sha': observation_sha}, ensure_ascii=False,
                             sort_keys=True, separators=(',', ':')),
                  state, _text(now), _text(now + timedelta(hours=24))))
    return dict(db.one(conn, 'SELECT * FROM probe_paths WHERE id=?', (path_id,)))


def require_path(conn, observer_id: str, path_epoch: int | str, scope: str, now) -> dict:
    try:
        epoch = int(path_epoch)
    except (TypeError, ValueError):
        raise PathNotQualified('path_epoch_invalid') from None
    row = db.one(conn, 'SELECT * FROM probe_paths WHERE observer_id=? AND epoch=?',
                 (observer_id, epoch))
    if not row or row['state'] != 'verified':
        raise PathNotQualified('path_not_verified')
    contract = json.loads(row['contract_json'])
    if scope not in contract.get('scopes', []) or row['expires_at'] < _text(now):
        raise PathNotQualified('path_scope_invalid')
    return db.row_to_dict(row)
