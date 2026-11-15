"""阶段门禁和命令注入边界，仅使用离线数据。"""
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.mark.parametrize("operation_id", [
    "router.probe_bypass", "router.dns", "router.subscription", "router.core",
    "router.firewall", "router.service", "router.wireguard", "router.sqm_calibrate",
    "nas.production.reader_install", "freeze.production.prepare",
    "freeze.production.arm", "nas.production.db_migrate", "nas.production.image_upgrade",
])
def test_pre_network_rejects_router_and_production_writes(operation_id):
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.phase_guard import authorize_operation

    proofs = {"feeds_hash_unchanged": True, "freeze_state": "ACTIVE",
              "production_sequence_verified": True}
    assert "ROUTER_PHASE_REQUIRED" in authorize_operation(
        OPERATION_REGISTRY[operation_id], "PRE_NETWORK", proofs)


@pytest.mark.parametrize("operation_id", [
    "nas.staging.reader_install", "freeze.staging.prepare", "freeze.staging.arm",
    "nas.staging.db_migrate", "nas.staging.image_upgrade", "read.router", "read.nas",
])
def test_pre_network_allows_only_registered_independent_staging_and_reads(operation_id):
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.phase_guard import authorize_operation

    assert authorize_operation(OPERATION_REGISTRY[operation_id], "PRE_NETWORK", {}) == []


def test_safe_name_cannot_smuggle_network_effects():
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.phase_guard import authorize_operation

    good = OPERATION_REGISTRY["router.safe_preparation"]
    assert authorize_operation(good, "PRE_NETWORK", {"safe_backup_verified": True}) == []
    for field, value in [("effects", ["router.dns"]), ("handler", "arbitrary.shell"),
                         ("target_role", "nas")]:
        assert authorize_operation({**good, field: value}, "PRE_NETWORK", {
            "safe_backup_verified": True}) == ["OPERATION_DEFINITION_MISMATCH"]
    assert authorize_operation(good, "PRE_NETWORK", {}) == ["SAFE_BACKUP_REQUIRED"]
    assert authorize_operation(good, "OFFLINE", {"safe_backup_verified": True}) == [
        "SAFE_PREPARATION_PHASE_REQUIRED"]


def test_registry_cannot_be_mutated_to_redefine_authorization():
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.phase_guard import authorize_operation

    operation = OPERATION_REGISTRY["router.safe_preparation"]
    operation["effects"].append("router.dns")
    assert authorize_operation(operation, "PRE_NETWORK", {"safe_backup_verified": True}) == [
        "OPERATION_DEFINITION_MISMATCH"]
    assert OPERATION_REGISTRY["router.safe_preparation"]["effects"] == [
        "router.private_backup", "router.stage_inert_rescue", "router.freeze_update_schedule"]


@pytest.mark.parametrize("extra", [
    {"command": "ssh nas ssh wrt reboot"},
    {"url": "https://example.test/update"},
    {"request": {"method": "GET", "url": "https://example.test/update"}},
    {"read_only": True, "handler": "shell.exec"},
])
def test_read_cannot_smuggle_nested_ssh_or_get_update(extra):
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.phase_guard import authorize_operation

    assert authorize_operation({**OPERATION_REGISTRY["read.router"], **extra},
                               "PRE_NETWORK", {}) == ["OPERATION_DEFINITION_MISMATCH"]


def test_unknown_operation_phase_and_production_relabel_fail_closed():
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.phase_guard import authorize_operation

    assert authorize_operation({"id": "unknown"}, "PRE_NETWORK", {}) == ["UNKNOWN_OPERATION"]
    assert authorize_operation(OPERATION_REGISTRY["read.router"], "unknown", {}) == [
        "UNKNOWN_PHASE"]
    bad = {**OPERATION_REGISTRY["nas.production.image_upgrade"],
           "effects": ["nas.staging.image_upgrade"]}
    assert authorize_operation(bad, "PRE_NETWORK", {}) == ["OPERATION_DEFINITION_MISMATCH"]


@pytest.mark.parametrize("operation_id", ["nas.production.db_migrate", "nas.production.image_upgrade"])
def test_final_production_requires_rescue_freeze_and_sequence(operation_id):
    from scripts.ops.contracts import OPERATION_REGISTRY
    from scripts.ops.phase_guard import authorize_operation

    op = OPERATION_REGISTRY[operation_id]
    assert "RESCUE_REQUIRED" in authorize_operation(op, "ROUTER_FINAL", {})
    proofs = {k: True for k in ("rescue_verified", "fault_lab_verified", "rollback_verified",
                               "window_authorized")}
    assert {"FREEZE_ACTIVE_REQUIRED", "PRODUCTION_SEQUENCE_REQUIRED"} <= set(
        authorize_operation(op, "ROUTER_FINAL", proofs))
    assert authorize_operation(op, "ROUTER_FINAL", {
        **proofs, "freeze_state": "ACTIVE", "production_sequence_verified": True}) == []


def test_proofs_are_signed_and_bound_to_current_action_and_predecessor(tmp_path):
    from scripts.ops.evidence import EvidenceError, init_run, write_proof, verified_proofs

    run = init_run(tmp_path / "private", {"role": "router"}, phase="OFFLINE")
    proof_dir = Path(run["proof_dir"])
    write_proof(proof_dir, "production_sequence", operation_id="nas.production.image_upgrade",
                plan_sha="a" * 64, predecessor="b" * 64,
                claims={"production_sequence_verified": True})
    assert verified_proofs(proof_dir, operation_id="nas.production.image_upgrade",
                           plan_sha="a" * 64, predecessor="b" * 64) == {
                               "production_sequence_verified": True}
    assert verified_proofs(proof_dir, operation_id="nas.production.db_migrate",
                           plan_sha="a" * 64, predecessor="b" * 64) == {}
    assert verified_proofs(proof_dir, operation_id="nas.production.image_upgrade",
                           plan_sha="a" * 64, predecessor="c" * 64) == {}
    path = proof_dir / "production_sequence.proof.json"
    path.write_text(path.read_text().replace('"production_sequence_verified":true',
                                            '"production_sequence_verified":false'))
    with pytest.raises(EvidenceError, match="PROOF_SIGNATURE_INVALID"):
        verified_proofs(proof_dir, operation_id="nas.production.image_upgrade",
                        plan_sha="a" * 64, predecessor="b" * 64)


def test_run_root_rejects_git_tree_and_journal_omits_secrets(tmp_path):
    from scripts.ops.evidence import EvidenceError, init_run, append_journal, journal_head

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(EvidenceError, match="PRIVATE_PATH_IN_GIT"):
        init_run(repo / "private", {"role": "router"}, phase="OFFLINE")
    run = init_run(tmp_path / "outside", {"role": "router"}, phase="OFFLINE")
    proof_dir = Path(run["proof_dir"])
    before = journal_head(proof_dir)
    row = append_journal(proof_dir, operation_id="read.router", phase="PRE_NETWORK",
                         plan_sha="a" * 64, state="verified", predecessor=before)
    assert row["target_role"] == "router"
    assert row["effects"] == ["read.router"]
    assert journal_head(proof_dir) == row["receipt_sha"]
    with pytest.raises(EvidenceError, match="PREDECESSOR_MISMATCH"):
        append_journal(proof_dir, operation_id="read.router", phase="PRE_NETWORK",
                       plan_sha="a" * 64, state="verified", predecessor=before)
    assert set(row) == {"sequence", "operation_id", "phase", "target_role", "effects",
                        "plan_sha", "state", "predecessor", "receipt_sha", "signature"}


def test_cli_rejects_arbitrary_execution_flags_and_defaults_to_dry_run(tmp_path, capsys):
    from scripts.v2_acceptance import main

    for args in [["--command", "reboot"], ["--url", "https://example.test/update"],
                 ["router", "safe-prepare", "--rescue-ok"]]:
        with pytest.raises(SystemExit):
            main(args)


def test_safe_backup_proof_stops_authorizing_after_archive_corruption(tmp_path):
    from scripts.ops.evidence import EvidenceError, verified_proofs
    from scripts.ops.safe_preparation import prepare_safe_plan, apply_safe_preparation
    from test_ops_safe_preparation import FixtureRunner, init_proofs

    directory = init_proofs(tmp_path)
    runner = FixtureRunner(tmp_path / "router")
    plan = prepare_safe_plan(runner.capture(), rescue_files=[])
    apply_safe_preparation(plan, runner=runner, proof_dir=directory)
    (directory / "safe-backup.enc").write_bytes(b"corrupted")
    with pytest.raises(EvidenceError, match="PROOF_EVIDENCE_CHANGED"):
        verified_proofs(directory, operation_id="router.safe_preparation",
                        plan_sha=plan["plan_sha"], predecessor=plan["predecessor"])


def test_cli_safe_prepare_preview_never_constructs_device_runner(tmp_path, monkeypatch, capsys):
    from scripts import v2_acceptance
    from test_ops_safe_preparation import snapshot

    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"role": "router", "snapshot": snapshot()}))
    assert v2_acceptance.main(["init", "--run-root", str(tmp_path / "private"),
                               "--inventory", str(inventory), "--phase", "OFFLINE"]) == 0
    proof_dir = Path(json.loads(capsys.readouterr().out)["proof_dir"])

    def forbidden(*args, **kwargs):
        raise AssertionError("dry_run_must_not_touch_device")

    monkeypatch.setattr(v2_acceptance, "LocalRouterRunner", forbidden)
    assert v2_acceptance.main(["router", "safe-prepare", "--inventory", str(inventory),
                               "--proof-dir", str(proof_dir)]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["dry_run"] is True
    assert preview["operation_id"] == "router.safe_preparation"
    assert "fixture-private-data" not in json.dumps(preview)
    assert not (proof_dir / "safe-backup.enc").exists()
    assert not (proof_dir / "journal.jsonl").exists()


def test_cli_apply_rejects_tampered_plan_before_creating_runner(tmp_path, monkeypatch, capsys):
    from scripts import v2_acceptance
    from test_ops_safe_preparation import snapshot

    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"role": "router", "snapshot": snapshot()}))
    v2_acceptance.main(["init", "--run-root", str(tmp_path / "private"),
                        "--inventory", str(inventory), "--phase", "OFFLINE"])
    proof_dir = Path(json.loads(capsys.readouterr().out)["proof_dir"])
    v2_acceptance.main(["router", "safe-prepare", "--inventory", str(inventory),
                        "--proof-dir", str(proof_dir)])
    capsys.readouterr()
    plan_path = next(proof_dir.glob("*.safe-plan.json"))
    plan_path.write_text(plan_path.read_text().replace('"phase":"PRE_NETWORK"',
                                                      '"phase":"ROUTER_FINAL"'))

    def forbidden(*args, **kwargs):
        raise AssertionError("tampered_plan_must_not_touch_device")

    monkeypatch.setattr(v2_acceptance, "LocalRouterRunner", forbidden)
    assert v2_acceptance.main(["apply", "--plan-file", str(plan_path), "--inventory", str(inventory),
                               "--proof-dir", str(proof_dir)]) == 1
    assert json.loads(capsys.readouterr().out)["blockers"] == ["PROOF_SIGNATURE_INVALID"]


def test_dispatch_does_not_trust_unsealed_or_rehashed_network_plan(tmp_path):
    from scripts.v2_acceptance import dispatch_registered
    from scripts.ops.evidence import EvidenceError
    from scripts.ops.safe_preparation import prepare_safe_plan
    from test_ops_safe_preparation import snapshot

    plan = prepare_safe_plan(snapshot(), rescue_files=[])
    plan["actions"] = ["restart"]
    with pytest.raises(EvidenceError, match="VERIFIED_PLAN_REQUIRED"):
        dispatch_registered(plan, inventory={"role": "router"}, proof_dir=tmp_path)


@pytest.mark.parametrize("operation", [None, [], "ssh wrt reboot", {"id": ["read.router"]}])
def test_cli_malformed_operation_is_sanitized_and_never_executes(tmp_path, capsys, operation):
    from scripts.v2_acceptance import main
    from scripts.ops.evidence import init_run

    run = init_run(tmp_path / "private", {"role": "router"}, phase="OFFLINE")
    operation_file = tmp_path / "operation.json"
    operation_file.write_text(json.dumps(operation))
    assert main(["plan", "--operation-file", str(operation_file), "--phase", "PRE_NETWORK",
                 "--proof-dir", run["proof_dir"]]) == 1
    assert json.loads(capsys.readouterr().out)["blockers"] == ["INVALID_PRIVATE_INPUT"]
