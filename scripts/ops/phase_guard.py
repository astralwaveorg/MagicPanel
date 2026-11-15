"""proofs 参数只能由证据验签边界提供；此纯函数不执行操作。"""
from scripts.ops.contracts import OPERATION_REGISTRY, PHASES


def authorize_operation(operation: dict, phase: str, proofs: dict) -> list[str]:
    if not isinstance(operation, dict) or not isinstance(operation.get("id"), str):
        return ["UNKNOWN_OPERATION"]
    registered = OPERATION_REGISTRY.get(operation["id"])
    if registered is None:
        return ["UNKNOWN_OPERATION"]
    if operation != registered:
        return ["OPERATION_DEFINITION_MISMATCH"]
    if phase not in PHASES:
        return ["UNKNOWN_PHASE"]
    operation_id = registered["id"]
    if operation_id == "router.safe_preparation":
        if phase not in ("PRE_NETWORK", "ROUTER_FINAL"):
            return ["SAFE_PREPARATION_PHASE_REQUIRED"]
        return [] if proofs.get("safe_backup_verified") is True else ["SAFE_BACKUP_REQUIRED"]
    if operation_id in ("dns_control.hk.deploy", "dns_control.kr.deploy"):
        if phase not in ("PRE_NETWORK", "ROUTER_FINAL"):
            return ["DNS_CONTROL_PHASE_REQUIRED"]
        return [] if proofs.get("dns_preflight_verified") is True else ["DNS_PREFLIGHT_REQUIRED"]
    effects = set(registered["effects"])
    if not any(x.startswith(("router.", "nas.production.", "freeze.production.")) for x in effects):
        return []
    if phase != "ROUTER_FINAL":
        return ["ROUTER_PHASE_REQUIRED"]
    checks = (("rescue_verified", "RESCUE_REQUIRED"), ("fault_lab_verified", "FAULT_LAB_REQUIRED"),
              ("rollback_verified", "ROLLBACK_REQUIRED"), ("window_authorized", "WINDOW_REQUIRED"))
    blockers = [code for key, code in checks if proofs.get(key) is not True]
    if effects & {"nas.production.db_migrate", "nas.production.image_upgrade"}:
        if proofs.get("freeze_state") != "ACTIVE":
            blockers.append("FREEZE_ACTIVE_REQUIRED")
        if proofs.get("production_sequence_verified") is not True:
            blockers.append("PRODUCTION_SEQUENCE_REQUIRED")
    return blockers
