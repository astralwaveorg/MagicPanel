#!/usr/bin/env python3
"""V2固定操作CLI。普通输出只含安全ID、摘要和阻塞码。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ops.contracts import OPERATION_REGISTRY, PHASES
from scripts.ops.evidence import (
    EvidenceError, canonical_bytes, digest, init_run, journal_head, private_path,
    private_write, seal_artifact, verified_proofs, verify_artifact,
)
from scripts.ops.phase_guard import authorize_operation
from scripts.ops.safe_preparation import (
    LocalRouterRunner, SafePreparationError, apply_safe_preparation, prepare_safe_plan, source_digests,
)


def _json(path):
    if Path(path).stat().st_size > 512 * 1024 * 1024:
        raise EvidenceError("INPUT_TOO_LARGE")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _inventory(path, directory):
    inventory = _json(path)
    run = _json(private_path(Path(directory)) / "run.json")
    if digest(inventory) != run["inventory_sha"] or inventory.get("role") != run["target_role"]:
        raise EvidenceError("INVENTORY_BINDING_MISMATCH")
    return inventory


def _preview(plan):
    operation = plan["operation"]
    return {"operation_id": operation["id"], "target_role": operation["target_role"],
            "effects": operation["effects"], "phase": plan["phase"], "plan_sha": plan["plan_sha"],
            "sources": plan["sources"], "blockers": plan["blockers"], "dry_run": True}


def dispatch_registered(artifact: dict, *, inventory: dict, proof_dir: Path):
    """入口只绑定实际已实现的固定函数，不通过import字符串解析handler。"""
    if not isinstance(artifact, dict) or "signature" not in artifact:
        raise EvidenceError("VERIFIED_PLAN_REQUIRED")
    plan = verify_artifact(proof_dir, artifact, purpose="safe_plan")
    run = _json(private_path(Path(proof_dir)) / "run.json")
    if digest(inventory) != run["inventory_sha"]:
        raise EvidenceError("INVENTORY_BINDING_MISMATCH")
    if plan.get("operation") != OPERATION_REGISTRY.get("router.safe_preparation"):
        raise EvidenceError("NO_REGISTERED_EXECUTOR")
    if plan.get("sources") != source_digests():
        raise EvidenceError("HANDLER_SOURCE_CHANGED")
    runner = LocalRouterRunner(inventory)
    return apply_safe_preparation(plan, runner=runner, proof_dir=proof_dir)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", allow_abbrev=False)
    init.add_argument("--run-root", type=Path, required=True)
    init.add_argument("--inventory", type=Path, required=True)
    init.add_argument("--phase", choices=["OFFLINE"], required=True)
    plan_parser = sub.add_parser("plan", allow_abbrev=False)
    plan_parser.add_argument("--operation-file", type=Path, required=True)
    plan_parser.add_argument("--phase", choices=PHASES, required=True)
    plan_parser.add_argument("--proof-dir", type=Path, required=True)
    apply_parser = sub.add_parser("apply", allow_abbrev=False)
    apply_parser.add_argument("--plan-file", type=Path, required=True)
    apply_parser.add_argument("--inventory", type=Path, required=True)
    apply_parser.add_argument("--proof-dir", type=Path, required=True)
    router = sub.add_parser("router", allow_abbrev=False)
    router_sub = router.add_subparsers(dest="router_command", required=True)
    safe = router_sub.add_parser("safe-prepare", allow_abbrev=False)
    safe.add_argument("--inventory", type=Path, required=True)
    safe.add_argument("--proof-dir", type=Path, required=True)
    safe.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init_run(args.run_root, _json(args.inventory), phase=args.phase)
        elif args.command == "plan":
            operation = _json(args.operation_file)
            if not isinstance(operation, dict) or not isinstance(operation.get("id"), str):
                raise ValueError("invalid_operation")
            # 任意额外字段在phase_guard整定义比较中拒绝，包括嵌套GET/SSH。
            predecessor = journal_head(args.proof_dir)
            plan = {"schema": 1, "operation": operation, "phase": args.phase,
                    "sources": source_digests(), "predecessor": predecessor}
            plan["plan_sha"] = digest(plan)
            plan["blockers"] = authorize_operation(operation, args.phase, verified_proofs(
                args.proof_dir, operation_id=operation.get("id"), plan_sha=plan["plan_sha"],
                predecessor=predecessor))
            if operation != OPERATION_REGISTRY.get(operation.get("id")):
                result = {"blockers": plan["blockers"], "dry_run": True}
            else:
                private_write(private_path(args.proof_dir) / f"{plan['plan_sha']}.plan.json",
                              canonical_bytes(seal_artifact(args.proof_dir, purpose="operation_plan", body=plan)))
                result = _preview(plan)
        elif args.command == "router":
            inventory = _inventory(args.inventory, args.proof_dir)
            snapshot = inventory.get("snapshot", {})
            plan = prepare_safe_plan({**snapshot, "predecessor": journal_head(args.proof_dir)},
                                     rescue_files=inventory.get("rescue_files", []))
            path = private_path(args.proof_dir) / f"{plan['plan_sha']}.safe-plan.json"
            if not path.exists():
                private_write(path, canonical_bytes(seal_artifact(args.proof_dir, purpose="safe_plan", body=plan)))
            result = dispatch_registered(_json(path), inventory=inventory, proof_dir=args.proof_dir) if args.apply else _preview(plan)
        else:
            inventory = _inventory(args.inventory, args.proof_dir)
            artifact = _json(args.plan_file)
            plan = verify_artifact(args.proof_dir, artifact, purpose="safe_plan")
            if plan.get("predecessor") != journal_head(args.proof_dir):
                raise EvidenceError("PREDECESSOR_MISMATCH")
            result = dispatch_registered(artifact, inventory=inventory, proof_dir=args.proof_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1 if result.get("blockers") else 0
    except (EvidenceError, SafePreparationError) as exc:
        print(json.dumps({"blockers": [str(exc)]}))
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"blockers": ["INVALID_PRIVATE_INPUT"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
