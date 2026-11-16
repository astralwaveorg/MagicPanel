from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_alive_core_failed_or_slow_nodes_must_keep_cold_cn_working():
    from scripts.ops.network_lab import check_node_isolation_cases
    names = ('all_nodes_failed_core_alive', 'all_nodes_slow_core_alive')
    cases = {name: {'core_alive': True, 'cn_cold_dns': 'passed',
                    'cn_new_connection': 'passed'} for name in names}
    assert check_node_isolation_cases(cases) == []
    for name in names:
        broken = copy.deepcopy(cases)
        broken[name]['cn_cold_dns'] = 'failed'
        assert f'CN_ISOLATION_FAILED:{name}' in check_node_isolation_cases(broken)
    assert check_node_isolation_cases({})


def test_model_only_or_all_blocked_cannot_prove_cn_survival():
    from scripts.ops.network_lab import certify_fault_report
    for report in ({'source_kind': 'fixture_model', 'cn_failed': 0},
                   {'source_kind': 'packet_namespace', 'cn_failed': 1}):
        assert certify_fault_report(report, {'scope_sha': 'scope-a'})


def test_unknown_us_does_not_prove_us_exhaustion():
    from scripts.ops.network_lab import consume_google_trace
    trace = {'us': [{'state': 'unknown'}], 'sg': [{'state': 'available'}],
             'chosen_tier': 'SG', 'core_healthy': True}
    assert 'TIER_EXHAUSTION_UNPROVEN' in consume_google_trace(trace)


def test_normal_google_failure_does_not_activate_basic_mode():
    from scripts.ops.network_lab import consume_google_trace
    trace = {'us': [{'state': 'failed'}], 'sg': [{'state': 'failed'}],
             'jp': [{'state': 'failed'}], 'core_healthy': True,
             'chosen_tier': 'DIRECT', 'gateway_mode': 'basic'}
    assert consume_google_trace(trace)


def test_google_trace_rejects_stale_or_incomplete_exhaustion():
    from scripts.ops.network_lab import consume_google_trace
    trace = {'us': [{'state': 'failed', 'node_key': 'u1', 'fresh': True}],
             'sg': [{'state': 'available', 'node_key': 's1', 'fresh': True}],
             'jp': [], 'chosen_tier': 'SG', 'core_healthy': True,
             'scope_sha': 's', 'evidence_scope_sha': 'old',
             'revision': 2, 'evidence_revision': 1,
             'eligible': {'US': ['u1', 'u2'], 'SG': ['s1'], 'JP': []}}
    errors = consume_google_trace(trace)
    assert 'TIER_EXHAUSTION_UNPROVEN' in errors
    assert 'GOOGLE_EVIDENCE_STALE' in errors


def test_google_trace_does_not_plan_or_reward_faster_lower_tier():
    from scripts.ops.network_lab import consume_google_trace
    trace = {'us': [{'state': 'available', 'node_key': 'u1', 'fresh': True}],
             'sg': [{'state': 'available', 'node_key': 's1', 'fresh': True}],
             'jp': [], 'chosen_tier': 'US', 'core_healthy': True,
             'scope_sha': 's', 'evidence_scope_sha': 's',
             'revision': 2, 'evidence_revision': 2,
             'eligible': {'US': ['u1'], 'SG': ['s1'], 'JP': []},
             'recursive_leaves': ['u1'], 'provider_leaves': ['u1']}
    assert consume_google_trace(trace) == []
    trace['chosen_tier'] = 'SG'
    assert 'TIER_EXHAUSTION_UNPROVEN' in consume_google_trace(trace)
    trace['chosen_tier'] = 'US'
    trace['provider_leaves'].append('DIRECT')
    assert 'GOOGLE_DIRECT_LEAF' in consume_google_trace(trace)


def test_lab_rejects_unsafe_prefix_before_reading_candidate(tmp_path):
    from scripts.ops.network_lab import run_lab
    for prefix in ('all', 'mpv2-12345678;echo', '../mpv2-12345678'):
        with pytest.raises(ValueError, match='LAB_PREFIX_REQUIRED'):
            run_lab('all', prefix=prefix, candidate=tmp_path/'absent')


def test_claimed_pass_without_packet_or_runtime_is_rejected():
    from scripts.ops.network_lab import certify_fault_report
    report = {'source_kind': 'packet_namespace', 'scope_sha': 's',
              'candidate_sha': 'c', 'cases': {'core_stop': {'status': 'passed'}},
              'cn_failed': 0}
    errors = certify_fault_report(report, {'scope_sha': 's', 'candidate_sha': 'c'})
    assert 'CASE_EVIDENCE_REQUIRED:core_stop' in errors
    assert any(e.startswith('CASE_MISSING:') for e in errors)


def test_restore_budget_is_per_case_not_average():
    from scripts.ops.network_lab import certify_fault_report
    report = {'source_kind': 'packet_namespace', 'scope_sha': 's',
              'candidate_sha': 'c', 'cases': {'core_stop': {
                  'status': 'passed', 'owner_withdraw_ms': 8001, 'cn_recovered_ms': 10}},
              'cn_failed': 0}
    errors = certify_fault_report(report, {'scope_sha': 's', 'candidate_sha': 'c'})
    assert 'OWNER_DEADLINE:core_stop' in errors


def test_candidate_commands_are_never_accepted(tmp_path):
    import json
    from scripts.ops.network_lab import load_candidate
    path = tmp_path/'candidate.json'
    path.write_text(json.dumps({'schema': 1, 'commands': ['sh', '-c', 'echo bad']}))
    with pytest.raises(ValueError, match='CANDIDATE_SCHEMA'):
        load_candidate(path)


def test_report_cannot_pass_with_changed_policy_or_invented_digest():
    from scripts.ops.network_lab import certify_fault_report
    report = {'source_kind': 'packet_namespace', 'scope_sha': 's', 'candidate_sha': 'c',
              'policy': {'limits': {'owner_withdraw_ms': 80000}},
              'cases': {'shared_ip': {'status': 'passed', 'packet_sha': 'a'*64,
                                     'runtime_sha': 'b'*64, 'candidate_sha': 'c'}}, 'cn_failed': 0}
    errors = certify_fault_report(report, {'scope_sha': 's', 'candidate_sha': 'c'})
    assert 'POLICY_REVISION_MISMATCH' in errors
    assert 'CASE_EVIDENCE_REQUIRED:shared_ip' in errors


def test_internal_worker_rejects_direct_execution_before_any_network_change():
    from scripts.ops.network_lab import packet_worker
    with pytest.raises(ValueError, match='NESTED_NAMESPACE_REQUIRED'):
        packet_worker('all', {'parent_netns': 'unknown', 'parent_mountns': 'unknown'})


def test_host_snapshot_rejects_marker_executable_in_candidate(tmp_path):
    if sys.platform != 'linux':
        pytest.skip('host argv regression runs in Linux')
    from scripts.ops.network_lab import host_snapshot
    marker = tmp_path/'executed'
    fake = tmp_path/'nft'
    fake.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    fake.chmod(0o700)
    with pytest.raises(ValueError, match='TRUSTED_TOOL_REQUIRED'):
        host_snapshot({'tools': {'nft': str(fake)}})
    assert not marker.exists()


@pytest.mark.parametrize('kind', ['symlink', 'git'])
def test_private_output_rejects_link_or_git_before_host_probe(tmp_path, monkeypatch, kind):
    if sys.platform != 'linux':
        pytest.skip('namespace output path validation runs in Linux')
    from scripts.ops import network_lab
    target = tmp_path/'target'; target.mkdir(mode=0o700)
    if kind == 'symlink':
        link = tmp_path/'link'; link.symlink_to(target, target_is_directory=True)
        output = link/'child'; code = 'PRIVATE_PATH_SYMLINK'
    else:
        (target/'.git').mkdir(); output = target/'child'; code = 'PRIVATE_PATH_IN_GIT'
    def forbidden(_):
        raise AssertionError('host probe was reached before output validation')
    monkeypatch.setattr(network_lab, 'host_snapshot', forbidden)
    with pytest.raises(ValueError, match=code):
        network_lab._run_isolated('all', 'mpv2-aabbccdd', {'out_private': str(output)})


def test_private_worker_input_and_result_are_mode_600(tmp_path, monkeypatch):
    if sys.platform != 'linux':
        pytest.skip('POSIX mode check')
    from scripts.ops import network_lab
    output = tmp_path/'private'
    monkeypatch.setattr(network_lab, 'host_snapshot', lambda _: {'fixed': 'unchanged'})
    monkeypatch.setattr(network_lab.subprocess, 'run',
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, '', ''))
    spec = {'out_private': str(output), 'scope': {'test': True}, 'candidate_sha': 'c'}
    network_lab._run_isolated('all', 'mpv2-aabbccdd', spec)
    directory = output/'mpv2-aabbccdd'
    assert output.stat().st_mode & 0o777 == 0o700
    assert directory.stat().st_mode & 0o777 == 0o700
    for name in ('worker-input.json', 'report.json'):
        assert (directory/name).stat().st_mode & 0o777 == 0o600


def test_candidate_rejects_self_attested_core(tmp_path):
    from scripts.ops.network_lab import load_candidate, file_digest, ROOT
    fake = tmp_path/'core'; fake.write_text('#!/bin/sh\nexit 0\n')
    files = [ROOT/'ops/router'/name for name in (
        'apply_bundle.sh', 'gateway_watch.sh', 'rollback_bundle.sh', 'dns_watch.sh',
        'guard_common.sh', 'guard_state.sh', 'magicpanel-gateway-watch.init', 'magicpanel-dns-watch.init')]
    spec = {'schema': 1, 'role': 'offline_lab', 'scope': {},
            'profile': 'linux-redirect-tproxy-dualstack-v1',
            'core': {'path': str(fake), 'sha256': file_digest(fake)},
            'files': [{'path': str(p), 'sha256': file_digest(p)} for p in files], 'tools': {}}
    path = tmp_path/'candidate.json'; path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match='TRUSTED_CORE_REQUIRED'):
        load_candidate(path)


def test_host_child_does_not_inherit_loader_shell_or_python_injection(monkeypatch):
    if sys.platform != 'linux':
        pytest.skip('Linux loader environment')
    from scripts.ops.network_lab import trusted_process_env
    for key in ('LD_PRELOAD', 'LD_AUDIT', 'BASH_ENV', 'ENV', 'PYTHONPATH', 'PYTHONHOME'):
        monkeypatch.setenv(key, '/tmp/marker-injection')
    monkeypatch.setenv('LD_LIBRARY_PATH', '/tmp/untrusted-libs')
    env = trusted_process_env()
    result = subprocess.run(['/usr/bin/env'], env=env, capture_output=True, text=True, check=True)
    assert 'marker-injection' not in result.stdout
    assert 'untrusted-libs' not in result.stdout
    assert env['PATH'] == '/usr/sbin:/usr/bin:/sbin:/bin'


def test_foreign_watch_script_is_rejected_even_with_correct_self_hash(tmp_path):
    if sys.platform != 'linux':
        pytest.skip('uses verified offline core in Linux cache')
    from scripts.ops.network_lab import load_candidate, file_digest, ROOT
    core = Path('/home/jonny/.cache/magicpanel-network-lab/bin/mihomo')
    if not core.is_file():
        pytest.skip('verified lab core unavailable')
    names = ('apply_bundle.sh', 'gateway_watch.sh', 'rollback_bundle.sh', 'dns_watch.sh',
             'guard_common.sh', 'guard_state.sh', 'magicpanel-gateway-watch.init', 'magicpanel-dns-watch.init')
    files = [ROOT/'ops/router'/name for name in names]
    foreign = tmp_path/'gateway_watch.sh'; foreign.write_text('#!/bin/sh\nexit 0\n')
    files[1] = foreign
    spec = {'schema': 1, 'role': 'offline_lab', 'scope': {},
            'profile': 'linux-redirect-tproxy-dualstack-v1',
            'core': {'path': str(core), 'sha256': file_digest(core)},
            'files': [{'path': str(p), 'sha256': file_digest(p)} for p in files], 'tools': {}}
    path = tmp_path/'candidate.json'; path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match='REVIEWED_ROUTER_SCRIPT_REQUIRED'):
        load_candidate(path)
