"""观测视角注册、路径资格与探测目标白名单。"""
import json
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .. import db


class PathNotQualified(ValueError):
    pass


OBSERVER_KINDS = frozenset({'fixture', 'independent_vps', 'nas', 'router', 'client'})
GOOGLE_PROBE_HOST_ALLOWLIST = frozenset({'www.google.com', 'mail.google.com',
                                         'www.youtube.com', 'gemini.google.com'})
BASIC_PROBE_HOST_ALLOWLIST = frozenset({'health.example.test'})
PATH_PROOF_VERSION = 2
_SHA256 = re.compile(r'[a-f0-9]{64}')
_NONCE = re.compile(r'[A-Za-z0-9_-]{12,128}')


def admit_target(url: str, *, google: bool, country: str | None, egress_scope: str) -> bool:
    """目标先过固定白名单；country 只是观测标签，不构成禁令。"""
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.fragment):
            return False
    except (TypeError, ValueError):
        return False
    host = parts.hostname or ''
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


def path_proof_message(observer_id: str, contract: dict, proof: dict) -> bytes:
    """序列化观测回执。签名绑定观测者、证据摘要及有效期计算所用时间。"""
    return json.dumps({
        'purpose': 'magicpanel-observer-path', 'version': PATH_PROOF_VERSION,
        'observer_id': observer_id, 'contract': contract,
        'signed_at': proof['signed_at'], 'nonce': proof['nonce'],
        'observation_sha': proof['observation_sha'],
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def verified_proof(observer_id: str, public_key: str, contract: dict, proof: dict) -> bool:
    if (not isinstance(contract, dict) or not isinstance(proof, dict)
            or proof.get('version') != PATH_PROOF_VERSION or not isinstance(public_key, str)
            or not _SHA256.fullmatch(public_key)
            or not isinstance(proof.get('nonce'), str) or not _NONCE.fullmatch(proof['nonce'])
            or not isinstance(proof.get('observation_sha'), str)
            or not _SHA256.fullmatch(proof['observation_sha'])
            or not isinstance(proof.get('signed_at'), str)
            or not isinstance(proof.get('signature'), str)
            or not re.fullmatch(r'[a-f0-9]{128}', proof['signature'])):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            bytes.fromhex(proof['signature']), path_proof_message(observer_id, contract, proof))
        return True
    except (InvalidSignature, ValueError, TypeError, UnicodeError):
        return False


def qualify(conn, *, observer_id: str, contract: dict, proof: dict, now) -> dict:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    observer = db.one(conn, 'SELECT * FROM probe_observers WHERE id=?', (observer_id,))
    if not observer or not observer['enabled']:
        raise ValueError('observer_missing')
    if not isinstance(contract, dict) or not isinstance(proof, dict):
        raise ValueError('path_contract_invalid')
    scopes = contract.get('scopes')
    if (type(contract.get('config_revision')) is not int
            or contract['config_revision'] != observer['config_revision']
            or not isinstance(scopes, list) or not scopes
            or not all(isinstance(scope, str) and scope for scope in scopes)):
        raise ValueError('path_contract_invalid')
    measured, now = _time(proof.get('signed_at')), _time(now)
    if (not measured or not now or measured.utcoffset() is None or now.utcoffset() is None
            or abs((now - measured).total_seconds()) > 300):
        raise ValueError('path_clock_skew')
    if not verified_proof(observer_id, observer['public_key'], contract, proof):
        raise ValueError('path_signature_invalid')
    duplicate = db.one(conn, "SELECT id FROM probe_paths WHERE observer_id=? "
                       "AND json_extract(proof_json,'$.nonce')=?", (observer_id, proof['nonce']))
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
                  json.dumps({key: proof[key] for key in
                              ('version', 'nonce', 'signed_at', 'observation_sha', 'signature')},
                             ensure_ascii=False, sort_keys=True, separators=(',', ':')),
                  state, _text(now), _text(min(now, measured) + timedelta(hours=24))))
    return dict(db.one(conn, 'SELECT * FROM probe_paths WHERE id=?', (path_id,)))


def require_path(conn, observer_id: str, path_epoch: int | str, scope: str, now) -> dict:
    try:
        epoch = int(path_epoch)
    except (TypeError, ValueError):
        raise PathNotQualified('path_epoch_invalid') from None
    row = db.one(conn, 'SELECT p.*,o.public_key,o.config_revision FROM probe_paths p '
                 'JOIN probe_observers o ON o.id=p.observer_id '
                 "WHERE p.observer_id=? AND p.epoch=? AND o.enabled=1 AND o.kind!='fixture'",
                 (observer_id, epoch))
    if not row or row['state'] != 'verified':
        raise PathNotQualified('path_not_verified')
    try:
        contract, proof = (json.loads(row[key]) for key in ('contract_json', 'proof_json'))
        qualified_at, expires_at = (_time(row[key]) for key in ('qualified_at', 'expires_at'))
        verified = verified_proof(observer_id, row['public_key'], contract, proof)
        in_scope = (verified and scope in contract['scopes']
                    and contract['config_revision'] == row['config_revision']
                    and qualified_at <= now < expires_at)
    except (KeyError, TypeError, ValueError):
        raise PathNotQualified('path_not_verified') from None
    if not verified:
        raise PathNotQualified('path_not_verified')
    if not in_scope:
        raise PathNotQualified('path_scope_invalid')
    result = db.row_to_dict(row)
    result.pop('public_key')
    return result
