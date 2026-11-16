"""服务状态归一、失败确认与跨出口熔断合同。"""
import pytest


@pytest.mark.parametrize('status,headers,body,want', [
    (200, {'content-type': 'text/html'}, b'normal', 'observed-ok'),
    (200, {'cf-mitigated': 'challenge'}, b'challenge', 'challenge'),
    (401, {}, b'authentication required', 'auth-required'),
    (403, {}, b'denied', 'unknown'),
    (429, {}, b'slow down', 'rate-limited'),
])
def test_http_state_is_not_a_boolean(status, headers, body, want):
    from app.services.probe_adapters import parse_response
    probe = {'id': 'fixture-entry', 'version': '1', 'scope': 'web-entry',
             'ok_marker': 'normal', 'expected_content_type': 'text/html'}
    result = parse_response(probe, {'status': status, 'headers': headers, 'body': body})
    assert result['result_state'] == want
    assert 'body' not in result and 'cookie' not in str(result).lower()


def test_rate_limit_is_not_confirmed_node_failure():
    from app.services.probe_adapters import confirm_failure
    from app.services.recovery_policy import defaults
    result = confirm_failure([
        {'result_state': 'rate-limited', 'measured_at': '2026-11-15T04:00:00+00:00'},
        {'result_state': 'rate-limited', 'measured_at': '2026-11-15T04:01:00+00:00'},
    ], policy=defaults())
    assert result['confirmed'] is False
    assert result['state'] == 'pending'


def test_hard_failure_needs_interval_and_control():
    from app.services.probe_adapters import confirm_failure
    from app.services.recovery_policy import defaults
    rows = [{'result_state': 'blocked', 'measured_at': '2026-11-15T04:00:00+00:00'},
            {'result_state': 'blocked', 'measured_at': '2026-11-15T04:00:31+00:00'}]
    assert confirm_failure(rows, policy=defaults())['confirmed'] is True
    assert confirm_failure([rows[0], dict(rows[1], measured_at='2026-11-15T04:00:10+00:00')],
                           policy=defaults())['confirmed'] is False
    degraded = confirm_failure(rows, policy=defaults(), control_ok=False)
    assert degraded['state'] == 'measurement_degraded'


def test_catalog_never_guesses_disabled_muse():
    from app.services.probe_adapters import catalog
    items = {item['id']: item for item in catalog()}
    assert items['basic-entry']['requests_max'] <= 2
    assert items['muse-entry']['enabled'] is False
