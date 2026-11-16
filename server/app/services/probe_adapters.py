"""探测适配器：状态归一、硬故障确认和跨出口熔断契约。"""
from datetime import datetime
import json
import uuid

from .recovery_policy import defaults


def _time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_response(probe: dict, response: dict) -> dict:
    status = int(response.get('status', 0))
    headers = {str(key).lower(): value for key, value in (response.get('headers') or {}).items()}
    body = response.get('body', b'')
    text = body.decode('utf-8', 'ignore') if isinstance(body, bytes) else str(body)
    content_type = headers.get('content-type', '')
    if status == 200:
        if headers.get('cf-mitigated') == 'challenge' or 'challenge' in text.lower():
            state = 'challenge'
        elif probe.get('expected_content_type') and probe['expected_content_type'] not in content_type:
            state = 'unknown'
        elif probe.get('ok_marker') and probe['ok_marker'] not in text:
            state = 'unknown'
        else:
            state = 'observed-ok'
    elif status == 401:
        state = 'auth-required'
    elif status == 429:
        state = 'rate-limited'
    else:
        state = 'unknown'
    return {'probe_id': probe['id'], 'probe_version': probe['version'],
            'result_state': state, 'http_status': status,
            'reason_code': f'http_{status}', 'content_type': content_type}


def confirm_failure(samples: list[dict], *, policy: dict, control_ok: bool = True) -> dict:
    untrusted = policy['detection']['untrusted_states']
    required = policy['detection']['hard_failure_confirmations']
    interval = policy['detection']['hard_failure_interval_seconds']
    votes = [row for row in samples if row.get('result_state') not in untrusted]
    if not control_ok:
        return {'confirmed': False, 'state': 'measurement_degraded', 'reason': 'control_failed'}
    if len(votes) < required or any(row.get('result_state') != 'blocked' for row in votes):
        return {'confirmed': False, 'state': 'pending', 'reason': 'not_hard_failure_votes'}
    times = sorted(_time(row['measured_at']) for row in votes)
    if not all(times):
        return {'confirmed': False, 'state': 'pending', 'reason': 'invalid_time'}
    if (times[-1] - times[0]).total_seconds() < interval:
        return {'confirmed': False, 'state': 'pending', 'reason': 'confirmation_interval_short'}
    return {'confirmed': True, 'state': 'confirmed', 'reason': 'hard_failure_confirmed'}


def catalog() -> tuple[dict, ...]:
    return (
        {'id': 'basic-entry', 'version': 'v1', 'service': 'basic', 'product': 'connectivity',
         'scope': 'web-entry', 'google': False, 'requests_max': 2,
         'bytes_max': 8192, 'timeout_seconds': 6, 'allowlist': BASIC_TARGETS,
         'license_ref': '', 'enabled': True},
        {'id': 'google-web', 'version': 'v1', 'service': 'google', 'product': 'web',
         'scope': 'google', 'google': True, 'requests_max': 2,
         'bytes_max': 8192, 'timeout_seconds': 6, 'allowlist': GOOGLE_TARGETS,
         'license_ref': '', 'enabled': True},
        {'id': 'muse-entry', 'version': 'v1', 'service': 'muse', 'product': 'web',
         'scope': 'web-entry', 'google': False, 'requests_max': 0,
         'bytes_max': 0, 'timeout_seconds': 0, 'allowlist': frozenset(),
         'license_ref': '', 'enabled': False},
    )


GOOGLE_TARGETS = frozenset({'www.google.com', 'mail.google.com', 'www.youtube.com',
                            'gemini.google.com'})
BASIC_TARGETS = frozenset({'health.example.test'})


def update_breaker(conn, probe_id: str, version: str, samples: list[dict], now) -> dict:
    if not conn.in_transaction:
        raise ValueError('probe_transaction_required')
    failures = sum(1 for row in samples if row.get('result_state') == 'blocked')
    domains = {row['fault_domain'] for row in samples if row.get('domain_verified')}
    suspect = len(domains) >= 3 and failures * 2 >= len(samples)
    state = 'suspect' if suspect else 'healthy'
    window = {'failures': failures, 'samples': len(samples), 'domains': sorted(domains)}
    conn.execute('INSERT INTO probe_adapter_health(probe_id,probe_version,state,window_json,'
                 'last_reason,updated_at) VALUES(?,?,?,?,?,?) '
                 'ON CONFLICT(probe_id,probe_version) DO UPDATE SET state=excluded.state,'
                 'window_json=excluded.window_json,last_reason=excluded.last_reason,'
                 'updated_at=excluded.updated_at',
                 (probe_id, version, state, json.dumps(window, sort_keys=True,
                                                       separators=(',', ':')),
                  'cross_domain_suspect' if suspect else '', now.isoformat()))
    return {'state': state, **window}
