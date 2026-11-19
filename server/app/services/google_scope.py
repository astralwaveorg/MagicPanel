"""导出生产订阅的 Google 候选清单和建议线路，供观测端安排测量。"""
import argparse
import hashlib
import json
from datetime import datetime, timezone

import yaml

from .. import config, db, security
from . import google_evidence, node_rename
from .probe_observers import GOOGLE_PROBE_HOST_ALLOWLIST


def production_scope(conn, artifact, *, now):
    """读取生产产物的冻结范围，不读设备令牌或输出 YAML、代理参数。"""
    if not artifact or artifact in {".", ".."} or any(ch in artifact for ch in "/\\"):
        raise ValueError("google_artifact_invalid")
    build = db.one(conn, "SELECT id,snapshot,results FROM builds WHERE status='PRODUCTION'")
    if not build:
        raise ValueError("google_production_missing")
    result = json.loads(build["results"]).get(artifact)
    if not result or not result.get("ok"):
        raise ValueError("google_artifact_missing")
    content = (config.BUILDS_DIR / str(build["id"]) / f"{artifact}.yaml").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != result.get("sha256"):
        raise ValueError("google_artifact_digest_mismatch")
    cfg = yaml.safe_load(content)
    snapshot = json.loads(security.decrypt_payload(build["snapshot"]))
    if "regional_catalog" not in snapshot:
        raise ValueError("google_scope_unavailable")
    reserved = set(config.BUILTIN_TARGETS) | {config.GUARD_PROXY}
    reserved.update(group["name"] for group in snapshot["groups"])
    names = node_rename.regional_names(snapshot["regional_catalog"], reserved)
    scope = google_evidence.artifact_scope(cfg, snapshot["node_catalog"], names)
    if scope is None:
        raise ValueError("google_scope_unavailable")
    members, incomplete = scope
    current = {r["node_uid"]: r["current_revision"] for r in conn.execute(
        "SELECT node_uid,current_revision FROM node_catalog WHERE enabled=1 AND retired=0")}
    report = google_evidence.evaluate_scope(scope, google_evidence.observations(conn, now=now),
                                            evaluation_at=now)
    tiers = {}
    stale = False
    for tier, rows in members.items():
        candidates = []
        for uid, row in rows.items():
            unchanged = current.get(uid) == row["revision"]
            stale |= not unchanged
            candidates.append({"node_uid": uid, **row, "current_revision_matches": unchanged})
        tiers[tier] = sorted(candidates, key=lambda n: (n["origin_kind"] != "local", n["name"], n["node_uid"]))
    # 生产文件仍可能包含已退役节点。保留缺口，不能把当前目录当作完整的生产集合。
    recommendation = {key: report[key] for key in ("state", "tier", "candidate_uids")}
    if stale:
        recommendation.update(state="catalog_changed", tier=None, candidate_uids=[])
    return {
        "build_id": build["id"], "artifact": artifact, "artifact_sha256": digest,
        "scope_sha256": report["scope_sha"], "scope_complete": not incomplete and not stale,
        "hosts": sorted(GOOGLE_PROBE_HOST_ALLOWLIST), "tiers": tiers,
        "coverage": report["coverage"], "recommendation": recommendation,
    }


def main():
    parser = argparse.ArgumentParser(description="导出生产订阅的 Google 观测范围")
    parser.add_argument("artifact", help="构建详情中的产物名，不带 .yaml")
    args = parser.parse_args()
    try:
        with db.connect() as conn:
            conn.execute("BEGIN")
            result = production_scope(conn, args.artifact, now=datetime.now(timezone.utc))
    except (ValueError, OSError, TypeError, KeyError, yaml.YAMLError) as exc:
        code = str(exc)
        parser.exit(1, code + "\n" if code in {
            "google_artifact_invalid", "google_production_missing", "google_artifact_missing",
            "google_artifact_digest_mismatch", "google_scope_unavailable",
        } else "google_scope_unavailable\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
