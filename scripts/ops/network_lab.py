"""离线真实网络实验。packet namespace不代表家庭/客户端或真实地区证明。"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import ipaddress
import signal
import socket
import socketserver
import struct
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.ops.evidence import canonical_bytes, private_path, private_write

CONTRACT = json.loads((ROOT/'fixtures/v2_ops/lab_cases.json').read_text(encoding='utf-8'))
REQUIRED_CASES = tuple(CONTRACT['required_cases'])
# 由已核验NAS备份/本地解包依赖产生；候选不能自行扩大可执行文件信任集。
TRUSTED_BINARY_SHA = {
    'core': 'e1140de751b2848973350edcf0ba32d37a1a8ea5833019d8eb6af67151ed4f7a',
    'nft': '7b3efd79bd3a70d72275b7bbfe19f2234a837968a3c0ad5528126a396a00d42f',
    'tcpdump': 'b19250abc948f03f637ecf8845114ee03132ad0ce12526c180388b2ae6680fd3',
    'ash': 'df12634c17fcdca839ae5dc47d7627b7558511f7645de7c99ccf097a0f28ed5b',
    'ip': '2829deca72cff655d6d1290646abb9cc829da2e2db615eec8bc0ccd283acf3a7',
    'unshare': '41c65e55107cbbb1a1f6994784a938dd7dbbe255d1fea6b7a58ec96eabe382ef',
}
TRUSTED_LIBRARY_DIR = Path('/home/jonny/.cache/magicpanel-network-lab/root/usr/lib/x86_64-linux-gnu')
TRUSTED_LIBRARY_TREE_SHA = 'a8fde89c781b8568af48c2478ad91bb132c39544a9631be8c63c0a46915882b3'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def trusted_binary(kind, filename):
    code = 'TRUSTED_CORE_REQUIRED' if kind == 'core' else 'TRUSTED_TOOL_REQUIRED'
    path = Path(filename)
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(code)
    try:
        if not path.is_file() or file_digest(path) != TRUSTED_BINARY_SHA[kind]:
            raise ValueError(code)
    except (OSError, KeyError):
        raise ValueError(code) from None
    return str(path)


def trusted_process_env():
    directory = TRUSTED_LIBRARY_DIR
    if not directory.is_dir() or any(part.is_symlink() for part in (directory, *directory.parents)):
        raise ValueError('TRUSTED_LIBRARIES_REQUIRED')
    entries = []
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() and (not path.is_file() or not path.resolve().is_relative_to(directory)):
            raise ValueError('TRUSTED_LIBRARIES_REQUIRED')
        if path.is_file():
            entries.append((str(path.relative_to(directory)),
                            path.readlink().as_posix() if path.is_symlink() else file_digest(path)))
    actual = hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()
    if actual != TRUSTED_LIBRARY_TREE_SHA:
        raise ValueError('TRUSTED_LIBRARIES_REQUIRED')
    return {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'LD_LIBRARY_PATH': str(directory)}


def check_node_isolation_cases(cases: dict) -> list[str]:
    errors = []
    for name in ('all_nodes_failed_core_alive', 'all_nodes_slow_core_alive'):
        item = cases.get(name, {})
        if item.get('core_alive') is not True or any(item.get(k) != 'passed' for k in ('cn_cold_dns', 'cn_new_connection')):
            errors.append(f'CN_ISOLATION_FAILED:{name}')
    return errors


def consume_google_trace(trace: dict) -> list[str]:
    """校验02输出，不生成选路计划；未知/陈旧/缺候选不能证明耗尽。"""
    errors = []
    chosen = trace.get('chosen_tier')
    tiers = ('US', 'SG', 'JP')
    if chosen not in (*tiers, 'UNAVAILABLE', 'REJECT'):
        errors.append('GOOGLE_INVALID_CHOICE')
    if trace.get('core_healthy') and str(trace.get('gateway_mode', '')).lower() in ('basic', 'basic_wan'):
        errors.append('BUSINESS_FAILURE_IS_NOT_CORE_FAILURE')
    if not trace.get('scope_sha') or trace.get('scope_sha') != trace.get('evidence_scope_sha') or trace.get('revision') != trace.get('evidence_revision'):
        errors.append('GOOGLE_EVIDENCE_STALE')
    for key in ('recursive_leaves', 'provider_leaves'):
        if any(str(leaf).upper() in ('DIRECT', 'COMPATIBLE') for leaf in trace.get(key, [])):
            errors.append('GOOGLE_DIRECT_LEAF')
    before = tiers[:tiers.index(chosen)] if chosen in tiers else tiers
    for tier in before:
        values = trace.get(tier.lower(), [])
        eligible = trace.get('eligible', {}).get(tier)
        actual = [v.get('node_key') for v in values]
        if (eligible is None or len(actual) != len(set(actual)) or set(actual) != set(eligible)
                or any(v.get('state') != 'failed' or v.get('fresh') is not True for v in values)):
            errors.append('TIER_EXHAUSTION_UNPROVEN')
    if chosen in tiers and not any(v.get('state') == 'available' and v.get('fresh') is True for v in trace.get(chosen.lower(), [])):
        errors.append('CHOSEN_TIER_UNPROVEN')
    return sorted(set(errors))


def certify_fault_report(report: dict, requested_scope: dict) -> list[str]:
    errors = []
    if report.get('source_kind') not in ('packet_namespace', 'real_client'):
        errors.append('REAL_PACKET_EVIDENCE_REQUIRED')
    for key in ('scope_sha', 'candidate_sha'):
        if not requested_scope.get(key) or report.get(key) != requested_scope[key]:
            errors.append(f'{key.upper()}_MISMATCH')
    if not report.get('core_sha') or not report.get('core_version'):
        errors.append('REAL_CORE_REQUIRED')
    if report.get('host_before') != report.get('host_after') or not report.get('host_before'):
        errors.append('HOST_STATE_CHANGED_OR_UNPROVEN')
    if report.get('cn_failed', 1) != 0:
        errors.append('CN_REGRESSION')
    if report.get('policy') != CONTRACT:
        errors.append('POLICY_REVISION_MISMATCH')
    cases = report.get('cases', {})
    errors.extend(check_node_isolation_cases(cases))
    for name in REQUIRED_CASES:
        item = cases.get(name)
        if not isinstance(item, dict):
            errors.append(f'CASE_MISSING:{name}')
            continue
        if item.get('status') != 'passed':
            errors.append(f'CASE_NOT_PASSED:{name}')
        valid_evidence = item.get('candidate_sha') == report.get('candidate_sha')
        evidence_root = Path(report.get('evidence_root', ''))
        for kind in ('packet', 'runtime'):
            path = evidence_root/str(item.get(kind+'_path', ''))
            try:
                valid_evidence = (valid_evidence and evidence_root.is_absolute() and path.resolve().is_relative_to(evidence_root.resolve())
                                  and path.is_file() and not path.is_symlink() and file_digest(path) == item.get(kind+'_sha'))
            except (OSError, ValueError):
                valid_evidence = False
        if valid_evidence:
            metadata = {'packet_sha', 'runtime_sha', 'candidate_sha', 'packet_path', 'runtime_path'}
            try:
                recorded = json.loads((evidence_root/item['runtime_path']).read_text(encoding='utf-8'))
                valid_evidence = recorded == {key: value for key, value in item.items() if key not in metadata}
            except (OSError, ValueError, TypeError):
                valid_evidence = False
        if not valid_evidence:
            errors.append(f'CASE_EVIDENCE_REQUIRED:{name}')
        if name in ('core_stop', 'core_kill', 'core_hang', 'stale_redirect', 'fw4_reload'):
            if item.get('owner_withdraw_ms', 8001) > 8000:
                errors.append(f'OWNER_DEADLINE:{name}')
            if item.get('cn_recovered_ms', 10001) > 10000:
                errors.append(f'CN_DEADLINE:{name}')
    if not report.get('google_traces'):
        errors.append('PLANNER_TRACE_REQUIRED')
    for trace in report.get('google_traces', []):
        errors.extend(consume_google_trace(trace))
    errors.extend(report.get('blockers', []))
    return sorted(set(errors))


def load_candidate(path: Path) -> dict:
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    allowed = {'schema', 'role', 'scope', 'core', 'files', 'profile', 'google_traces',
               'dns_bundle', 'out_private', 'tools', 'predecessor', 'coverage'}
    if (not isinstance(raw, dict) or raw.get('schema') != 1 or raw.get('role') != 'offline_lab'
            or set(raw) - allowed or not isinstance(raw.get('scope'), dict)):
        raise ValueError('CANDIDATE_SCHEMA')
    if raw.get('profile') != 'linux-redirect-tproxy-dualstack-v1':
        raise ValueError('CANDIDATE_PROFILE')
    for item in [raw.get('core', {}), *raw.get('files', [])]:
        if set(item) != {'path', 'sha256'} or not Path(item['path']).is_absolute() or file_digest(item['path']) != item['sha256']:
            raise ValueError('CANDIDATE_HASH_MISMATCH')
    required = {'apply_bundle.sh', 'gateway_watch.sh', 'rollback_bundle.sh', 'dns_watch.sh',
                'guard_common.sh', 'guard_state.sh', 'magicpanel-gateway-watch.init', 'magicpanel-dns-watch.init'}
    names = [Path(item['path']).name for item in raw.get('files', [])]
    if set(names) != required or len(names) != len(required):
        raise ValueError('CANDIDATE_SCRIPTS_REQUIRED')
    trusted_binary('core', raw['core']['path'])
    for item in raw['files']:
        supplied = Path(os.path.abspath(item['path']))
        expected = ROOT/'ops/router'/supplied.name
        if supplied != expected or any(part.is_symlink() for part in (supplied, *supplied.parents)):
            raise ValueError('REVIEWED_ROUTER_SCRIPT_REQUIRED')
    if not {'nft', 'tcpdump'} <= set(raw.get('tools', {})) <= {'nft', 'tcpdump', 'ash'}:
        raise ValueError('TRUSTED_TOOL_REQUIRED')
    for kind, filename in raw['tools'].items():
        trusted_binary(kind, filename)
    raw['harness_sha'] = file_digest(Path(__file__))
    raw['contract_sha'] = file_digest(ROOT/'fixtures/v2_ops/lab_cases.json')
    raw['tool_shas'] = {key: file_digest(path) for key, path in raw.get('tools', {}).items()}
    raw['library_tree_sha'] = TRUSTED_LIBRARY_TREE_SHA
    raw['candidate_sha'] = digest(raw)
    return raw


def run_lab(case: str, *, prefix: str, candidate: Path, out_private: Path | None = None) -> dict:
    if not re.fullmatch(r'mpv2-[0-9a-f]{8}', prefix):
        raise ValueError('LAB_PREFIX_REQUIRED')
    if case != 'all' and case not in REQUIRED_CASES:
        raise ValueError('LAB_CASE_UNKNOWN')
    spec = load_candidate(candidate)
    if out_private is not None:
        spec['out_private'] = str(out_private)
    return _run_isolated(case, prefix, spec)


def _run_isolated(case, prefix, spec):
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('LINUX_ROOT_NAMESPACE_REQUIRED')
    out = private_path(Path(spec['out_private']), create=True)
    # 全新目录避免把旧结果误作本轮证据。
    run_dir = out / prefix
    if run_dir.exists() or run_dir.is_symlink():
        raise ValueError('LAB_RUN_ALREADY_EXISTS')
    run_dir.mkdir(mode=0o700)
    run_dir = private_path(run_dir)
    spec['run_dir'] = str(run_dir)
    spec['parent_netns'] = os.readlink('/proc/self/ns/net')
    spec['parent_mountns'] = os.readlink('/proc/self/ns/mnt')
    spec['prefix'] = prefix
    before = host_snapshot(spec)
    private = run_dir/'worker-input.json'
    private_write(private, canonical_bytes(spec))
    command = [trusted_binary('unshare', '/usr/bin/unshare'), '--mount', '--net', '--pid', '--fork', '--mount-proc',
               sys.executable, str(Path(__file__).resolve()), '_worker',
               '--case', case, '--candidate', str(private)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600, env=trusted_process_env())
        if result.returncode:
            private_write(run_dir/'worker-error.txt', result.stderr[-8000:].encode('utf-8'))
        report_file = run_dir/'packet-report.json'
        report = json.loads(report_file.read_text()) if report_file.exists() else {
            'source_kind': 'packet_namespace', 'cases': {}, 'blockers': ['NAMESPACE_WORKER_FAILED']}
    finally:
        after = host_snapshot(spec)
    report.update(host_before=before, host_after=after, scope_sha=digest(spec['scope']),
                  candidate_sha=spec['candidate_sha'])
    report['certification_errors'] = certify_fault_report(report, {
        'scope_sha': digest(spec['scope']), 'candidate_sha': spec['candidate_sha']})
    report['production_ready'] = False
    private_write(run_dir/'report.json', canonical_bytes(report))
    return report


def command(argv, **kwargs):
    return subprocess.run(list(map(str, argv)), check=True, capture_output=True, text=True, **kwargs)


def host_snapshot(spec):
    nft = trusted_binary('nft', spec.get('tools', {}).get('nft', ''))
    ip = trusted_binary('ip', '/usr/bin/ip')
    environment = trusted_process_env()
    values = {}
    for name, argv in {
        'v4_routes': [ip, '-4', 'route', 'show', 'table', 'all'],
        'v6_routes': [ip, '-6', 'route', 'show', 'table', 'all'],
        'v4_rules': [ip, '-4', 'rule', 'show'], 'v6_rules': [ip, '-6', 'rule', 'show'],
        'namespaces': [ip, 'netns', 'list'],
        'nft': [nft, '-s', 'list', 'ruleset'],
    }.items():
        values[name] = command(argv, env=environment).stdout
    values['forward4'] = Path('/proc/sys/net/ipv4/ip_forward').read_text()
    values['forward6'] = Path('/proc/sys/net/ipv6/conf/all/forwarding').read_text()
    return {key: hashlib.sha256(value.encode()).hexdigest() for key, value in values.items()}


class Network:
    def __init__(self, prefix, spec):
        self.prefix, self.spec = prefix, spec
        self.names = {name: prefix+'-'+name for name in ('c', 'g', 'o', 'us', 'sg', 'jp')}
        self.processes = []
        self.files = []
        self.out = Path(spec['run_dir'])

    def inside(self, ns, argv, **kw):
        return command(['ip', 'netns', 'exec', self.names[ns], *argv], **kw)

    def spawn(self, ns, argv, name):
        log = (self.out/f'{name}.log').open('ab')
        self.files.append(log)
        proc = subprocess.Popen(['ip', 'netns', 'exec', self.names[ns], *map(str, argv)],
                                stdout=log, stderr=log, start_new_session=True)
        self.processes.append(proc)
        return proc

    def pair(self, left, right, lname, rname, v4left, v4right, v6left, v6right):
        a, b = 'a'+uuid.uuid4().hex[:8], 'b'+uuid.uuid4().hex[:8]
        command(['ip', 'link', 'add', a, 'type', 'veth', 'peer', 'name', b])
        for ns, link, name, v4, v6 in ((left, a, lname, v4left, v6left), (right, b, rname, v4right, v6right)):
            command(['ip', 'link', 'set', link, 'netns', self.names[ns]])
            self.inside(ns, ['ip', 'link', 'set', link, 'name', name])
            self.inside(ns, ['ip', 'addr', 'add', v4, 'dev', name])
            self.inside(ns, ['ip', '-6', 'addr', 'add', v6, 'dev', name, 'nodad'])
            self.inside(ns, ['ip', 'link', 'set', name, 'up'])

    def __enter__(self):
        command(['mount', '--make-rprivate', '/'])
        command(['mount', '-t', 'tmpfs', '-o', 'mode=755', 'tmpfs', '/run'])
        Path('/run/netns').mkdir()
        try:
            for name in self.names.values():
                command(['ip', 'netns', 'add', name])
                command(['ip', 'netns', 'exec', name, 'ip', 'link', 'set', 'lo', 'up'])
            self.pair('c', 'g', 'eth0', 'lan0', '192.0.2.2/24', '192.0.2.1/24', '2001:db8:1::2/64', '2001:db8:1::1/64')
            self.pair('g', 'o', 'wan0', 'eth0', '198.51.100.1/24', '198.51.100.2/24', '2001:db8:2::1/64', '2001:db8:2::2/64')
            for index, region in enumerate(('us', 'sg', 'jp')):
                self.pair('g', region, f'p{index}', 'eth0', f'203.0.113.{index*4+1}/30', f'203.0.113.{index*4+2}/30',
                          f'2001:db8:{index+3}::1/64', f'2001:db8:{index+3}::2/64')
                self.inside(region, ['ip', 'route', 'add', 'default', 'via', f'203.0.113.{index*4+1}'])
                self.inside(region, ['ip', '-6', 'route', 'add', 'default', 'via', f'2001:db8:{index+3}::1'])
            for ns, v4, v6 in (('c', '192.0.2.1', '2001:db8:1::1'), ('o', '198.51.100.1', '2001:db8:2::1')):
                self.inside(ns, ['ip', 'route', 'add', 'default', 'via', v4])
                self.inside(ns, ['ip', '-6', 'route', 'add', 'default', 'via', v6])
            self.inside('g', ['sysctl', '-w', 'net.ipv4.ip_forward=1', 'net.ipv6.conf.all.forwarding=1'])
            self.inside('g', ['sysctl', '-w', 'net.ipv4.conf.all.rp_filter=0', 'net.ipv4.conf.lan0.rp_filter=0'])
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *args):
        for proc in reversed(self.processes):
            if proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGCONT)
                    os.killpg(proc.pid, signal.SIGTERM)
        for proc in self.processes:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        for stream in self.files:
            stream.close()
        for name in reversed(list(self.names.values())):
            subprocess.run(['ip', 'netns', 'del', name], capture_output=True)


def recv_exact(sock, size):
    result = b''
    while len(result) < size:
        block = sock.recv(size - len(result))
        if not block:
            raise ConnectionError('short socket read')
        result += block
    return result


def socks_address(sock, atyp):
    if atyp == 1:
        host = socket.inet_ntop(socket.AF_INET, recv_exact(sock, 4))
    elif atyp == 4:
        host = socket.inet_ntop(socket.AF_INET6, recv_exact(sock, 16))
    elif atyp == 3:
        host = recv_exact(sock, recv_exact(sock, 1)[0]).decode()
        host = '198.51.100.2' if host.endswith('.fixture.invalid') else host
    else:
        raise ValueError('address type')
    return host, struct.unpack('!H', recv_exact(sock, 2))[0]


def serve_fixture(kind, port, directory):
    """仅提供文档网段受控原点/DNS/代理，不消费真实节点凭据。"""
    import select
    directory = Path(directory)

    class HTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if kind == 'health':
                body = b'DNS_OK'
            else:
                host = self.headers.get('Host', '')
                body = (b'READY' if self.path == '/ready' else
                        json.dumps({'host': host, 'path': self.path, 'peer': self.client_address[0],
                                    'result': 'CN_OK' if host.startswith(('cn.', 'cn-cdn.')) else 'GOOGLE_FIXTURE'}).encode())
            self.send_response(503 if self.path == '/business-health' else 200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    if kind in ('origin', 'origin6', 'health'):
        cls = ThreadingHTTPServer
        if kind == 'origin6':
            class HTTP6(ThreadingHTTPServer):
                address_family = socket.AF_INET6
                def server_bind(self):
                    self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    super().server_bind()
            cls = HTTP6
        cls(('::' if kind == 'origin6' else '0.0.0.0', port), HTTP).serve_forever()
    elif kind in ('dns', 'udp', 'udp6'):
        sock = socket.socket(socket.AF_INET6 if kind == 'udp6' else socket.AF_INET, socket.SOCK_DGRAM)
        if kind == 'udp6':
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind(('::' if kind == 'udp6' else '0.0.0.0', port))
        while True:
            data, peer = sock.recvfrom(8192)
            if kind == 'dns':
                offset = 12
                while data[offset]:
                    offset += data[offset]+1
                offset += 1
                qtype = struct.unpack('!H', data[offset:offset+2])[0]
                question = data[12:offset+4]
                answer = ipaddress.ip_address('2001:db8:2::2' if qtype == 28 else '198.51.100.2').packed
                response = data[:2]+b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00'+question
                response += b'\xc0\x0c'+struct.pack('!HHIH', qtype, 1, 0, len(answer))+answer
            else:
                response = json.dumps({'peer': peer[0], 'payload': data.hex()}).encode()
            sock.sendto(response, peer)
    elif kind == 'opaque':
        class Opaque(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                payload = self.request.recv(128)
                self.request.sendall(json.dumps({'peer': self.client_address[0], 'payload': payload.hex()}).encode())
        class OpaqueServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        OpaqueServer(('0.0.0.0', port), Opaque).serve_forever()
    elif kind == 'socks':
        class Proxy(socketserver.BaseRequestHandler):
            def handle(self):
                client = self.request
                client.settimeout(10)
                try:
                    ver, n = recv_exact(client, 2)
                    recv_exact(client, n)
                    client.sendall(b'\x05\x00')
                    ver, op, _, atyp = recv_exact(client, 4)
                    target = socks_address(client, atyp)
                    if op == 1:
                        upstream = socket.create_connection(target, 2)
                        client.sendall(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
                        with upstream:
                            while True:
                                ready, _, _ = select.select([client, upstream], [], [], 10)
                                if not ready:
                                    return
                                for source in ready:
                                    data = source.recv(65536)
                                    if not data:
                                        return
                                    (upstream if source is client else client).sendall(data)
                    elif op == 3:
                        relay = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        relay.bind(('0.0.0.0', 0))
                        addr = b'\0'*4
                        client.sendall(b'\x05\x00\x00\x01'+addr+struct.pack('!H', relay.getsockname()[1]))
                        with relay:
                            while True:
                                ready, _, _ = select.select([client, relay], [], [], 10)
                                if client in ready or not ready:
                                    return
                                raw, sender = relay.recvfrom(8192)
                                # SOCKS UDP: 同一请求只允许一个文档网段原点。
                                from io import BytesIO
                                class Reader:
                                    def __init__(self, data): self.stream = BytesIO(data)
                                    def recv(self, n): return self.stream.read(n)
                                reader = Reader(raw[4:])
                                dest = socks_address(reader, raw[3])
                                payload = reader.stream.read()
                                family = socket.AF_INET6 if ':' in dest[0] else socket.AF_INET
                                with socket.socket(family, socket.SOCK_DGRAM) as upstream:
                                    upstream.settimeout(2)
                                    upstream.sendto(payload, dest)
                                    reply, _ = upstream.recvfrom(8192)
                                relay.sendto(raw[:len(raw)-len(payload)]+reply, sender)
                except (OSError, ValueError, ConnectionError):
                    return
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        Server(('0.0.0.0', port), Proxy).serve_forever()


def probe_client(kind, host, port, name):
    started = time.monotonic()
    result = {'passed': False, 'kind': kind}
    try:
        family = socket.AF_INET6 if ':' in host else socket.AF_INET
        if kind == 'dns':
            queryid = os.urandom(2)
            labels = b''.join(bytes([len(p)])+p.encode() for p in name.split('.'))+b'\0'
            query = queryid+b'\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'+labels+b'\x00\x01\x00\x01'
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.settimeout(.7); sock.bind(('::' if family == socket.AF_INET6 else '0.0.0.0', 0))
                result['source_port'] = sock.getsockname()[1]
                sock.sendto(query, (host, port)); response, _ = sock.recvfrom(8192)
                result['passed'] = response[:2] == queryid and response[-4:] == socket.inet_aton('198.51.100.2')
        elif kind == 'udp':
            payload = b'opaque-'+os.urandom(12)
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.settimeout(.8); sock.bind(('::' if family == socket.AF_INET6 else '0.0.0.0', 0))
                result['source_port'] = sock.getsockname()[1]
                sock.sendto(payload, (host, port)); response, _ = sock.recvfrom(8192)
                result['response'] = json.loads(response)
                result['passed'] = result['response']['payload'] == payload.hex()
        elif kind == 'opaque':
            payload = b'opaque-without-domain'
            with socket.create_connection((host, port), .8) as sock:
                result['source_port'] = sock.getsockname()[1]
                sock.sendall(payload)
                result['response'] = json.loads(sock.recv(8192))
                result['passed'] = result['response']['payload'] == payload.hex()
        else:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(.8); sock.bind(('::' if family == socket.AF_INET6 else '0.0.0.0', 0))
                result['source_port'] = sock.getsockname()[1]
                sock.connect((host, port))
                sock.sendall(f'GET /{uuid.uuid4().hex} HTTP/1.0\r\nHost: {name}\r\n\r\n'.encode())
                response = b''
                while True:
                    block = sock.recv(8192)
                    if not block: break
                    response += block
                result['response'] = json.loads(response.split(b'\r\n\r\n', 1)[1])
                result['passed'] = result['response']['host'] == name
    except (OSError, ValueError, IndexError):
        result['error'] = 'LOCAL_PROBE_FAILED'
    result['elapsed_ms'] = round((time.monotonic()-started)*1000, 2)
    print(json.dumps(result))


def core_config():
    return {
        'mixed-port': 7890, 'redir-port': 7892, 'tproxy-port': 7895,
        'allow-lan': True, 'bind-address': '*', 'mode': 'rule', 'ipv6': True,
        'external-controller': '127.0.0.1:9090', 'log-level': 'info',
        'profile': {'store-selected': False},
        'hosts': {'ready.lab.invalid': '198.51.100.2'},
        'dns': {'enable': False},
        'sniffer': {'enable': True, 'force-dns-mapping': True, 'parse-pure-ip': True,
                    'override-destination': False, 'sniff': {'HTTP': {'ports': [8080]}}},
        'proxies': [{'name': region.upper(), 'type': 'socks5', 'server': f'203.0.113.{i*4+2}',
                     'port': 1080, 'udp': True} for i, region in enumerate(('us', 'sg', 'jp'))],
        'proxy-groups': [{'name': 'LAB', 'type': 'select', 'proxies': ['US', 'SG', 'JP', 'REJECT']},
                         {'name': 'native-health', 'type': 'fallback', 'proxies': ['US', 'SG', 'JP'],
                          'url': 'http://198.51.100.2:8080/ready', 'interval': 600, 'lazy': True}],
        'rules': ['DOMAIN,ready.lab.invalid,DIRECT', 'DOMAIN,cn.fixture.invalid,DIRECT',
                  'DOMAIN,cn-cdn.fixture.invalid,DIRECT', 'MATCH,LAB'],
    }


def packet_worker(case, spec):
    if (sys.platform != 'linux' or os.getpid() != 1
            or os.readlink('/proc/self/ns/net') == spec.get('parent_netns')
            or os.readlink('/proc/self/ns/mnt') == spec.get('parent_mountns')):
        raise ValueError('NESTED_NAMESPACE_REQUIRED')
    os.environ['MPV2_LAB_PARENT_NETNS'] = spec['parent_netns']
    os.umask(0o077)
    out = private_path(Path(spec['run_dir']))
    report = {'schema': 1, 'source_kind': 'packet_namespace', 'scope_sha': digest(spec['scope']),
              'candidate_sha': spec['candidate_sha'], 'core_sha': spec['core']['sha256'],
              'policy': CONTRACT, 'cn_failed': 0, 'cases': {},
              'virtual_regions_are_path_labels': True, 'google_traces': spec.get('google_traces', []),
              'production_ready': False, 'blockers': [], 'evidence_root': str(out),
              'harness_sha': spec.get('harness_sha'), 'contract_sha': spec.get('contract_sha')}
    binary = trusted_binary('core', spec['core']['path'])
    report['core_version'] = command([binary, '-v']).stdout.strip()
    selected = REQUIRED_CASES if case == 'all' else (case,)
    for name in selected:
        report['cases'][name] = {'status': 'pending', 'reason': 'NOT_EXECUTED'}
    module = str(Path(__file__).resolve())
    script_dir = out/'scripts'; script_dir.mkdir()
    for item in spec['files']:
        target = script_dir/Path(item['path']).name
        target.write_bytes(Path(item['path']).read_bytes())
    if spec.get('tools', {}).get('ash'):
        (script_dir/'sh').symlink_to(spec['tools']['ash'])
        os.environ['PATH'] = str(script_dir)+os.pathsep+os.environ['PATH']
    try:
        with Network(spec['prefix'], spec) as net:
            bundle = out/'bundle'; bundle.mkdir()
            netns = net.inside('g', ['readlink', '/proc/self/ns/net']).stdout.strip()
            mountns = net.inside('g', ['readlink', '/proc/self/ns/mnt']).stdout.strip()
            (bundle/'owner.env').write_text('\n'.join([
                'role=packet_namespace', 'owner='+spec['prefix'].replace('-', '_'), 'netns='+netns,
                'mountns='+mountns, 'parent_netns='+spec['parent_netns'],
                'parent_mountns='+spec['parent_mountns'], 'predecessor=empty',
                'dns_adapter=fixture-http-v1', '']) )
            os.environ['MPV2_NFT'] = spec['tools']['nft']
            for kind, port in (('origin', 8080), ('origin6', 8080), ('udp', 8081), ('udp6', 8081), ('opaque', 8443)):
                net.spawn('o', [sys.executable, module, '_serve', kind, str(port), str(out)], kind)
            proxies = [net.spawn(region, [sys.executable, module, '_serve', 'socks', '1080', str(out)], region)
                       for region in ('us', 'sg', 'jp')]
            dnsprocs = []
            for port in (1053, 5353):
                dnsprocs.append(net.spawn('g', [sys.executable, module, '_serve', 'dns', str(port), str(out)], f'dns{port}'))
            health = [net.spawn('g', [sys.executable, module, '_serve', 'health', str(port), str(out)], f'health{port}')
                      for port in (18053, 18054, 18055)]
            config = out/'config.json'; config.write_text(json.dumps(core_config()))
            command([binary, '-t', '-d', str(out/'core'), '-f', str(config)])
            core = net.spawn('g', [binary, '-d', str(out/'core'), '-f', str(config)], 'core')
            time.sleep(.8)
            net.inside('g', ['sh', str(script_dir/'apply_bundle.sh'), str(bundle)])
            watch = net.spawn('g', ['sh', str(script_dir/'gateway_watch.sh'), str(bundle)], 'gateway-watch')
            dnswatch = net.spawn('g', ['sh', str(script_dir/'dns_watch.sh'), str(bundle)], 'dns-watch')
            time.sleep(.6)
            pcap = out/'packets.pcap'
            capture = net.spawn('g', [spec['tools']['tcpdump'], '-Z', 'root', '-U', '-s', '0', '-i', 'any', '-w', str(pcap)], 'tcpdump')
            time.sleep(.25)
            owner = spec['prefix'].replace('-', '_')
            evidence = []

            def probe(kind='http', host='198.51.100.2', port=8080, name='cn.fixture.invalid'):
                result = net.inside('c', [sys.executable, module, '_probe', kind, host, str(port), name])
                return json.loads(result.stdout)

            def passed(name, samples, **extra):
                if name not in selected: return
                okay = all(s.get('passed') is True for s in samples)
                item = {'status': 'observed' if okay else 'failed', 'samples': samples, **extra}
                report['cases'][name] = item
                evidence.append((name, item))

            def scoped(name, reason):
                if name in selected:
                    report['cases'][name] = {'status': 'pending', 'reason': reason}

            # 同IP、同端口域名可见时必须方向相反；不可见的对照另列停止线。
            cn = probe(); foreign = probe(name='google.fixture.invalid')
            cn['passed'] = cn['passed'] and cn.get('response', {}).get('peer') == '198.51.100.1'
            foreign['passed'] = foreign['passed'] and foreign.get('response', {}).get('peer') == '203.0.113.2'
            passed('shared_ip', [cn, foreign])
            passed('cn_overseas_cdn', [probe(name='cn-cdn.fixture.invalid')])
            unknown = probe(name='unknown.fixture.invalid')
            unknown['passed'] = unknown['passed'] and unknown.get('response', {}).get('peer') == '203.0.113.2'
            passed('unknown_domain', [unknown])
            if spec.get('google_traces'):
                trace_samples = []
                for trace in spec['google_traces']:
                    errors = consume_google_trace(trace)
                    if errors:
                        trace_samples.append({'passed': False, 'errors': errors}); continue
                    tier = trace['chosen_tier']
                    selected_tier = tier if tier in ('US', 'SG', 'JP') else 'REJECT'
                    net.inside('g', ['curl', '--noproxy', '*', '-fsS', '--max-time', '1', '-X', 'PUT',
                                     '-H', 'Content-Type: application/json', '--data', json.dumps({'name': selected_tier}),
                                     'http://127.0.0.1:9090/proxies/LAB'])
                    readback = json.loads(net.inside('g', ['curl', '--noproxy', '*', '-fsS', '--max-time', '1',
                                                         'http://127.0.0.1:9090/proxies/LAB']).stdout)
                    observed = probe(name='google.fixture.invalid')
                    expected = {'US': '203.0.113.2', 'SG': '203.0.113.6', 'JP': '203.0.113.10'}.get(tier)
                    okay = (observed['passed'] and observed.get('response', {}).get('peer') == expected) if expected else not observed['passed']
                    trace_samples.append({'passed': okay and readback.get('now') == selected_tier,
                                          'chosen_tier': tier, 'observed': observed, 'readback': readback.get('now')})
                passed('google_tiers', trace_samples, planner_implementation='02 external input; no ranking in lab')
                net.inside('g', ['curl', '--noproxy', '*', '-fsS', '--max-time', '1', '-X', 'PUT',
                                 '-H', 'Content-Type: application/json', '--data', '{"name":"US"}',
                                 'http://127.0.0.1:9090/proxies/LAB'])
            delay = json.loads(net.inside('g', ['curl', '--noproxy', '*', '-fsS', '--max-time', '2',
                                               'http://127.0.0.1:9090/proxies/US/delay?timeout=1000&url=http%3A%2F%2F198.51.100.2%3A8080%2Fready']).stdout)
            business = net.inside('g', ['curl', '--noproxy', '', '-sS', '--max-time', '2', '-x', 'http://127.0.0.1:7890',
                                        '-o', '/dev/null', '-w', '%{http_code}', 'http://198.51.100.2:8080/business-health']).stdout
            passed('core_health_semantics', [{'passed': isinstance(delay.get('delay'), (int, float)) and business == '503',
                                              'native_delay_ms': delay.get('delay'), 'business_http_status': business}],
                   coverage='native health can succeed while business fails; business qualification must come from 02')
            opaque_cn = probe('opaque', '198.51.100.2', 8443, '')
            opaque_foreign = probe('opaque', '198.51.100.2', 8443, '')
            opaque_cn['expected_peer'] = '198.51.100.1'
            opaque_foreign['expected_peer'] = '203.0.113.2'
            for sample in (opaque_cn, opaque_foreign):
                sample['passed'] = sample['passed'] and sample.get('response', {}).get('peer') == sample['expected_peer']
            passed('ech_opaque', [opaque_cn, opaque_foreign],
                   reason='OPAQUE_SHARED_DESTINATION_HAS_NO_DOMAIN_SIGNAL',
                   coverage='opaque bytes, not an emulated TLS/ECH protocol or decrypted hidden SNI')
            passed('ipv6_tcp', [probe(host='2001:db8:2::2')])
            for name, address in (('ipv4_udp', '198.51.100.2'), ('ipv6_udp', '2001:db8:2::2')):
                sample = probe('udp', address, 8081, '')
                sample['passed'] = sample['passed'] and sample.get('response', {}).get('peer') in ('203.0.113.2', '2001:db8:3::2')
                passed(name, [sample])
            dns = lambda: probe('dns', '192.0.2.1', 53, uuid.uuid4().hex+'.cn.fixture.invalid')
            with ThreadPoolExecutor(max_workers=8) as executor:
                cold = list(executor.map(lambda _: dns(), range(8)))
            passed('cold_dns_concurrent', cold)
            passed('hot_dns', [probe('dns', '192.0.2.1', 53, 'cn.fixture.invalid') for _ in range(2)])
            if 'hot_dns' in selected:
                report['cases']['hot_dns'].update(status='pending', reason='REAL_DNS_CACHE_ADAPTER_REQUIRED')
            passed('client_own_dns', [probe('dns', '198.51.100.2', 53, 'unknown.fixture.invalid')],
                   coverage='plaintext port53 interception only; encrypted external DNS pending')
            # 每个节点故障期间同时产生新源端口与唯一DNS标签。
            for name, sig in (('all_nodes_slow_core_alive', signal.SIGSTOP),
                              ('all_nodes_failed_core_alive', signal.SIGTERM)):
                for proc in proxies: os.kill(proc.pid, sig)
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(dns), executor.submit(probe),
                               executor.submit(probe, 'http', '198.51.100.2', 8080, 'google.fixture.invalid')]
                    results = [f.result() for f in futures]
                control = net.inside('g', ['curl', '--noproxy', '*', '-fsS', '--max-time', '0.5', 'http://127.0.0.1:9090/version'])
                state = (bundle/'state/gateway.state').read_text()
                results[1]['passed'] = results[1]['passed'] and 'mode=MANAGED\n' in state and not results[2]['passed']
                passed(name, results[:2], core_alive=bool(control.stdout), gateway_managed='mode=MANAGED\n' in state,
                       cn_cold_dns='passed' if results[0]['passed'] else 'failed',
                       cn_new_connection='passed' if results[1]['passed'] else 'failed',
                       overseas_failed=not results[2]['passed'])
                if sig == signal.SIGSTOP:
                    for proc in proxies: os.kill(proc.pid, signal.SIGCONT)
                else:
                    proxies = [net.spawn(region, [sys.executable, module, '_serve', 'socks', '1080', str(out)], region+'-restart')
                               for region in ('us', 'sg', 'jp')]
                    time.sleep(.2)
            for name, indices in (('dns_trusted_single_failed', [1]), ('dns_trusted_both_failed', [1, 2]), ('agh_hang', [0])):
                for index in indices: os.kill(health[index].pid, signal.SIGSTOP)
                if name == 'agh_hang': os.kill(dnsprocs[0].pid, signal.SIGSTOP)
                began = time.monotonic(); recovered = None
                while time.monotonic()-began < 4:
                    sample = dns()
                    if sample['passed']: recovered = sample
                    statefile = bundle/'state/dns.state'
                    state = statefile.read_text() if statefile.exists() else ''
                    wanted = 'TRUSTED' if len(indices) == 1 and indices[0] == 1 else ('AGH_BYPASS' if indices == [0] else 'DNS_DEGRADED')
                    if 'mode='+wanted+'\n' in state and recovered: break
                    time.sleep(.1)
                elapsed = round((time.monotonic()-began)*1000)
                measured = recovered or {'passed': False}
                if name != 'dns_trusted_single_failed': measured['passed'] = measured['passed'] and elapsed <= 3000
                passed(name, [measured], transition_ms=elapsed,
                       component_scope='fixture DNS, not AGH/DoH adapter certification')
                for index in indices: os.kill(health[index].pid, signal.SIGCONT)
                if name == 'agh_hang': os.kill(dnsprocs[0].pid, signal.SIGCONT)
            # 每个核心故障重新加载独立守护状态；每轮仍从故障注入计时。
            for name, sig in (('core_stop', signal.SIGTERM), ('core_kill', signal.SIGKILL), ('core_hang', signal.SIGSTOP),
                              ('stale_redirect', signal.SIGTERM), ('fw4_reload', None)):
                os.killpg(watch.pid, signal.SIGTERM); watch.wait(timeout=3)
                (bundle/'state/gateway.state').unlink(missing_ok=True)
                (bundle/'state/gateway.lock').rmdir() if (bundle/'state/gateway.lock').exists() else None
                net.inside('g', ['sh', str(script_dir/'apply_bundle.sh'), str(bundle)])
                watch = net.spawn('g', ['sh', str(script_dir/'gateway_watch.sh'), str(bundle)], name+'-watch')
                time.sleep(.2)
                injected = time.monotonic(); removed = None; recovered = None; samples = []
                if sig: os.kill(core.pid, sig)
                else: net.inside('g', [spec['tools']['nft'], 'delete', 'table', 'inet', owner])
                while time.monotonic()-injected < 10:
                    table = subprocess.run(['ip', 'netns', 'exec', net.names['g'], spec['tools']['nft'], 'list', 'table', 'inet', owner], capture_output=True)
                    if (sig and table.returncode != 0) or (not sig and table.returncode == 0):
                        removed = removed if removed is not None else (time.monotonic()-injected)*1000
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        fdns = executor.submit(dns); fhttp = executor.submit(probe)
                        samples = [fdns.result(), fhttp.result()]
                    if removed is not None and all(s['passed'] for s in samples):
                        recovered = (time.monotonic()-injected)*1000; break
                    time.sleep(.05)
                passed(name, samples, owner_withdraw_ms=round(removed or 10001, 2),
                       cn_recovered_ms=round(recovered or 10001, 2), guard_alive=watch.poll() is None,
                       old_sessions_may_break=True)
                if sig == signal.SIGSTOP: os.kill(core.pid, signal.SIGCONT)
                elif sig:
                    core.wait(timeout=3)
                    core = net.spawn('g', [binary, '-d', str(out/'core'), '-f', str(config)], name+'-core-restart')
                time.sleep(.4)
            # 不缩短sealed的60秒冷却，真实等待并继续检测新端口国内连接。
            if 'guard_recovery' in selected:
                os.kill(core.pid, signal.SIGSTOP)
                until = time.monotonic()+9
                while time.monotonic() < until:
                    statefile = bundle/'state/gateway.state'
                    state = dict(line.split('=', 1) for line in statefile.read_text().splitlines())
                    if state['mode'] == 'BASIC_WAN': break
                    time.sleep(.1)
                changed = int(state['changed'])
                os.kill(core.pid, signal.SIGCONT)
                restored = None; early = False; samples = []
                until = time.monotonic()+65
                while time.monotonic() < until:
                    state = dict(line.split('=', 1) for line in statefile.read_text().splitlines())
                    if state['mode'] == 'MANAGED':
                        restored = int(state['changed'])-changed
                        early = restored < 60000
                        break
                    if not samples or len(samples) < 3:
                        samples.append(probe())
                    time.sleep(.3)
                samples.append({'passed': restored is not None and not early, 'cooldown_ms': restored,
                                'successful_probes': int(state['successes'])})
                passed('guard_recovery', samples, restored_after_ms=restored)
            # 负例实际发包，错误方案不能因新连接成功率平均值而通过。
            os.killpg(watch.pid, signal.SIGTERM); watch.wait(timeout=3)
            os.kill(core.pid, signal.SIGSTOP)
            net.inside('g', ['sh', str(script_dir/'apply_bundle.sh'), str(bundle)])
            for name in ('negative_core_direct_only', 'negative_dead_redirect'):
                sample = probe(); sample['expected_failure_observed'] = not sample['passed']; sample['passed'] = not sample['passed']
                passed(name, [sample])
            os.kill(core.pid, signal.SIGCONT)
            net.inside('g', ['sh', str(script_dir/'rollback_bundle.sh'), str(bundle)])
            rules = out/'negative.nft'
            rules.write_text(f'table inet {owner}_negative {{\n chain block {{\n type filter hook forward priority -200; policy drop;\n }}\n }}\n')
            net.inside('g', [spec['tools']['nft'], '-f', str(rules)])
            sample = probe(); sample['passed'] = not sample['passed']
            passed('negative_all_blocked', [sample])
            net.inside('g', [spec['tools']['nft'], 'delete', 'table', 'inet', owner+'_negative'])
            # IP集合提前直连导致同IP Google也直出。
            net.inside('g', ['sh', str(script_dir/'apply_bundle.sh'), str(bundle)])
            rules.write_text(f'add set inet {owner} blind_cn {{ type ipv4_addr; elements = {{ 198.51.100.2 }}; }}\n'
                             f'insert rule inet {owner} redirect4 ip daddr @blind_cn return\n')
            net.inside('g', [spec['tools']['nft'], '-f', str(rules)])
            blind = probe(name='google.fixture.invalid')
            blind['passed'] = blind['passed'] and blind.get('response', {}).get('peer') == '192.0.2.2'
            passed('negative_blind_ipset', [blind], coverage='shared destination bypass counterexample')
            if not spec.get('google_traces'):
                scoped('google_tiers', '02_PLANNER_TRACE_AND_EXECUTION_REQUIRED')
            scoped('guard_boot', 'PROCD_BOOT_ON_FIXED_OPENWRT_REQUIRED')
            scoped('old_conntrack', 'EXISTING_SESSION_AND_HOT_CACHE_MATRIX_REQUIRED')
            os.kill(capture.pid, signal.SIGINT); capture.wait(timeout=3)
            if not pcap.exists() or pcap.stat().st_size <= 24:
                report['blockers'].append('PCAP_EMPTY')
                for _, item in evidence:
                    if item['status'] == 'observed':
                        item['status'] = 'pending'; item['reason'] = 'PACKET_EVIDENCE_REQUIRED'
            else:
                packet_sha = file_digest(pcap)
                for name, item in evidence:
                    if item['status'] == 'observed': item['status'] = 'passed'
                    runtime = out/(name+'.runtime.json')
                    private_write(runtime, canonical_bytes(item))
                    item.update(packet_sha=packet_sha, runtime_sha=file_digest(runtime), candidate_sha=spec['candidate_sha'],
                                packet_path=pcap.name, runtime_path=runtime.name)
            report['cn_failed'] = sum(1 for name, item in report['cases'].items()
                                      if item.get('status') == 'failed' and not name.startswith('negative_'))
            report['blockers'].extend(['FIXED_R6S_CORE_PLUGIN_SCOPE_PENDING', 'REAL_AGH_DOH_BUNDLE_PENDING'])
    except Exception as exc:
        report['blockers'].append('PACKET_EXECUTION_FAILED:'+type(exc).__name__)
        private_write(out/'exception.txt', (str(exc)+'\n'+getattr(exc, 'stderr', '')).encode('utf-8'))
    finally:
        private_write(out/'packet-report.json', canonical_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    worker = sub.add_parser('_worker')
    worker.add_argument('--candidate', type=Path, required=True)
    worker.add_argument('--case', required=True)
    serve = sub.add_parser('_serve')
    serve.add_argument('kind'); serve.add_argument('port', type=int); serve.add_argument('directory')
    probe = sub.add_parser('_probe')
    probe.add_argument('kind'); probe.add_argument('host'); probe.add_argument('port', type=int); probe.add_argument('name')
    run = sub.add_parser('run')
    run.add_argument('--case', default='all'); run.add_argument('--prefix')
    run.add_argument('--candidate-manifest', type=Path, required=True)
    run.add_argument('--out-private', type=Path)
    args = parser.parse_args(argv)
    if args.operation == '_serve':
        if (sys.platform != 'linux' or not os.environ.get('MPV2_LAB_PARENT_NETNS')
                or os.readlink('/proc/self/ns/net') == os.environ['MPV2_LAB_PARENT_NETNS']):
            raise ValueError('NESTED_NAMESPACE_REQUIRED')
        serve_fixture(args.kind, args.port, args.directory)
    elif args.operation == '_probe':
        if (sys.platform != 'linux' or not os.environ.get('MPV2_LAB_PARENT_NETNS')
                or os.readlink('/proc/self/ns/net') == os.environ['MPV2_LAB_PARENT_NETNS']):
            raise ValueError('NESTED_NAMESPACE_REQUIRED')
        probe_client(args.kind, args.host, args.port, args.name)
    elif args.operation == '_worker':
        packet_worker(args.case, json.loads(args.candidate.read_text()))
    else:
        result = run_lab(args.case, prefix=args.prefix or 'mpv2-'+uuid.uuid4().hex[:8], candidate=args.candidate_manifest,
                         out_private=args.out_private)
        print(json.dumps({'source_kind': result['source_kind'], 'candidate_sha': result.get('candidate_sha'),
                          'cases': {k: v['status'] for k, v in result.get('cases', {}).items()},
                          'blockers': result.get('certification_errors'), 'production_ready': False}))
        return 42 if result.get('certification_errors') else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
