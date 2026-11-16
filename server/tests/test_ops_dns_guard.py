from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def step(tmp_path, kind, now, a, b, elapsed=0):
    if os.name != 'posix':
        pytest.skip('real ash state machine also executed in isolated Linux')
    path = tmp_path/f'{kind}.state'
    shell = [os.environ['MPV2_ASH'], 'ash'] if os.environ.get('MPV2_ASH') else ['sh']
    result = subprocess.run([*shell, str(ROOT/'ops/router/guard_state.sh'), kind, str(path),
                             str(now), str(int(a)), str(int(b)), str(elapsed)],
                            text=True, capture_output=True, check=True)
    state = dict(line.split('=', 1) for line in path.read_text().splitlines())
    return state, result.stdout.strip()


def test_single_trusted_failure_does_not_switch_cn_or_default(tmp_path):
    state, action = step(tmp_path, 'dns', 0, True, True)
    assert state['mode'] == 'TRUSTED' and action == 'none'
    assert state['cn_branch'] == 'independent'


def test_both_trusted_fail_immediately_degrade_without_claiming_trust(tmp_path):
    state, action = step(tmp_path, 'dns', 0, True, False)
    assert action == 'emergency' and state['mode'] == 'DNS_DEGRADED'
    assert state['overseas_trusted'] == '0' and state['epoch'] == '1'


def test_dns_recovery_needs_three_successes_separated_by_ten_seconds(tmp_path):
    step(tmp_path, 'dns', 0, True, False)
    for now in (1000, 2000, 3000, 10000, 11000):
        state, action = step(tmp_path, 'dns', now, True, True)
        assert action == 'none'
    state, action = step(tmp_path, 'dns', 21000, True, True)
    assert action == 'trusted' and state['epoch'] == '2'


def test_agh_hang_bypasses_independently_and_state_survives_process_restart(tmp_path):
    state, action = step(tmp_path, 'dns', 0, False, True)
    assert action == 'emergency' and state['mode'] == 'AGH_BYPASS'
    state, action = step(tmp_path, 'dns', 1000, True, True)
    assert action == 'none' and state['mode'] == 'AGH_BYPASS'
    assert state['epoch'] == '1'


def test_recovery_failure_resets_confirmation_and_preserves_last_good(tmp_path):
    step(tmp_path, 'dns', 0, True, True)
    step(tmp_path, 'dns', 2000, True, False)
    for now, healthy in ((3000, True), (13000, True), (14000, False), (23000, True)):
        state, action = step(tmp_path, 'dns', now, True, healthy)
    assert action == 'none' and state['mode'] == 'DNS_DEGRADED'
    assert state['last_good'] == '0' and state['successes'] == '1'


def test_gateway_shared_deadline_and_persisted_cooldown(tmp_path):
    for now in (0, 2000, 4000):
        state, action = step(tmp_path, 'gateway', now, True, True, 1001)
    assert action == 'withdraw' and state['mode'] == 'BASIC_WAN'
    for now in (6000, 8000, 10000, 12000, 14000):
        state, action = step(tmp_path, 'gateway', now, True, True, 20)
        assert action == 'none'
    state, action = step(tmp_path, 'gateway', 64000, True, True, 20)
    assert action == 'apply' and state['mode'] == 'MANAGED'


def test_probe_failures_cannot_be_hidden_by_one_success(tmp_path):
    for now in (0, 2000, 4000):
        state, action = step(tmp_path, 'gateway', now, True, False, 100)
    assert action == 'withdraw'


def test_state_rejects_injection_and_does_not_execute_file(tmp_path):
    if os.name != 'posix':
        pytest.skip('Linux ash execution')
    marker = tmp_path/'executed'
    (tmp_path/'dns.state').write_text(f'mode=$(touch {marker})\nepoch=1\n')
    with pytest.raises(subprocess.CalledProcessError):
        step(tmp_path, 'dns', 0, True, True)
    assert not marker.exists()
