"""受限安全准备，不连接生产主机。"""
import copy
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def snapshot():
    return {
        "role": "router", "adapter": "openclash_v1", "phase": "PRE_NETWORK",
        "dns_sha": "a", "wan_lan_sha": "b", "udp_v6_cn_sha": "c", "core_pid": [42],
        "core_started_at": "fixture", "subscription_sha": "old", "geo_sha": "old",
        "firewall_sha": "fw", "routes_sha": "route", "forwarding_sha": "fwd",
        "connections_sha": "existing", "uci_pending": [], "updaters_running": False,
        "schedule_requires_reload": False,
        "uci": {"openclash.config": "openclash", "openclash.config.auto_update": "1",
                "openclash.config.geo_auto_update": "1", "openclash.config.enable": "1",
                "openclash.cfg0ab.config": "untouched",
                "openclash.cfg0abc": "config_subscribe",
                "openclash.cfg0abc.auto_update": "1"},
        "crontab": "0 4 * * * /usr/share/openclash/openclash.sh\n"
                   "*/5 * * * * /usr/local/sbin/openclash-health.sh\n"
                   "0 3 * * * echo /usr/share/openclash/openclash_geo.sh\n",
        "backup_components": {name: "fixture-private-data" for name in (
            "uci", "openclash", "agh", "dnsmasq", "crontab", "subscription_raw",
            "subscription_cache", "geo_versions", "firewall", "routes", "runtime")},
    }


class FixtureRunner:
    """模拟外部设备边界；写入真实本地文件，故障由设备快照表示。"""
    def __init__(self, root, *, drift=None, fail_freeze=False):
        self.root = root
        self.current = snapshot()
        self.drift = drift
        self.fail_freeze = fail_freeze
        self.mutations = []
        root.mkdir()

    def capture(self):
        return copy.deepcopy(self.current)

    def stage_rescue(self, files):
        created = []
        for item in files:
            path = self.root / item["name"]
            path.write_text(item["content"], encoding="utf-8")
            path.chmod(0o600)
            created.append(item["name"])
        self.mutations.append("inert_files")
        return {"created": created}

    def freeze_updates(self, changes):
        self.mutations.append("schedule")
        for item in changes["uci"]:
            self.current["uci"][item["key"]] = item["after"]
        self.current["crontab"] = changes["crontab_after"]
        if self.drift:
            self.current[self.drift] = "changed"
        if self.fail_freeze:
            raise RuntimeError("device-private-error-with-sensitive-data")

    def restore_owned(self, *, before, applied, staged):
        # 外部无关变更保留；只撤销本事务的调度和惰性文件。
        for item in applied["uci"]:
            if self.current["uci"].get(item["key"]) == item["after"]:
                self.current["uci"][item["key"]] = item["before"]
        if self.current["crontab"] == applied["crontab_after"]:
            self.current["crontab"] = before["crontab"]
        for item in staged["created"]:
            (self.root / item).unlink(missing_ok=True)


def init_proofs(tmp_path):
    from scripts.ops.evidence import init_run
    return Path(init_run(tmp_path / "private", {"role": "router"}, phase="OFFLINE")["proof_dir"])


def test_safe_preparation_rejects_dns_or_service_drift():
    from scripts.ops.safe_preparation import validate_safe_diff

    before = {k: v for k, v in snapshot().items() if k.endswith("_sha") or k.startswith("core_")}
    for key in before:
        if key == "connections_sha":
            continue
        assert validate_safe_diff(before, {**before, key: "changed"}), key
    assert validate_safe_diff(before, {**before, "unknown_write": "changed"})
    assert validate_safe_diff(before, {k: v for k, v in before.items() if k != "dns_sha"})
    assert validate_safe_diff(before, {**before, "collected_at": "later", "packet_count": 23}) == []


def test_plan_only_freezes_identified_updates_and_preserves_health_and_echo():
    from scripts.ops.safe_preparation import prepare_safe_plan

    before = snapshot()
    plan = prepare_safe_plan(before, rescue_files=[{"name": "rescue.sh", "content": "#!/bin/sh\nexit 0\n"}])
    assert plan["blockers"] == []
    assert [x["key"] for x in plan["schedule"]["uci"]] == [
        "openclash.cfg0abc.auto_update", "openclash.config.auto_update",
        "openclash.config.geo_auto_update"]
    assert plan["schedule"]["crontab_after"] == (
        "# magicpanel-safe-preparation 0 4 * * * /usr/share/openclash/openclash.sh\n"
        "*/5 * * * * /usr/local/sbin/openclash-health.sh\n"
        "0 3 * * * echo /usr/share/openclash/openclash_geo.sh\n")
    assert before == snapshot()
    assert "backup_components" not in plan


@pytest.mark.parametrize("change,code", [
    ({"schedule_requires_reload": True}, "SCHEDULE_RELOAD_REQUIRED"),
    ({"uci_pending": ["openclash.config.enable=0"]}, "PENDING_UCI_CHANGES"),
    ({"updaters_running": True}, "UPDATER_ALREADY_RUNNING"),
    ({"adapter": "arbitrary"}, "UNSUPPORTED_SCHEDULE_ADAPTER"),
    ({"backup_components": {}}, "BACKUP_COMPONENTS_REQUIRED"),
    ({"crontab": "0 * * * * /usr/share/openclash/openclash.sh && /etc/init.d/openclash restart\n"},
     "MIXED_UPDATE_CRON"),
])
def test_preflight_blocks_reload_incomplete_backup_or_unsafe_scheduler(change, code):
    from scripts.ops.safe_preparation import prepare_safe_plan

    assert code in prepare_safe_plan({**snapshot(), **change}, rescue_files=[])["blockers"]


@pytest.mark.parametrize("name", ["../rescue.sh", "/etc/init.d/procd", "sub/rescue.sh", "a;reboot"])
def test_rescue_files_cannot_escape_inert_directory(name):
    from scripts.ops.safe_preparation import prepare_safe_plan

    assert "INVALID_RESCUE_FILE" in prepare_safe_plan(snapshot(), rescue_files=[
        {"name": name, "content": "reboot"}])["blockers"]


def test_apply_verifies_encrypted_backup_before_writes_and_signs_safe_receipt(tmp_path):
    from cryptography.fernet import Fernet
    from scripts.ops.safe_preparation import prepare_safe_plan, apply_safe_preparation
    from scripts.ops.evidence import verified_proofs

    proof_dir = init_proofs(tmp_path)
    runner = FixtureRunner(tmp_path / "router")
    plan = prepare_safe_plan(runner.capture(), rescue_files=[{
        "name": "rescue.sh", "content": "#!/bin/sh\nexit 0\n"}])
    result = apply_safe_preparation(plan, runner=runner, proof_dir=proof_dir)
    assert result["state"] == "verified"
    assert result["network_fault_matrix_verified"] is False
    assert runner.current["uci"]["openclash.config.enable"] == "1"
    assert runner.current["uci"]["openclash.cfg0abc.auto_update"] == "0"
    assert (runner.root / "rescue.sh").stat().st_mode & 0o111 == 0
    encrypted = (proof_dir / "safe-backup.enc").read_bytes()
    assert b"fixture-private-data" not in encrypted
    data = Fernet((proof_dir / "backup.key").read_bytes()).decrypt(encrypted)
    assert json.loads(data)["backup_components"]["agh"] == "fixture-private-data"
    proofs = verified_proofs(proof_dir, operation_id="router.safe_preparation",
                              plan_sha=plan["plan_sha"], predecessor=plan["predecessor"])
    assert proofs["safe_backup_verified"] is True
    assert "fault_lab_verified" not in proofs
    journal = (proof_dir / "journal.jsonl").read_text()
    assert "fixture-private-data" not in journal


def test_forged_backup_boolean_and_arbitrary_plan_actions_do_not_authorize_apply(tmp_path):
    from scripts.ops.safe_preparation import prepare_safe_plan, apply_safe_preparation, SafePreparationError

    proof_dir = init_proofs(tmp_path)
    runner = FixtureRunner(tmp_path / "router")
    plan = prepare_safe_plan(runner.capture(), rescue_files=[])
    for extra in [{"safe_backup_verified": True}, {"handler": "arbitrary.shell"},
                  {"actions": [{"id": "router.safe_preparation", "command": "reboot"}]},
                  {"url": "https://example.test/update"}]:
        with pytest.raises(SafePreparationError, match="PLAN_DEFINITION_MISMATCH"):
            apply_safe_preparation({**plan, **extra}, runner=runner, proof_dir=proof_dir)
    assert runner.mutations == []


def test_backup_readback_failure_never_writes_router(tmp_path, monkeypatch):
    from scripts.ops import safe_preparation

    proof_dir = init_proofs(tmp_path)
    runner = FixtureRunner(tmp_path / "router")
    plan = safe_preparation.prepare_safe_plan(runner.capture(), rescue_files=[])
    original = Path.read_bytes

    def corrupt(path):
        return b"corrupt" if path.name == "safe-backup.enc" else original(path)

    monkeypatch.setattr(Path, "read_bytes", corrupt)
    with pytest.raises(safe_preparation.SafePreparationError, match="BACKUP_READBACK_FAILED"):
        safe_preparation.apply_safe_preparation(plan, runner=runner, proof_dir=proof_dir)
    assert runner.mutations == []


@pytest.mark.parametrize("drift", ["dns_sha", "core_pid", "firewall_sha", "forwarding_sha"])
def test_post_write_drift_only_restores_owned_preparation(tmp_path, drift):
    from scripts.ops.safe_preparation import prepare_safe_plan, apply_safe_preparation

    proof_dir = init_proofs(tmp_path)
    runner = FixtureRunner(tmp_path / "router", drift=drift)
    plan = prepare_safe_plan(runner.capture(), rescue_files=[{"name": "rescue.sh", "content": "exit 0\n"}])
    result = apply_safe_preparation(plan, runner=runner, proof_dir=proof_dir)
    assert result["state"] == "rollback_required"
    assert runner.current[drift] == "changed"
    assert runner.current["uci"] == snapshot()["uci"]
    assert runner.current["crontab"] == snapshot()["crontab"]
    assert not (runner.root / "rescue.sh").exists()
    assert "SAFE_INVARIANT_CHANGED" in result["blockers"]


def test_partial_schedule_failure_rolls_back_own_files_without_exposing_device_error(tmp_path):
    from scripts.ops.safe_preparation import prepare_safe_plan, apply_safe_preparation

    proof_dir = init_proofs(tmp_path)
    runner = FixtureRunner(tmp_path / "router", fail_freeze=True)
    plan = prepare_safe_plan(runner.capture(), rescue_files=[])
    result = apply_safe_preparation(plan, runner=runner, proof_dir=proof_dir)
    assert result["state"] == "rolled_back"
    assert runner.current == snapshot()
    assert "sensitive-data" not in json.dumps(result)


def test_apply_works_with_nonzero_current_predecessor(tmp_path):
    from scripts.ops.safe_preparation import prepare_safe_plan, apply_safe_preparation
    from scripts.ops.evidence import append_journal, journal_head

    proof_dir = init_proofs(tmp_path)
    prior = append_journal(proof_dir, operation_id="read.router", phase="PRE_NETWORK",
                           plan_sha="b" * 64, state="verified", predecessor=journal_head(proof_dir))
    runner = FixtureRunner(tmp_path / "router")
    plan = prepare_safe_plan({**runner.capture(), "predecessor": prior["receipt_sha"]}, rescue_files=[])
    result = apply_safe_preparation(plan, runner=runner, proof_dir=proof_dir)
    assert result["state"] == "verified"


def test_failed_backup_records_blocked_action_without_claiming_success(tmp_path, monkeypatch):
    from scripts.ops import safe_preparation

    proof_dir = init_proofs(tmp_path)
    runner = FixtureRunner(tmp_path / "router")
    plan = safe_preparation.prepare_safe_plan(runner.capture(), rescue_files=[])

    def denied(*args, **kwargs):
        raise safe_preparation.SafePreparationError("BACKUP_READBACK_FAILED")

    monkeypatch.setattr(safe_preparation, "_verified_backup", denied)
    with pytest.raises(safe_preparation.SafePreparationError, match="BACKUP_READBACK_FAILED"):
        safe_preparation.apply_safe_preparation(plan, runner=runner, proof_dir=proof_dir)
    row = json.loads((proof_dir / "journal.jsonl").read_text())
    assert row["state"] == "blocked"
    assert row["effects"] == ["router.private_backup", "router.stage_inert_rescue", "router.freeze_update_schedule"]
    assert runner.mutations == []


@pytest.mark.parametrize("field", ["command", "url", "handler", "actions"])
def test_snapshot_cannot_add_execution_fields(field):
    from scripts.ops.safe_preparation import prepare_safe_plan

    assert "UNRECOGNIZED_SNAPSHOT_FIELD" in prepare_safe_plan({
        **snapshot(), field: "reboot"}, rescue_files=[])["blockers"]


@pytest.fixture
def shell_helpers(tmp_path):
    source = Path(__file__).resolve().parents[2] / "ops/router/safe_prepare.sh"
    # 隔离测试纯函数；不调用脚本的设备入口或任何系统写操作。
    library = tmp_path / "helpers.sh"
    library.write_text(source.read_text(encoding="utf-8").split("\naction=${1:-}", 1)[0],
                       encoding="utf-8", newline="\n")
    bash = Path("C:/Program Files/Git/bin/bash.exe")
    return str(bash) if bash.exists() else "/bin/bash", library


def test_shell_freezes_only_actual_update_invocation(shell_helpers, tmp_path):
    bash, library = shell_helpers
    cron = tmp_path / "crontab"
    cron.write_text(snapshot()["crontab"], newline="\n")
    result = subprocess.run([bash, "-c", '. "$1"; freeze_cron "$2"', "fixture", str(library), str(cron)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "# magicpanel-safe-preparation 0 4 * * * /usr/share/openclash/openclash.sh\n"
        "*/5 * * * * /usr/local/sbin/openclash-health.sh\n"
        "0 3 * * * echo /usr/share/openclash/openclash_geo.sh\n")
    cron.write_text("0 * * * * /usr/share/openclash/openclash.sh && reboot\n", newline="\n")
    result = subprocess.run([bash, "-c", '. "$1"; freeze_cron "$2"', "fixture", str(library), str(cron)],
                            capture_output=True, text=True)
    assert result.returncode != 0


def test_shell_uci_x_anonymous_sections_do_not_enable_unrelated_fields(shell_helpers, tmp_path):
    bash, library = shell_helpers
    uci = tmp_path / "uci.fixture"
    uci.write_text("openclash.config=openclash\nopenclash.config.auto_update='1'\n"
                   "openclash.config.enable='1'\nopenclash.cfg0abc=config_subscribe\n"
                   "openclash.cfg0abc.auto_update='1'\nopenclash.cfg1abc=servers\n"
                   "openclash.cfg1abc.auto_update='1'\n", newline="\n")
    script = '. "$1"; export FIXTURE_UCI="$2"; uci() { cat "$FIXTURE_UCI"; }; update_keys'
    result = subprocess.run([bash, "-c", script, "fixture", str(library), str(uci)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["openclash.cfg0abc.auto_update", "openclash.config.auto_update"]


@pytest.mark.parametrize("command", [
    "/usr/share/openclash/openclash.sh #daily-sub-update",
    "/usr/share/openclash/openclash.sh 'Example-默认'",
    "/usr/share/openclash/openclash.sh 'Example-自建美日' loop 3600",
    "/usr/share/openclash/openclash.sh 'Example name' loop 60 >/dev/null 2>&1 # scheduled",
    "/usr/share/openclash/openclash_geo.sh ipdb",
    "/usr/share/openclash/openclash_geo.sh geosite",
    "/usr/share/openclash/openclash_geo.sh geoip",
    "/usr/share/openclash/openclash_chnroute.sh",
])
def test_known_plugin_update_arguments_are_frozen_without_execution(shell_helpers, tmp_path, command):
    from scripts.ops.safe_preparation import freeze_cron

    bash, library = shell_helpers
    text = f"0 4 * * * {command}\n"
    cron = tmp_path / "crontab"
    cron.write_text(text, encoding="utf-8", newline="\n")
    assert freeze_cron(text) == "# magicpanel-safe-preparation " + text
    result = subprocess.run([bash, "-c", '. "$1"; freeze_cron "$2"', "fixture", str(library), str(cron)],
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("utf-8") == "# magicpanel-safe-preparation " + text


@pytest.mark.parametrize("suffix", [
    "'Example' loop 3600 && /etc/init.d/openclash restart",
    "'Example'; /usr/local/sbin/openclash-health.sh",
    "'Example' loop $(reboot)", "'Example' loop `reboot`", "'Example' loop 0",
    "'Example' loop 3600 extra", "'Example' 'second-subscription'", "'unterminated",
])
def test_plugin_argument_parser_rejects_mixed_or_unrecognized_shell(shell_helpers, tmp_path, suffix):
    from scripts.ops.safe_preparation import freeze_cron, SafePreparationError

    bash, library = shell_helpers
    text = f"0 4 * * * /usr/share/openclash/openclash.sh {suffix}\n"
    cron = tmp_path / "crontab"
    cron.write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(SafePreparationError):
        freeze_cron(text)
    result = subprocess.run([bash, "-c", '. "$1"; freeze_cron "$2"', "fixture", str(library), str(cron)],
                            capture_output=True)
    assert result.returncode != 0


def test_connection_diagnostic_churn_does_not_change_plan_or_control_flow_guard():
    from scripts.ops.safe_preparation import prepare_safe_plan, validate_safe_diff

    before = snapshot()
    after = {**before, "connections_sha": "normal-new-and-expired-flows", "packet_count": 42}
    assert validate_safe_diff(before, after) == []
    assert prepare_safe_plan(before, rescue_files=[])["plan_sha"] == prepare_safe_plan(
        after, rescue_files=[])["plan_sha"]
    assert validate_safe_diff(before, {**after, "forwarding_sha": "changed"}) == ["SAFE_INVARIANT_CHANGED"]


@pytest.fixture
def isolated_router(tmp_path):
    """真实ash兼容sh在无网络命名空间运行；/etc和/root均是一次性目录。"""
    bwrap = shutil.which("bwrap")
    if os.name != "posix" or not bwrap:
        pytest.skip("Linux user namespace fixture; covered by WSL run")
    probe = subprocess.run([bwrap, "--unshare-all", "--ro-bind", "/", "/", "--", "/usr/bin/true"],
                           capture_output=True)
    if probe.returncode:
        pytest.skip("user namespaces unavailable")
    etc = tmp_path / "etc"
    tools = tmp_path / "bin"
    private = tmp_path / "root"
    for directory in (etc / "config", etc / "crontabs", tools, private):
        directory.mkdir(parents=True, mode=0o700)
    (etc / "openwrt_release").write_text("fixture-openwrt\n")
    (etc / "board.json").write_text('{"fixture":true}\n')
    (etc / "config/openclash").write_text("\n".join(
        f"{key}='{value}'" for key, value in snapshot()["uci"].items()) + "\n")
    (etc / "crontabs/root").write_text(snapshot()["crontab"])
    uci = tools / "uci"
    uci.write_text('''#!/usr/bin/python3
import json, pathlib, sys
args=sys.argv[1:]
config=pathlib.Path('/etc/config/openclash')
pending_path=pathlib.Path('/etc/pending.json')
pending=json.loads(pending_path.read_text()) if pending_path.exists() else {}
values=dict(line.split('=',1) for line in config.read_text().splitlines())
if args == ['-X','show','openclash']:
    print(config.read_text(),end='')
elif args[0] == 'changes':
    for key,value in pending.items(): print(key+'='+value)
elif args[0] == 'get':
    print(pending.get(args[1],values[args[1]]).strip("'"))
elif args[0] == 'set':
    key,value=args[1].split('=',1);pending[key]="'"+value+"'"
    if pathlib.Path('/etc/inject-unowned').exists(): pending['openclash.config.enable']="'0'"
elif args[0] == 'commit':
    values.update(pending);pending={}
    config.write_text(''.join(key+'='+value+'\\n' for key,value in values.items()))
elif args[0] == 'revert':
    pending.pop(args[1],None)
else: sys.exit(99)
pending_path.write_text(json.dumps(pending))
''')
    uci.chmod(0o755)
    (tools / "crontab").write_text(
        '#!/bin/sh\ncase "$1" in */candidate.cron) [ ! -e /etc/fail-crontab ] || exit 99;; esac\n'
        'cp "$1" /etc/crontabs/root\n')
    (tools / "crontab").chmod(0o755)
    for name in ("nft", "ip", "conntrack", "netstat"):
        (tools / name).write_text('#!/bin/sh\necho forbidden >> /etc/network-commands.log\nexit 99\n')
        (tools / name).chmod(0o755)
    source = Path(__file__).resolve().parents[2] / "ops/router/safe_prepare.sh"
    base = [bwrap, "--unshare-all", "--uid", "0", "--gid", "0", "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--bind", str(tools), "/usr/sbin", "--bind", str(etc), "/etc",
            "--ro-bind", "/etc/alternatives", "/etc/alternatives",
            "--bind", str(private), "/root", "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev",
            "--ro-bind", str(source), "/safe_prepare.sh", "--chdir", "/", "--", "/bin/sh", "/safe_prepare.sh"]

    def call(*args, body=None):
        return subprocess.run([*base, *args], input=body, capture_output=True)

    return call, etc, private


def test_isolated_shell_freezes_and_restores_only_schedule_and_stages_inert_file(isolated_router):
    call, etc, private = isolated_router
    config = etc / "config/openclash"
    cron = etc / "crontabs/root"
    before_config, before_cron = config.read_bytes(), cron.read_bytes()
    content = b"#!/bin/sh\nexit 79\n"
    sha = hashlib.sha256(content).hexdigest()
    result = call("stage", "a" * 64, "rescue.sh", sha, body=content)
    assert result.returncode == 0, result.stderr
    inert = private / ".magicpanel-safe-preparation" / ("a" * 64) / "inert/rescue.sh"
    assert inert.read_bytes() == content
    assert inert.stat().st_mode & 0o777 == 0o600
    result = call("freeze", "a" * 64, hashlib.sha256(before_config).hexdigest(),
                  hashlib.sha256(before_cron).hexdigest())
    assert result.returncode == 0, result.stderr
    assert "openclash.config.enable='1'" in config.read_text()
    assert "openclash.cfg0abc.auto_update='0'" in config.read_text()
    assert cron.read_text().startswith("# magicpanel-safe-preparation ")
    result = call("restore", "a" * 64)
    assert result.returncode == 0, result.stderr
    assert config.read_bytes() == before_config
    assert cron.read_bytes() == before_cron
    assert call("unstage", "a" * 64, "rescue.sh", sha).returncode == 0
    assert not inert.exists()
    assert not (etc / "network-commands.log").exists()


def test_isolated_shell_failure_reverts_only_own_pending_uci(isolated_router):
    call, etc, private = isolated_router
    (etc / "inject-unowned").touch()
    config = etc / "config/openclash"
    cron = etc / "crontabs/root"
    before_config, before_cron = config.read_bytes(), cron.read_bytes()
    result = call("freeze", "b" * 64, hashlib.sha256(before_config).hexdigest(),
                  hashlib.sha256(before_cron).hexdigest())
    assert result.returncode != 0
    assert json.loads((etc / "pending.json").read_text()) == {"openclash.config.enable": "'0'"}
    assert config.read_bytes() == before_config
    assert cron.read_bytes() == before_cron
    assert not (etc / "network-commands.log").exists()


def test_isolated_shell_failure_after_uci_commit_restores_own_schedule(isolated_router):
    call, etc, private = isolated_router
    (etc / "fail-crontab").touch()
    config = etc / "config/openclash"
    cron = etc / "crontabs/root"
    before_config, before_cron = config.read_bytes(), cron.read_bytes()
    result = call("freeze", "c" * 64, hashlib.sha256(before_config).hexdigest(),
                  hashlib.sha256(before_cron).hexdigest())
    assert result.returncode != 0
    assert config.read_bytes() == before_config
    assert cron.read_bytes() == before_cron
    assert not (etc / "network-commands.log").exists()
