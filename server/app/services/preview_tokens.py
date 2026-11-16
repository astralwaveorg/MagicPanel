"""预演令牌：认证加密、actor/purpose/输入绑定与短 TTL。"""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta

from .. import security


class PreviewTokenError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    signature = hmac.new(security.derive_subkey(security.load_master_material(),
                                                purpose='preview-token'),
                         raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=') + '.' + signature


def issue_preview(*, purpose: str, actor_id: int, normalized_payload: dict,
                  scope: dict, evaluation_at, expected_revisions: dict,
                  input_sha: str, digest: str, now) -> dict:
    if not purpose or actor_id < 1 or not input_sha or not digest:
        raise PreviewTokenError('preview_invalid')
    payload = {'version': 1, 'purpose': purpose, 'actor_id': actor_id,
               'normalized_payload': normalized_payload, 'scope': scope,
               'evaluation_at': evaluation_at.isoformat(),
               'expected_revisions': expected_revisions,
               'input_sha': input_sha, 'digest': digest,
               'nonce': uuid.uuid4().hex, 'issued_at': now.isoformat(),
               'expires_at': (now + timedelta(seconds=300)).isoformat()}
    return {'preview_token': _encode(payload), 'expires_at': payload['expires_at'],
            'digest': digest}


def open_preview(token: str, *, purpose: str, actor_id: int, now,
                 allow_expired_for_replay: bool = False) -> dict:
    try:
        encoded, signature = token.rsplit('.', 1)
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        expected = hmac.new(security.derive_subkey(security.load_master_material(),
                                                   purpose='preview-token'),
                            raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(raw)
        if payload.get('purpose') != purpose or payload.get('actor_id') != actor_id:
            raise ValueError
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        raise PreviewTokenError('preview_invalid') from None
    expired = now.isoformat() > payload['expires_at']
    if expired and not allow_expired_for_replay:
        raise PreviewTokenError('preview_expired')
    return payload


def payload_digest(payload: dict) -> str:
    normalized = {'purpose': payload['purpose'], 'scope': payload['scope'],
                  'evaluation_at': payload['evaluation_at'],
                  'expected_revisions': payload['expected_revisions'],
                  'normalized_payload': payload['normalized_payload']}
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()
