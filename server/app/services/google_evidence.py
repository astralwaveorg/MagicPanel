"""从已验证观测路径读入 Google 业务证据。基础连通探针不能进入选路。"""

import json
from datetime import datetime, timedelta

from .google_receipts import verify as verify_receipt
from .probe_observers import verified_proof
from .. import config
from .routing_planner import GOOGLE_TIERS, _time, qualify_google_manifest

GOOGLE_GROUP = "🔍 谷歌服务"
TIER_GROUPS = dict(zip(GOOGLE_TIERS, ("🇺🇸 Google 美国候选", "🇸🇬 新加坡自动", "🇯🇵 日本自动")))


def public_report(report):
    """构建详情只公开固定状态和计数，不暴露探测原始数据。"""
    if not isinstance(report, dict) or report.get("state") not in (
        "scope_incomplete", "usable", "all_failed", "needs_review",
    ):
        return None
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        return None
    counters = ("total", "observed-ok", "confirmed-blocked", "unknown", "missing")
    public = {}
    for region in GOOGLE_TIERS:
        counts = coverage.get(region)
        if not isinstance(counts, dict):
            return None
        values = {key: counts.get(key, 0) for key in counters}
        if (any(type(value) is not int or value < 0 for value in values.values())
                or "total" not in counts
                or values["total"] != sum(values[key] for key in counters[1:])):
            return None
        public[region] = values
    tier = report.get("tier")
    return {"state": report["state"], "tier": tier if tier in GOOGLE_TIERS else None,
            "coverage": public}


def artifact_scope(cfg, catalog, regional_plan):
    """只收录实际下发、可映射到唯一节点版本的候选。"""
    groups = {group["name"]: group for group in cfg.get("proxy-groups", [])}
    if GOOGLE_GROUP not in groups:
        return None
    proxies = {proxy["name"] for proxy in cfg.get("proxies", [])}
    by_name = {}
    for row in catalog:
        label = regional_plan.get((row.get("source_id"), row["emit_name"]))
        if label in proxies:
            by_name.setdefault(label, []).append(row)

    def leaves(name, ancestors=()):
        if name == config.GUARD_PROXY:
            return set(), False
        if name in ancestors:
            return set(), True
        if name in groups:
            group = groups[name]
            incomplete = bool(group.get("use") or group.get("include-all"))
            names = set()
            for child in group.get("proxies", []):
                found, missing = leaves(child, (*ancestors, name))
                names.update(found)
                incomplete |= missing
            return names, incomplete
        if len(by_name.get(name, [])) == 1:
            return {name}, False
        return set(), True

    top = groups[GOOGLE_GROUP]
    incomplete = (top.get("proxies", []) != list(TIER_GROUPS.values())
                  or bool(top.get("use") or top.get("include-all")))
    members = {}
    seen = set()
    for tier, group in TIER_GROUPS.items():
        names, missing = leaves(group)
        incomplete |= missing
        members[tier] = {by_name[name][0]["node_uid"]: {
            "name": name,
            "revision": by_name[name][0]["revision"],
            "origin_kind": by_name[name][0]["origin_kind"],
        } for name in sorted(names)}
        incomplete |= bool(seen.intersection(members[tier])) or len(members[tier]) != len(names)
        seen.update(members[tier])
    return members, incomplete


def evaluate_scope(scope, samples, *, evaluation_at):
    members, incomplete = scope
    # 名称可以修改，报告的范围指纹只绑定节点 ID 与版本。
    members = {tier: {uid: {k: v for k, v in node.items() if k != "name"}
                      for uid, node in rows.items()} for tier, rows in members.items()}
    report = qualify_google_manifest(members, samples, evaluation_at=evaluation_at)
    if incomplete:
        report.update(state="scope_incomplete", tier=None, candidate_uids=[], exhaustion=[])
    return report


def artifact_report(cfg, catalog, regional_plan, samples, *, evaluation_at):
    """按产物中的实际组成员统计证据；诊断结果不改写客户端线路。"""
    scope = artifact_scope(cfg, catalog, regional_plan)
    if scope is None:
        return None
    report = evaluate_scope(scope, samples, evaluation_at=evaluation_at)
    return {key: report[key] for key in ("state", "tier", "coverage")}


def observations(conn, *, now: datetime) -> list[dict]:
    rows = conn.execute("""
        SELECT i.node_uid, i.node_revision, r.result_state, r.egress_json, r.evidence_json,
               r.measured_at, r.valid_until, p.qualified_at, p.expires_at, p.contract_json,
               o.config_revision, o.public_key, o.id AS observer_id, p.proof_json, r.path_epoch
        FROM probe_results r JOIN probe_items i ON i.id=r.item_id
        JOIN probe_jobs j ON j.id=i.job_id AND j.observer_id=r.observer_id
        JOIN probe_paths p ON p.observer_id=r.observer_id AND p.epoch=r.path_epoch
        JOIN probe_observers o ON o.id=r.observer_id
        JOIN probe_adapter_health a ON a.probe_id=r.probe_id AND a.probe_version=r.probe_version
        WHERE i.service_key='google:critical' AND i.state='completed'
          AND j.cancel_requested=0 AND p.state='verified' AND o.enabled=1
          AND o.kind!='fixture' AND a.state='healthy'
          AND r.probe_id='google-critical' AND r.probe_version='v1'
        ORDER BY r.measured_at, r.id
        """)
    accepted = []
    for r in rows:
        try:
            egress, evidence, contract = (json.loads(r[key]) for key in
                                          ("egress_json", "evidence_json", "contract_json"))
            received, valid, qualified, expires = (_time(r[key]) for key in
                                                     ("measured_at", "valid_until", "qualified_at", "expires_at"))
            receipt = evidence.get("receipt")
            confirmed = verify_receipt(receipt, evidence.get("signature"), r["public_key"])
            if not confirmed:
                continue
            measured, country, signed_state = confirmed
            if (not all((received, valid, qualified, expires))
                    or not qualified <= measured <= received <= now < min(expires, valid, measured + timedelta(hours=24))
                    or (received - measured).total_seconds() > 300
                    or not verified_proof(r["observer_id"], r["public_key"], contract, json.loads(r["proof_json"]))
                    or contract.get("config_revision") != r["config_revision"]
                    or "google" not in contract.get("scopes", [])
                    or egress.get("scope") != "google" or egress.get("verified") is not True
                    or egress.get("country") != country or r["result_state"] != signed_state
                    or any(receipt[key] != r[key] for key in
                           ("observer_id", "node_uid", "node_revision", "path_epoch"))):
                continue
            state = "confirmed-blocked" if signed_state == "blocked" else signed_state
            accepted.append({"node_uid": r["node_uid"], "revision": r["node_revision"],
                             "country": country, "measured_at": measured.isoformat(),
                             "valid_until": min(expires, valid).isoformat(), "state": state,
                             "egress_verified": True, "control_ok": True})
        except (TypeError, ValueError, AttributeError):
            continue
    return accepted
