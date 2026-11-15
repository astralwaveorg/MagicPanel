"""安全准备：加密验读备份后，仅暂存惰性文件及冻结已识别更新调度。"""
from __future__ import annotations

import hashlib
import base64
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile

from cryptography.fernet import Fernet, InvalidToken

from scripts.ops.contracts import OPERATION_REGISTRY
from scripts.ops.evidence import (
    ZERO_SHA, append_journal, canonical_bytes, digest, journal_head, private_path,
    private_write, run_lock, verified_proofs, write_proof,
)
from scripts.ops.phase_guard import authorize_operation

ROOT = Path(__file__).resolve().parents[2]
OPERATION_ID = "router.safe_preparation"
_UPDATE_FIELDS = frozenset(("auto_update", "geo_auto_update", "geoip_auto_update",
                            "geosite_auto_update", "chnr_auto_update"))
_UPDATERS = frozenset(("/usr/share/openclash/openclash.sh",
                       "/usr/share/openclash/openclash_geo.sh",
                       "/usr/share/openclash/openclash_chnroute.sh"))
_REQUIRED_INVARIANTS = (
    "dns_sha", "wan_lan_sha", "udp_v6_cn_sha", "core_pid", "core_started_at",
    "subscription_sha", "geo_sha", "firewall_sha", "routes_sha", "forwarding_sha",
)
_BACKUP_COMPONENTS = frozenset(("uci", "openclash", "agh", "dnsmasq", "crontab",
                               "subscription_raw", "subscription_cache", "geo_versions",
                               "firewall", "routes", "runtime"))
_VOLATILE = frozenset(("collected_at", "packet_count", "byte_count", "uptime_seconds", "connections_sha"))
_SAFE_SUMMARIES = frozenset(("private_backup_sha", "inert_files_sha", "update_schedule_sha"))
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SECTION = re.compile(r"openclash\.(?:[A-Za-z_][A-Za-z0-9_]*|@config_subscribe\[\d+\])\Z")
_SNAPSHOT_FIELDS = frozenset(_REQUIRED_INVARIANTS) | _VOLATILE | _SAFE_SUMMARIES | {
    "role", "adapter", "phase", "uci", "crontab", "backup_components", "predecessor",
    "uci_pending", "updaters_running", "schedule_requires_reload",
}


class SafePreparationError(ValueError):
    pass


def source_digests() -> dict:
    paths = ("scripts/ops/contracts.py", "scripts/ops/phase_guard.py", "scripts/ops/evidence.py",
             "scripts/ops/safe_preparation.py", "scripts/v2_acceptance.py", "ops/router/safe_prepare.sh")
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def _unquote(value):
    if not isinstance(value, str):
        return value
    try:
        parts = shlex.split(value)
        return parts[0] if len(parts) == 1 else value
    except ValueError:
        return value


def _schedule_keys(uci):
    if not isinstance(uci, dict):
        return []
    keys = {f"openclash.config.{name}" for name in _UPDATE_FIELDS}
    keys.update(f"{section}.auto_update" for section, kind in uci.items()
                if _SECTION.fullmatch(section) and _unquote(kind) == "config_subscribe")
    return sorted(key for key in keys if key in uci)


def _cron_tokens(command):
    words, token, quote, active, escaped = [], "", "", False, False
    for char in command:
        if escaped:
            token += char
            escaped = False
        elif char == "\\" and quote != "'":
            escaped, active = True, True
        elif quote:
            if char == quote:
                quote = ""
            else:
                token += char
        elif char in ("'", '"'):
            quote, active = char, True
        elif char == "#" and not active:
            break
        elif char.isspace():
            if active:
                words.append(token)
            token, active = "", False
        else:
            token, active = token + char, True
    if quote or escaped:
        raise SafePreparationError("UNRECOGNIZED_CRON")
    if active:
        words.append(token)
    return words


def _valid_update_arguments(script, arguments):
    if arguments[-2:] == [">/dev/null", "2>&1"]:
        arguments = arguments[:-2]
    elif arguments[-3:] == [">", "/dev/null", "2>&1"]:
        arguments = arguments[:-3]
    if script.endswith("/openclash_chnroute.sh"):
        return not arguments
    if script.endswith("/openclash_geo.sh"):
        return not arguments or arguments in (["ipdb"], ["geosite"], ["geoip"])
    if not arguments:
        return True
    name = arguments[0]
    valid_name = (0 < len(name.encode("utf-8")) <= 128 and
                  re.fullmatch(r"[A-Za-z0-9_. +\-\u0080-\U0010ffff]+", name) is not None)
    return bool(valid_name and (len(arguments) == 1 or (
        len(arguments) == 3 and arguments[1] == "loop" and
        re.fullmatch(r"[1-9][0-9]{0,8}", arguments[2]))))


def freeze_cron(text: str) -> str:
    """只识别直接调用更新器的独立任务，复杂 shell 语句拒绝猜测。"""
    if not isinstance(text, str):
        raise SafePreparationError("INVALID_CRONTAB")
    lines = []
    for line in text.splitlines(keepends=True):
        if not line.strip() or line.lstrip().startswith("#"):
            lines.append(line)
            continue
        match = re.match(r"\s*(?:\S+\s+){5}(.+?)\s*$", line)
        if line.lstrip().startswith("@"):
            match = re.match(r"\s*@\w+\s+(.+?)\s*$", line)
        if not match:
            raise SafePreparationError("UNRECOGNIZED_CRON")
        command = match[1]
        words = _cron_tokens(command)
        index = 1 if words and words[0] == "exec" else 0
        if len(words) > index and words[index] in ("sh", "ash", "bash", "/bin/sh", "/bin/ash", "/bin/bash"):
            index += 1
        direct_update = len(words) > index and words[index] in _UPDATERS
        mentioned_update = any(path in command for path in _UPDATERS)
        if direct_update:
            # 参数仅作语法识别；原始任务整行注释，绝不求值或执行。
            if not _valid_update_arguments(words[index], words[index + 1:]):
                raise SafePreparationError("MIXED_UPDATE_CRON")
            lines.append("# magicpanel-safe-preparation " + line)
        elif mentioned_update and (not words or words[0] not in ("echo", "/bin/echo")):
            raise SafePreparationError("MIXED_UPDATE_CRON")
        else:
            lines.append(line)
    return "".join(lines)


def _schedule(snapshot):
    uci = snapshot.get("uci", {})
    changes = []
    for key in _schedule_keys(uci):
        before = _unquote(uci[key])
        if before not in ("0", "1"):
            raise SafePreparationError("INVALID_UPDATE_FIELD")
        if before != "0":
            changes.append({"key": key, "before": uci[key], "after": "0"})
    return {"adapter": "openclash_v1", "uci": changes,
            "crontab_before_sha": digest(snapshot.get("crontab", "")),
            "crontab_after": freeze_cron(snapshot.get("crontab", ""))}


def validate_safe_diff(before: dict, after: dict) -> list[str]:
    errors = []
    for key in sorted(set(before) | set(after)):
        if key in _VOLATILE | _SAFE_SUMMARIES or key == "backup_components":
            continue
        if key not in before or key not in after:
            errors.append("SAFE_INVARIANT_CHANGED")
            continue
        if key == "uci":
            expected = dict(before[key])
            actual = dict(after[key])
            for name in _schedule_keys(before[key]):
                expected[name] = "0" if _unquote(expected[name]) == "1" else _unquote(expected[name])
                if name in actual:
                    actual[name] = _unquote(actual[name])
            if after[key] != before[key] and actual != expected:
                errors.append("SAFE_INVARIANT_CHANGED")
        elif key == "crontab":
            try:
                valid = after[key] in (before[key], freeze_cron(before[key]))
            except SafePreparationError:
                valid = False
            if not valid:
                errors.append("SAFE_INVARIANT_CHANGED")
        elif before[key] != after[key]:
            errors.append("SAFE_INVARIANT_CHANGED")
    return sorted(set(errors))


def _stable_snapshot(snapshot):
    return {k: v for k, v in snapshot.items()
            if k not in _VOLATILE and k not in ("backup_components", "predecessor")}


def prepare_safe_plan(snapshot: dict, *, rescue_files: list[dict]) -> dict:
    blockers = []
    if set(snapshot) - _SNAPSHOT_FIELDS:
        blockers.append("UNRECOGNIZED_SNAPSHOT_FIELD")
    if snapshot.get("role") != "router":
        blockers.append("ROUTER_INVENTORY_REQUIRED")
    if snapshot.get("adapter") != "openclash_v1":
        blockers.append("UNSUPPORTED_SCHEDULE_ADAPTER")
    if any(key not in snapshot or snapshot[key] is None for key in _REQUIRED_INVARIANTS):
        blockers.append("COMPLETE_BASELINE_REQUIRED")
    if snapshot.get("schedule_requires_reload") is not False:
        blockers.append("SCHEDULE_RELOAD_REQUIRED")
    if snapshot.get("uci_pending") != []:
        blockers.append("PENDING_UCI_CHANGES")
    if snapshot.get("updaters_running") is not False:
        blockers.append("UPDATER_ALREADY_RUNNING")
    backup = snapshot.get("backup_components")
    if not isinstance(backup, dict) or not _BACKUP_COMPONENTS <= backup.keys() or any(
            not backup[key] for key in _BACKUP_COMPONENTS & (backup or {}).keys()):
        blockers.append("BACKUP_COMPONENTS_REQUIRED")
    files = []
    names = set()
    if not isinstance(rescue_files, list):
        blockers.append("INVALID_RESCUE_FILE")
        rescue_files = []
    for item in rescue_files:
        if (not isinstance(item, dict) or set(item) != {"name", "content"} or
                not isinstance(item["name"], str) or not _FILENAME.fullmatch(item["name"]) or
                item["name"] in names or not isinstance(item["content"], str) or
                len(item["content"].encode("utf-8")) > 1024 * 1024):
            blockers.append("INVALID_RESCUE_FILE")
            continue
        names.add(item["name"])
        files.append({**item, "sha256": hashlib.sha256(item["content"].encode("utf-8")).hexdigest(),
                      "mode": "0600", "execute": False, "register_service": False})
    try:
        schedule = _schedule(snapshot)
    except SafePreparationError as exc:
        blockers.append(str(exc))
        schedule = {}
    phase = snapshot.get("phase", "PRE_NETWORK")
    blockers.extend(authorize_operation(OPERATION_REGISTRY[OPERATION_ID], phase,
                                         {"safe_backup_verified": True}))
    plan = {"schema": 1, "operation": OPERATION_REGISTRY[OPERATION_ID], "phase": phase,
            "snapshot_sha": digest(_stable_snapshot(snapshot)),
            "baseline": {key: snapshot[key] for key in _REQUIRED_INVARIANTS if key in snapshot},
            "schedule": schedule, "rescue_files": files,
            "actions": ["private_backup.verify", "inert_rescue.stage", "update_schedule.freeze"],
            "sources": source_digests(), "predecessor": snapshot.get("predecessor", ZERO_SHA),
            "blockers": sorted(set(blockers))}
    return {**plan, "plan_sha": digest(plan)}


def _verified_backup(snapshot, proof_dir, plan):
    body = canonical_bytes(snapshot)
    key = Fernet.generate_key()
    private_write(proof_dir / "backup.key", key)
    private_write(proof_dir / "safe-backup.enc", Fernet(key).encrypt(body))
    try:
        readback = Fernet((proof_dir / "backup.key").read_bytes()).decrypt(
            (proof_dir / "safe-backup.enc").read_bytes())
        if readback != body or digest(json.loads(readback)) != digest(snapshot):
            raise SafePreparationError("BACKUP_READBACK_FAILED")
    except (InvalidToken, OSError, ValueError):
        raise SafePreparationError("BACKUP_READBACK_FAILED") from None
    write_proof(proof_dir, "safe_backup", operation_id=OPERATION_ID,
                plan_sha=plan["plan_sha"], predecessor=plan["predecessor"],
                claims={"safe_backup_verified": True},
                evidence_hashes={name: hashlib.sha256((proof_dir / name).read_bytes()).hexdigest()
                                 for name in ("safe-backup.enc", "backup.key")})


def _schedule_is_frozen(snapshot, schedule):
    return (all(_unquote(snapshot.get("uci", {}).get(item["key"])) == "0"
                for item in schedule["uci"]) and
            snapshot.get("crontab") == schedule["crontab_after"] and
            snapshot.get("uci_pending") == [] and snapshot.get("updaters_running") is False)


def apply_safe_preparation(plan: dict, *, runner, proof_dir: Path) -> dict:
    proof_dir = private_path(Path(proof_dir))
    with run_lock(proof_dir):
        before = runner.capture()
        # 重建全部 actions/effects/源码摘要，重新散列不能替代固定定义校验。
        try:
            rescue_files = [{"name": item["name"], "content": item["content"]}
                            for item in plan["rescue_files"]]
            expected = prepare_safe_plan({**before, "predecessor": journal_head(proof_dir)},
                                         rescue_files=rescue_files)
        except (KeyError, TypeError):
            raise SafePreparationError("PLAN_DEFINITION_MISMATCH") from None
        if plan != expected:
            raise SafePreparationError("PLAN_DEFINITION_MISMATCH")
        if plan["blockers"]:
            raise SafePreparationError("SAFE_PREFLIGHT_BLOCKED")
        if journal_head(proof_dir) != plan["predecessor"]:
            raise SafePreparationError("PREDECESSOR_MISMATCH")
        if hasattr(runner, "bind_plan"):
            runner.bind_plan(plan)
        try:
            _verified_backup(before, proof_dir, plan)
        except Exception:
            append_journal(proof_dir, operation_id=OPERATION_ID, phase=plan["phase"],
                           plan_sha=plan["plan_sha"], state="blocked", predecessor=plan["predecessor"])
            raise SafePreparationError("BACKUP_READBACK_FAILED") from None
        proofs = verified_proofs(proof_dir, operation_id=OPERATION_ID,
                                  plan_sha=plan["plan_sha"], predecessor=plan["predecessor"])
        if authorize_operation(plan["operation"], plan["phase"], proofs):
            raise SafePreparationError("SAFE_BACKUP_REQUIRED")
        staged = {"created": []}
        state, blockers = "verified", []
        try:
            # runner 必须在每次写之前再次核对设备状态，回退仅负责本次变更。
            staged = runner.stage_rescue(plan["rescue_files"])
            runner.freeze_updates(plan["schedule"])
            after = runner.capture()
            blockers = validate_safe_diff(before, after)
            if not _schedule_is_frozen(after, plan["schedule"]):
                blockers.append("UPDATE_SCHEDULE_NOT_FROZEN")
            if blockers:
                raise SafePreparationError("SAFE_INVARIANT_CHANGED")
        except Exception:
            if not blockers:
                blockers = ["SAFE_PREPARATION_APPLY_FAILED"]
            try:
                runner.restore_owned(before=before, applied=plan["schedule"], staged=staged)
                restored = runner.capture()
                # 不自动回滚任何网络漂移；留给单独受控恢复。
                state = "rolled_back" if _stable_snapshot(restored) == _stable_snapshot(before) else "rollback_required"
            except Exception:
                state = "rollback_required"
                blockers.append("OWNED_ROLLBACK_FAILED")
        receipt = append_journal(proof_dir, operation_id=OPERATION_ID, phase=plan["phase"],
                                 plan_sha=plan["plan_sha"], state=state,
                                 predecessor=plan["predecessor"])
        return {"state": state, "plan_sha": plan["plan_sha"], "receipt_sha": receipt["receipt_sha"],
                "blockers": sorted(set(blockers)), "network_fault_matrix_verified": False}


def _without_counters(value):
    if isinstance(value, dict):
        return {key: _without_counters(item) for key, item in value.items()
                if key not in ("counter", "packets", "bytes", "expires", "used")}
    if isinstance(value, list):
        return [_without_counters(item) for item in value]
    return value


def _route_semantics(value):
    if isinstance(value, dict):
        return {key: _route_semantics(item) for key, item in value.items() if key != "expires"}
    if isinstance(value, list):
        return [_route_semantics(item) for item in value]
    return value


def _dns_listeners(text):
    identities = set()
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in ("tcp", "tcp6", "udp", "udp6"):
            continue
        if len(fields) < 5:
            raise SafePreparationError("INCOMPLETE_LISTENER_CAPTURE")
        address, separator, port = fields[3].rpartition(":")
        if not separator or port not in ("53", "5353", "7874"):
            continue
        if fields[0].startswith("tcp") and fields[-1] != "LISTEN":
            continue
        identities.add((fields[0], address.strip("[]"), int(port)))
    return sorted(identities)


class LocalRouterRunner:
    """只在inventory绑定的本机OpenWrt执行固定脚本；无远程传输入口。"""
    def __init__(self, inventory: dict):
        if (set(inventory) - {"schema", "role", "transport", "board_sha", "snapshot", "rescue_files"} or
                inventory.get("schema") != 1 or inventory.get("role") != "router" or
                inventory.get("transport") != "local_router" or
                not re.fullmatch(r"[0-9a-f]{64}", inventory.get("board_sha", ""))):
            raise SafePreparationError("INVALID_LOCAL_ROUTER_INVENTORY")
        if os.name != "posix" or not Path("/etc/openwrt_release").is_file():
            raise SafePreparationError("LOCAL_OPENWRT_REQUIRED")
        if hashlib.sha256(Path("/etc/board.json").read_bytes()).hexdigest() != inventory["board_sha"]:
            raise SafePreparationError("ROUTER_IDENTITY_MISMATCH")
        self.inventory = inventory
        self.script = ROOT / "ops/router/safe_prepare.sh"
        self.plan = None
        self.before = None
        self.staged = []

    def _call(self, action, *args, body=None):
        try:
            result = subprocess.run(["/bin/sh", str(self.script), action, *args], input=body,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=180, check=False,
                                    env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
        except (OSError, subprocess.TimeoutExpired):
            raise SafePreparationError("FIXED_ROUTER_ADAPTER_FAILED") from None
        if result.returncode:
            raise SafePreparationError("FIXED_ROUTER_ADAPTER_FAILED")
        return result.stdout

    def capture(self):
        archive = self._call("capture")
        observed = {}
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
                for member in tar:
                    if member.isfile() and member.name.startswith("observed/"):
                        if member.size > 64 * 1024 * 1024:
                            raise SafePreparationError("COLLECTOR_OUTPUT_TOO_LARGE")
                        observed[member.name.removeprefix("observed/")] = tar.extractfile(member).read()
                openclash_archive = tar.extractfile("files/openclash.tar").read()
            text = lambda name: observed[name].decode("utf-8")
            uci = dict(line.split("=", 1) for line in text("uci.txt").splitlines() if line)
            core = sorted([int(line.split()[0]), line.split()[1]]
                          for line in text("core.txt").splitlines())
            nft = _without_counters(json.loads(text("nft.json")))
            paths = {}
            with tarfile.open(fileobj=io.BytesIO(openclash_archive), mode="r:") as tar:
                for member in tar:
                    if member.isfile():
                        paths[member.name] = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            configs = {name: value for name, value in paths.items()
                       if name.endswith((".yaml", ".yml", ".mrs"))}
            geo = {name: value for name, value in paths.items() if name.endswith((".dat", ".mmdb"))}
            if not configs or not geo:
                raise SafePreparationError("RAW_CACHE_GEO_BACKUP_REQUIRED")
            # conntrack的超时、字节、计数器不参与不变量摘要。
            connections = sorted(" ".join(re.findall(
                r"(?:src|dst|sport|dport|zone|id)=[^\s]+", line))
                for line in text("connections.txt").splitlines())
            snapshot = {
                "role": "router", "adapter": "openclash_v1", "phase": "PRE_NETWORK",
                "dns_sha": digest([text("dhcp.txt"), text("agh.txt"), _dns_listeners(text("listeners.txt"))]),
                "wan_lan_sha": digest(text("network.txt")),
                "udp_v6_cn_sha": digest([nft, text("rules4.json"), text("rules6.json")]),
                "core_pid": [item[0] for item in core], "core_started_at": [item[1] for item in core],
                "subscription_sha": digest(configs), "geo_sha": digest(geo),
                "firewall_sha": digest([nft, text("firewall_config.txt")]),
                "routes_sha": digest([_route_semantics(json.loads(text("routes4.json"))),
                                      _route_semantics(json.loads(text("routes6.json")))]),
                "forwarding_sha": digest(text("forwarding.txt")),
                "connections_sha": digest(connections), "uci_pending": text("pending.txt").splitlines(),
                "updaters_running": bool(re.search(
                    r"/usr/share/openclash/openclash(?:_geo|_chnroute)?\.sh(?:\s|$)", text("processes.txt"))),
                "schedule_requires_reload": False, "uci": uci, "crontab": text("crontab.txt"),
                "backup_components": {"uci": text("uci.txt"), "openclash": paths,
                    "agh": text("agh.txt"), "dnsmasq": text("dhcp.txt"),
                    "crontab": text("crontab.txt") or "empty-crontab",
                    "subscription_raw": configs, "subscription_cache": configs, "geo_versions": geo,
                    "firewall": nft, "routes": text("routes4.json"), "runtime": core,
                    "listeners": text("listeners.txt"),
                    "archive_b64": base64.b64encode(archive).decode("ascii"),
                    "openclash_config_sha": hashlib.sha256(observed["openclash.txt"]).hexdigest()},
            }
        except (KeyError, ValueError, tarfile.TarError, AttributeError):
            raise SafePreparationError("INCOMPLETE_ROUTER_CAPTURE") from None
        return snapshot

    def bind_plan(self, plan):
        if plan["sources"] != source_digests():
            raise SafePreparationError("HANDLER_SOURCE_CHANGED")
        self.plan = plan
        self.before = self.capture()
        if self.before and digest(_stable_snapshot(self.before)) != plan["snapshot_sha"]:
            raise SafePreparationError("BASELINE_CHANGED")

    def stage_rescue(self, files):
        if self.plan is None:
            raise SafePreparationError("PLAN_NOT_BOUND")
        for item in files:
            # 先记尝试，短写/管道失败时也能按预期hash进行有限清理。
            self.staged.append(item)
            self._call("stage", self.plan["plan_sha"], item["name"], item["sha256"],
                       body=item["content"].encode("utf-8"))
        return {"created": [item["name"] for item in self.staged]}

    def freeze_updates(self, changes):
        if self.plan is None or changes != self.plan["schedule"]:
            raise SafePreparationError("PLAN_NOT_BOUND")
        current = self.capture()
        if digest(_stable_snapshot(current)) != self.plan["snapshot_sha"]:
            raise SafePreparationError("BASELINE_CHANGED")
        config_sha = current["backup_components"]["openclash_config_sha"]
        cron_sha = hashlib.sha256(current["crontab"].encode("utf-8")).hexdigest()
        self._call("freeze", self.plan["plan_sha"], config_sha, cron_sha)

    def restore_owned(self, *, before, applied, staged):
        if self.plan is None:
            raise SafePreparationError("PLAN_NOT_BOUND")
        errors = []
        try:
            self._call("restore", self.plan["plan_sha"])
        except SafePreparationError:
            errors.append("SCHEDULE_ROLLBACK_REQUIRED")
        for item in self.staged:
            try:
                self._call("unstage", self.plan["plan_sha"], item["name"], item["sha256"])
            except SafePreparationError:
                errors.append("INERT_ROLLBACK_REQUIRED")
        if errors:
            raise SafePreparationError("OWNED_ROLLBACK_FAILED")
