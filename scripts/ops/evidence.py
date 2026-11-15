"""仓库外私密运行目录、签名证据和连续摘要日志。"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import uuid

from scripts.ops.contracts import OPERATION_REGISTRY, PHASES

ZERO_SHA = "0" * 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PURPOSE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_CLAIMS = frozenset(("safe_backup_verified", "rescue_verified", "fault_lab_verified",
                     "rollback_verified", "window_authorized", "freeze_state",
                     "production_sequence_verified", "dns_preflight_verified"))


class EvidenceError(ValueError):
    pass


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def private_path(path: Path, *, create=False) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise EvidenceError("PRIVATE_PATH_SYMLINK")
        if (part / ".git").exists():
            raise EvidenceError("PRIVATE_PATH_IN_GIT")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    if not path.is_dir():
        raise EvidenceError("PRIVATE_DIRECTORY_REQUIRED")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise EvidenceError("PRIVATE_DIRECTORY_PERMISSIONS")
    return path


def private_write(path: Path, body: bytes, *, exclusive=True):
    parent = private_path(path.parent)
    path = parent / path.name
    if path.is_symlink():
        raise EvidenceError("PRIVATE_PATH_SYMLINK")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def _read_private(path):
    private_path(path.parent)
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("PRIVATE_FILE_REQUIRED")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise EvidenceError("PRIVATE_FILE_PERMISSIONS")
    return path.read_bytes()


def init_run(run_root: Path, inventory: dict, *, phase: str) -> dict:
    if phase != "OFFLINE":
        raise EvidenceError("INIT_OFFLINE_REQUIRED")
    if not isinstance(inventory, dict) or inventory.get("role") not in ("router", "nas", "dns_control"):
        raise EvidenceError("INVALID_INVENTORY")
    root = private_path(Path(run_root), create=True)
    run_id = uuid.uuid4().hex
    directory = private_path(root / run_id, create=True)
    private_write(directory / "signing.key", secrets.token_bytes(32))
    run = {"schema": 1, "run_id": run_id, "phase": phase,
           "inventory_sha": digest(inventory), "target_role": inventory["role"]}
    private_write(directory / "run.json", canonical_bytes(run))
    return {**run, "proof_dir": str(directory)}


def _run(directory):
    return json.loads(_read_private(private_path(Path(directory)) / "run.json"))


def _signature(directory, body):
    key = _read_private(Path(directory) / "signing.key")
    if len(key) != 32:
        raise EvidenceError("INVALID_SIGNING_KEY")
    return hmac.new(key, canonical_bytes(body), hashlib.sha256).hexdigest()


def seal_artifact(directory: Path, *, purpose: str, body: dict) -> dict:
    if not _PURPOSE.fullmatch(purpose):
        raise EvidenceError("INVALID_PROOF_PURPOSE")
    payload = {"schema": 1, "run_id": _run(directory)["run_id"], "purpose": purpose, "body": body}
    return {**payload, "signature": _signature(directory, payload)}


def verify_artifact(directory: Path, artifact: dict, *, purpose: str) -> dict:
    if not isinstance(artifact, dict) or set(artifact) != {"schema", "run_id", "purpose", "body", "signature"}:
        raise EvidenceError("PROOF_SIGNATURE_INVALID")
    payload = {k: v for k, v in artifact.items() if k != "signature"}
    if (artifact["schema"] != 1 or artifact["purpose"] != purpose or
            artifact["run_id"] != _run(directory)["run_id"] or
            not isinstance(artifact["signature"], str) or
            not hmac.compare_digest(artifact["signature"], _signature(directory, payload))):
        raise EvidenceError("PROOF_SIGNATURE_INVALID")
    return artifact["body"]


def write_proof(directory: Path, purpose: str, *, operation_id: str, plan_sha: str,
                predecessor: str, claims: dict, evidence_hashes: dict | None = None) -> dict:
    if operation_id not in OPERATION_REGISTRY or not _SHA.fullmatch(plan_sha) or not _SHA.fullmatch(predecessor):
        raise EvidenceError("INVALID_PROOF_BINDING")
    if not isinstance(claims, dict) or set(claims) - _CLAIMS:
        raise EvidenceError("INVALID_PROOF_CLAIMS")
    body = {"operation_id": operation_id, "plan_sha": plan_sha, "predecessor": predecessor,
            "claims": claims, "evidence_hashes": evidence_hashes or {}}
    for filename, expected in body["evidence_hashes"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", filename) or not _SHA.fullmatch(expected):
            raise EvidenceError("INVALID_PROOF_EVIDENCE")
        if hashlib.sha256(_read_private(Path(directory) / filename)).hexdigest() != expected:
            raise EvidenceError("PROOF_EVIDENCE_CHANGED")
    artifact = seal_artifact(directory, purpose=purpose, body=body)
    private_write(Path(directory) / f"{purpose}.proof.json", canonical_bytes(artifact))
    return artifact


def verified_proofs(directory: Path, *, operation_id: str, plan_sha: str, predecessor: str) -> dict:
    proofs = {}
    for path in sorted(private_path(Path(directory)).glob("*.proof.json")):
        purpose = path.name.removesuffix(".proof.json")
        body = verify_artifact(directory, json.loads(_read_private(path)), purpose=purpose)
        if (body.get("operation_id"), body.get("plan_sha"), body.get("predecessor")) != (
                operation_id, plan_sha, predecessor):
            continue
        claims = body.get("claims", {})
        if not isinstance(claims, dict) or set(claims) - _CLAIMS:
            raise EvidenceError("INVALID_PROOF_CLAIMS")
        hashes = body.get("evidence_hashes", {})
        if claims.get("safe_backup_verified") is True and not {"safe-backup.enc", "backup.key"} <= hashes.keys():
            raise EvidenceError("PROOF_EVIDENCE_REQUIRED")
        for filename, expected in hashes.items():
            if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", filename) or not _SHA.fullmatch(expected):
                raise EvidenceError("INVALID_PROOF_EVIDENCE")
            if hashlib.sha256(_read_private(Path(directory) / filename)).hexdigest() != expected:
                raise EvidenceError("PROOF_EVIDENCE_CHANGED")
        if claims.get("rescue_verified") is True:
            required={"accepted-rescue-manifest.json","rescue-binding.json","rescue_path.receipt.json",
                      "rescue_resources.receipt.json","rescue_rehearsal.receipt.json"}
            if not required <= hashes.keys():
                raise EvidenceError("RESCUE_EVIDENCE_REQUIRED")
            try:
                from scripts.ops.rescue import verify_rescue_readiness
                binding=json.loads(_read_private(Path(directory)/"rescue-binding.json"))
                manifest=json.loads(_read_private(Path(directory)/"accepted-rescue-manifest.json"))
                root=private_path(Path(binding["root"]))
                if verify_rescue_readiness(root,manifest,Path(directory),architecture=binding["architecture"]):
                    raise EvidenceError("RESCUE_EVIDENCE_INVALID")
            except (OSError,ValueError,TypeError,KeyError):
                raise EvidenceError("RESCUE_EVIDENCE_INVALID") from None
        for key, value in claims.items():
            if key in proofs and proofs[key] != value:
                raise EvidenceError("CONFLICTING_PROOFS")
            proofs[key] = value
    return proofs


@contextmanager
def run_lock(directory: Path):
    path = private_path(Path(directory)) / ".operation-lock"
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise EvidenceError("RUN_LOCKED") from None
    try:
        yield
    finally:
        path.rmdir()


def _journal(directory):
    path = private_path(Path(directory)) / "journal.jsonl"
    if not path.exists():
        return []
    rows = []
    predecessor = ZERO_SHA
    for line in _read_private(path).splitlines():
        row = json.loads(line)
        payload = {k: v for k, v in row.items() if k not in ("signature", "receipt_sha")}
        if (row.get("sequence") != len(rows) + 1 or row.get("predecessor") != predecessor or
                row.get("receipt_sha") != digest(payload) or
                not hmac.compare_digest(row.get("signature", ""), _signature(directory, {
                    **payload, "receipt_sha": row["receipt_sha"]}))):
            raise EvidenceError("JOURNAL_CHAIN_INVALID")
        rows.append(row)
        predecessor = row["receipt_sha"]
    return rows


def journal_head(directory: Path) -> str:
    rows = _journal(directory)
    return rows[-1]["receipt_sha"] if rows else ZERO_SHA


def append_journal(directory: Path, *, operation_id: str, phase: str, plan_sha: str,
                   state: str, predecessor: str) -> dict:
    if operation_id not in OPERATION_REGISTRY or phase not in PHASES or not _SHA.fullmatch(plan_sha):
        raise EvidenceError("INVALID_JOURNAL_ACTION")
    if state not in ("prepared", "verified", "blocked", "rolled_back", "rollback_required"):
        raise EvidenceError("INVALID_JOURNAL_STATE")
    rows = _journal(directory)
    if predecessor != (rows[-1]["receipt_sha"] if rows else ZERO_SHA):
        raise EvidenceError("PREDECESSOR_MISMATCH")
    op = OPERATION_REGISTRY[operation_id]
    row = {"sequence": len(rows) + 1, "operation_id": operation_id, "phase": phase,
           "target_role": op["target_role"], "effects": op["effects"], "plan_sha": plan_sha,
           "state": state, "predecessor": predecessor}
    row["receipt_sha"] = digest(row)
    row["signature"] = _signature(directory, row)
    path = Path(directory) / "journal.jsonl"
    # 调用者持有 run_lock；原子替换避免中断留下半行。
    temporary = path.with_suffix(".pending")
    private_write(temporary, b"".join(canonical_bytes(item) + b"\n" for item in [*rows, row]))
    os.replace(temporary, path)
    return row
