"""网络解锁检测接口：面板出口 / 指定节点两种模式 + 节点批量检测。"""
from collections import Counter
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from ..deps import CurrentUser, RequireCapabilities
from ..services import unlock_check, node_rename

router = APIRouter(prefix="/api/v1/unlock", tags=["unlock"])


def _regional_labels(conn, candidates):
    from .. import config
    rows = node_rename.regional_catalog(conn)
    present = {(row["source_id"], row["emit_name"]) for row in rows if not row.get("retired")}
    # 旧目录缺记录时，用原有节点身份补齐显示映射。
    for node in candidates:
        key = node.get("source_id"), node["name"]
        if key not in present:
            rows.append({"source_id": key[0], "emit_name": key[1], "display_name": key[1]})
            present.add(key)
    reserved = set(config.BUILTIN_TARGETS) | {config.GUARD_PROXY}
    reserved.update(row["name"] for row in conn.execute("SELECT name FROM proxy_groups"))
    names = node_rename.regional_names(rows, reserved)
    return {node["name"]: names[(node.get("source_id"), node["name"])] for node in candidates}


@router.get("/quality")
def quality(user=CurrentUser):
    from .. import db
    from ..services import node_catalog, quality_funnel, routing_planner, scheduler
    from ..services.probes.registry import ALL_DETECTORS

    candidates = scheduler._collect_probe_proxies()
    current = quality_funnel.current_results(candidates)
    names = [p["name"] for p in candidates]
    rows = [{k: v for k, v in (current.get(name) or {"name": name, "stage": "unknown"}).items()
             if k != "revision"} for name in names]
    with db.connect() as conn:
        auto = db.get_setting(conn, "probe_funnel_enabled", "0") == "1"
        scheduler_on = db.get_setting(conn, "scheduler_enabled", "1") == "1"
        config = quality_funnel._settings(conn)
        build_aliases = db.get_setting(conn, "probe_build_aliases", "1")
        labels = _regional_labels(conn, candidates)
        catalog = node_catalog.list_active_nodes(conn)
    origins = {r["emit_name"]: r for r in catalog if r["enabled"] and r["origin_kind"] == "local"}
    annotated = []
    for row in rows:
        origin = origins.get(row["name"])
        region = node_rename.detect_region(origin["raw_name"]) if origin else None
        annotated.append({**row, "origin_kind": "local" if origin else "source",
                          "country": {"🇺🇸": "US", "🇯🇵": "JP"}.get(region[0]) if region else None})
    now = int(time.time())
    earliest = now - config["refresh_seconds"]
    services = {}
    for service in (*routing_planner.MEDIA_NAMES, *routing_planner.AI_SERVICES):
        pool = routing_planner.service_candidates(annotated, service, earliest=earliest, latest=now)
        services[service] = {"count": len(pool), "nodes": [labels[item["name"]] for item in pool[:8]]}
    return {"items": [{**row, "probe_key": row["name"], "name": labels[row["name"]]} for row in rows], "counts": dict(Counter(r["stage"] for r in rows)),
            "routing_candidates": services,
            "task": scheduler.quality_task_status(), "auto": auto, "scheduler_on": scheduler_on,
            "thresholds": {"delay_ms": config["max_delay_ms"], "speed_bps": config["min_speed_bps"]},
            "settings": {
                "probe_max_delay_ms": config["max_delay_ms"],
                "probe_min_speed_bps": config["min_speed_bps"],
                "probe_speed_bytes": config["speed_bytes"],
                "probe_timeout_ms": round(config["timeout"] * 1000),
                "probe_speed_timeout_sec": config["speed_timeout"],
                "probe_concurrency": config["concurrency"],
                "probe_round_limit": config["round_limit"],
                "probe_retry": config["retry"],
                "probe_refresh_hours": config["refresh_seconds"] // 3600,
                "probe_platform_ids": config["platform_ids"],
                "probe_build_aliases": build_aliases,
            },
            "platforms": {pid: item.display_name for pid, item in ALL_DETECTORS.items()}}


@router.post("/quality/run", status_code=202)
def quality_run(user=RequireCapabilities("probe")):
    from ..services import scheduler, tester
    if not tester.core_status().get("available"):
        raise HTTPException(409, "请先在系统设置安装 Mihomo 核心")
    if not scheduler.start_quality_probe(user["username"]):
        raise HTTPException(409, "有检测正在运行，或两轮检测的间隔还未结束")
    return {"ok": True}


@router.post("/quality/export")
def quality_export(user=RequireCapabilities("reveal")):
    from .. import db, security
    from ..services import node_classes, quality_funnel, scheduler, tester
    candidates = scheduler._collect_probe_proxies()
    results = quality_funnel.current_results(candidates)
    if not any(item.get("qualified") for item in results.values()):
        raise HTTPException(409, "没有通过测速的节点")
    if not scheduler._auto_probe_lock.acquire(blocking=False):
        raise HTTPException(409, "正在检测节点，请完成后再导出")
    try:
        with db.connect() as conn:
            names = _regional_labels(conn, candidates)
        text = node_classes.export_pools(results, candidates, tester.validate_config, names=names)
    except node_classes.ClassifyError as exc:
        raise HTTPException(409, str(exc)) from None
    finally:
        scheduler._auto_probe_lock.release()
    with db.tx() as conn:
        security.audit(conn, user["username"], "export_node_quality", "node_quality",
                       detail={"count": sum(bool(i.get("qualified")) for i in results.values())})
    return Response(text, media_type="application/yaml",
                    headers={"Content-Disposition": "attachment; filename=magicpanel-node-pools.yaml",
                             "Cache-Control": "no-store"})


class RunBody(BaseModel):
    exit: str = "panel"
    ids: list[str] = Field(default_factory=list)


@router.get("/catalog")
def catalog(user=CurrentUser):
    return {"checks": [
        {"id": c["id"], "name": {"netflix_premium": "Netflix 非自制剧样本", "wikipedia": "维基百科"}.get(c["id"], c["name"]), "icon": c["icon"], "category": c["category"],
         "url": c.get("frame_url") or c["url"]}
        for c in unlock_check.CHECKS
    ], "categories": unlock_check.CATEGORY_NAMES}


@router.get("/last")
def last(exit: str = "panel", user=CurrentUser):
    return unlock_check.last_results(unlock_check.PANEL_EVIDENCE_CACHE if exit == "panel" else exit)


@router.post("/run")
def run(body: RunBody, user=RequireCapabilities("probe")):
    from ..services import scheduler
    if not scheduler._auto_probe_lock.acquire(blocking=False):
        raise HTTPException(409, "有检测正在运行，请稍后再试")
    try:
        if body.exit in ("panel", ""):
            return unlock_check.run_panel_evidence(body.ids)
        result = unlock_check.run_checks(body.exit, body.ids, operator=user["username"])
        from .. import db
        with db.connect() as conn:
            rows = db.all_(conn, "SELECT DISTINCT source_id FROM node_catalog WHERE emit_name=? AND retired=0",
                           (result["exit"],))
            names = (_regional_labels(conn, [{"name": result["exit"], "source_id": rows[0]["source_id"]}])
                     if len(rows) == 1 else {})
        for item in result["results"]:
            route = item.get("extra", {}).get("route") or {}
            if route.get("source") == "probe_connection":
                route["node"] = names.get(route.get("node"), route.get("node"))
                route["chain"] = [names.get(member, member) for member in route["chain"]]
        return result
    except LookupError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    finally:
        scheduler._auto_probe_lock.release()


class BatchBody(BaseModel):
    qty: int = Field(default=3, ge=1, le=3)
    ids: list[str] = Field(default_factory=list)


@router.post("/batch-detect")
def batch_detect(body: BatchBody, user=RequireCapabilities("probe")):
    """旧版手动检测与节点质量检测共用一个调度位。"""
    from ..services import scheduler

    def worker():
        unlock_check.run_batch(qty=body.qty, ids=body.ids or None, operator=user["username"])
        return {}

    if not scheduler._start_auto_probe("unlock-batch", worker):
        raise HTTPException(409, "有检测正在运行，或两轮检测的间隔还未结束")
    return {"ok": True, "started": True, "qty": body.qty}


@router.get("/batch-status")
def batch_status(user=CurrentUser):
    return unlock_check.batch_state()


@router.get("/capability-coverage")
def capability_coverage(user=CurrentUser):
    """解锁能力缓存覆盖率：构建页据此提示「产物里哪些节点还没有能力标记」。"""
    try:
        return unlock_check.coverage()
    except Exception as exc:
        raise HTTPException(500, f"统计解锁能力覆盖率失败：{exc}")


@router.get("/node-capabilities")
def node_capabilities(user=CurrentUser):
    """各节点的能力徽章（构建产物里节点名的徽章来源）。"""
    try:
        nodes = unlock_check.detectable_nodes()
    except Exception as exc:
        raise HTTPException(500, f"读取节点列表失败：{exc}")
    out = []
    for name in nodes:
        badges = unlock_check.capability_badges(name)
        out.append({"name": name, "badges": badges,
                    "tested": bool(badges) or bool(unlock_check._states_of(name))})
    return {"items": out, "total": len(out),
            "with_badges": sum(1 for i in out if i["badges"])}
