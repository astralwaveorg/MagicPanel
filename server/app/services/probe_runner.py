"""基础探针执行器；transport 是唯一网络边界。"""
import hashlib
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from .probe_models import RESULT_STATES
from .probe_observers import admit_target


SMALL_READ_LIMIT = 8192
BASIC_DEADLINE_SECONDS = 6


def run_item(item: dict, transport, *, now) -> dict:
    """执行单次基础检查；材料只进入 transport 配置，不进入结果。"""
    url = item.get('url', '')
    google = bool(item.get('google'))
    if not admit_target(url, google=google, country=item.get('country'),
                        egress_scope=item.get('egress_scope', '')):
        return _result(item, 'blocked', 'target_not_admitted', 0, now, {}, {})
    host = urlsplit(url).hostname or ''
    deadline = BASIC_DEADLINE_SECONDS
    request_count = 1
    try:
        response = transport('GET', url, headers={'host': host, 'user-agent': 'MagicPanel-Probe/1'},
                             body=b'', max_read=SMALL_READ_LIMIT, deadline=deadline)
        status = int(response.get('status', 0))
        body = response.get('body', b'')
        if status in (401,):
            state, reason = 'auth-required', 'http_auth_required'
        elif status == 403:
            state, reason = 'challenge', 'http_challenge'
        elif status == 429:
            state, reason = 'rate-limited', 'http_rate_limited'
        elif 200 <= status < 400:
            state, reason = 'observed-ok', ''
        else:
            state, reason = 'blocked', f'http_{status}'
        evidence = {'body_sha256': hashlib.sha256(body).hexdigest(),
                    'max_read': SMALL_READ_LIMIT, 'host': host}
        egress = item.get('egress', {})
    except Exception as exc:
        request_count = max(int(getattr(exc, 'request_count', 1)), 1)
        state, reason = 'blocked', 'transport_error'
        evidence = {'exception_type': type(exc).__name__}
        egress = {}
    return _result(item, state, reason, request_count, now, egress, evidence,
                   http_status=locals().get('status'))


def _result(item: dict, state: str, reason: str, request_count: int, now,
            egress: dict, evidence: dict, *, http_status=None) -> dict:
    if state not in RESULT_STATES:
        raise ValueError('probe_result_invalid')
    return {
        'node_uid': item['node_uid'], 'node_revision': item['node_revision'],
        'service_key': item['service_key'], 'observer_id': item.get('observer_id', ''),
        'path_epoch': int(item.get('path_epoch', 0)), 'probe_id': 'basic',
        'probe_version': 'v1', 'transport_state': state,
        'result_state': state, 'reason_code': reason, 'http_status': http_status,
        'egress': egress, 'evidence': evidence, 'request_count': request_count,
        'bytes_read': 0, 'bytes_written': 0, 'measured_at': now,
        'valid_until': now + timedelta(hours=24),
    }
