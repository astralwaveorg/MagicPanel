"""构建与版本发布（状态机）。

构建把当前策略固化为不可变快照并逐目标渲染；发布按状态机切换
版本状态（已构建 / 测试中 / 生产中 / 已下线），失败或空结果不会覆盖现网。
"""
import json
from pathlib import Path
from datetime import datetime, timezone
import shutil
import time
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..compiler import render, validate
from ..deps import CurrentUser, RequireCapabilities
from ..services import base_config as base_config_service
from ..services import runtime_profiles
from ..services import google_evidence, publish_gate, releases, node_catalog, node_rename
from ..services import source_nodes as source_node_service
from ..services import tester

router = APIRouter(prefix="/api/v1", tags=["builds"])


def collect_snapshot(conn, *, regional: bool = False) -> dict:
    sources = []
    for r in db.all_(conn, "SELECT * FROM sources ORDER BY id"):
        mode = r["mode"] if "mode" in r.keys() else config.SOURCE_MODE_PROVIDER
        item = {"source_id": r["id"], "name": r["name"], "enabled": bool(r["enabled"]),
                "filter": r["filter"], "ua": r["ua"],
                "suffix": (r["suffix"] if "suffix" in r.keys() else ""),
                "interval": r["interval"],
                "client_interval": r["client_interval"], "mode": mode}
        if (regional or mode == config.SOURCE_MODE_INLINE) and r["enabled"] and r["snapshot_enc"]:
            # 内联来源：节点定义随快照进入构建快照。机场换节点后策略指纹会变，
            # 自动构建才会把新节点重新下发（内联模式下客户端不再自己拉 provider）。
            item["nodes"] = source_node_service.parse(
                security.decrypt_text(r["snapshot_enc"]))
        if r["filter_unavailable"]:
            # 「只分发可用节点」：provider 模式在 feed 端过滤，内联模式没有
            # provider 可过滤，必须在构建时把测速失败的节点剔掉，否则这个开关
            # 在内联模式下会静默失效。
            results = json.loads(r["test_results"] or "{}")
            item["excluded_nodes"] = sorted(
                name for name, delay in results.items() if delay < 0)
        sources.append(item)
    rule_providers = [
        {"name": r["name"], "behavior": r["behavior"], "format": r["format"],
         "kind": r["kind"], "interval": r["interval"],
         "client_interval": r["client_interval"], "enabled": bool(r["enabled"]),
         # 内容指纹进快照：规则内容变了策略指纹就变，自动构建才会重新下发。
         # （规则来源的 content 以前不进快照，改了规则不触发自动构建。）
         "content_sha": security.sha256_text(r["content"] or "")}
        for r in db.all_(conn, "SELECT * FROM rule_providers ORDER BY id")
    ]
    local_nodes = [
        {"id": r["id"], "name": r["name"], "node_type": r["node_type"] or "",
         "protocol": r["protocol"],
         "server": r["server"], "port": r["port"],
         "params": json.loads(security.decrypt_text(r["params_enc"]) if r["params_enc"] else "{}"),
         "extra_yaml": security.decrypt_text(r["extra_yaml_enc"]) if r["extra_yaml_enc"] else "",
         "enabled": bool(r["enabled"])}
        for r in db.all_(conn, "SELECT * FROM local_nodes ORDER BY sort, id")
    ]
    groups = [
        {"id":r["id"], "members_format":r["members_format"],
         "members_v2":json.loads(r["members_v2"]),
         "variant_id": int(r["variant_id"] or 0) if "variant_id" in r.keys() else 0,
         "name": r["name"], "type": r["type"], "hidden": bool(r["hidden"]),
         "filter": r["filter"], "use_sources": json.loads(r["use_sources"] or "[]"),
         "local_nodes": json.loads(r["local_nodes"] or "[]"),
         "proxies": json.loads(r["proxies"] or "[]"), "url": r["url"],
         "targets": json.loads(r["targets"] or "[]"),
         "devices": json.loads(r["devices"] or "[]") if "devices" in r.keys() else [],
         "local_first": bool(r["local_first"]) if "local_first" in r.keys() else False,
         "interval": r["interval"], "timeout": r["timeout"],
         "tolerance": r["tolerance"], "lazy": bool(r["lazy"]),
         "strategy": r["strategy"]}
        for r in db.all_(conn, "SELECT * FROM proxy_groups ORDER BY sort, id")
    ]
    rules = [
        {"id":r["id"], "target_ref_v2":json.loads(r["target_ref_v2"]),
         "variant_id": int(r["variant_id"] or 0) if "variant_id" in r.keys() else 0,
         "type": r["type"], "value": r["value"], "target": r["target"],
         "enabled": bool(r["enabled"]), "no_resolve": bool(r["no_resolve"]),
         "no_track": bool(r["no_track"]) if "no_track" in r.keys() else False,
         "pre_matching": bool(r["pre_matching"]) if "pre_matching" in r.keys() else False,
         "targets": json.loads(r["targets"] or "[]"),
         "devices": json.loads(r["devices"] or "[]") if "devices" in r.keys() else []}
        for r in db.all_(conn, "SELECT * FROM rules ORDER BY sort, id")
    ]
    catalog = node_catalog.list_active_nodes(conn)
    selected_uids = {ref['ref'] for group in groups if group['members_format'] == 'typed-v2'
                     for ref in group['members_v2'] if ref.get('kind') == 'node'}
    node_materials = []
    for entry in catalog:
        if entry['origin_kind'] == 'source' and entry['node_uid'] in selected_uids:
            proxy = node_catalog.load_probe_material(conn,entry['node_uid'],entry['revision'])
            proxy['name'] = entry['emit_name']
            node_materials.append({'node_uid':entry['node_uid'],'revision':entry['revision'],'proxy':proxy})
    targets = [
        {"id": int(r["id"]), "name": r["name"], "engine": r["engine"],
         "platform": r["platform"], "extra_yaml": r["extra_yaml"],
         "default_runtime_profile": r["default_runtime_profile"]}
        for r in db.all_(conn, "SELECT * FROM targets ORDER BY id")
    ]
    devices = [
        {"id": int(r["id"]), "name": r["name"], "target_id": int(r["target_id"]),
         "env": r["env"], "runtime_profile": r["runtime_profile"]}
        for r in db.all_(conn, "SELECT id, name, target_id, env, runtime_profile "
                               "FROM devices ORDER BY id")
    ]
    base_docs: dict[str, dict] = {}      # 引擎平台配置：引擎+平台 → 覆盖文档
    base_devices: dict[str, dict] = {}   # 设备专属配置：设备 id → 覆盖文档
    for row in db.all_(conn, "SELECT engine, platform, device_id, content "
                             "FROM base_configs"):
        try:
            doc = base_config_service.normalize(
                base_config_service.parse_content(row["content"]))
        except ValueError:
            continue
        device_id = int(row["device_id"] or 0)
        platform = row["platform"] or ""
        if device_id:
            base_devices[str(device_id)] = doc
        elif platform:
            base_docs[f"{row['engine']}|{platform}"] = doc
        else:
            # 引擎默认配置层的用户覆盖：键是 "engine|"（平台为空）。
            # 渲染层按同一套语义与源码默认值合并，这一层改了才真正生效。
            base_docs[f"{row['engine']}|"] = doc
    snippets = [
        {"name": r["name"], "category": r["category"], "engine": r["engine"],
         "content": r["content"]}
        for r in db.all_(
            conn, "SELECT * FROM snippets WHERE enabled=1 ORDER BY sort, id")
    ]
    variants = [
        {"id": int(r["id"]), "name": r["name"], "note": r["note"],
         "enabled": bool(r["enabled"]), "is_system": bool(r["is_system"])}
        for r in db.all_(conn, "SELECT * FROM variants ORDER BY sort, id")
    ] or [{"id": 0, "name": "默认", "note": "", "enabled": True, "is_system": True}]
    return {
        "node_catalog": catalog, "node_materials":node_materials,
        "sources": sources, "rule_providers": rule_providers,
        "local_nodes": local_nodes, "groups": groups, "rules": rules,
        "targets": targets, "snippets": snippets, "base": base_docs,
        "base_devices": base_devices, "devices": devices, "variants": variants,
    }


def _build_dir(build_id: int):
    path = config.BUILDS_DIR / str(build_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_path(build_id: int, target_name: str):
    return _build_dir(build_id) / f"{target_name}.yaml"


def artifact_file(build_id: int, target_name: str):
    """只读路径：目录不存在时也不创建。

    读接口不该有副作用——产物被留存清理后再查一次，
    不应该凭空把空目录建出来。
    """
    return config.BUILDS_DIR / str(int(build_id)) / f"{target_name}.yaml"


def _build_public(row, with_results: bool = False) -> dict:
    data = releases.build_public(row, with_results=with_results)
    data.pop("snapshot", None)
    return data


def _get_build(conn, bid: int):
    row = db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))
    if not row:
        raise HTTPException(404, "构建不存在")
    return row


def _delete_guard(build) -> str:
    """只有从未发布过的构建可以物理删除；其余状态是归档/生效版本。"""
    if build["status"] == releases.BuildStatus.BUILT.value:
        return ""
    try:
        label = releases.STATUS_LABELS[releases.BuildStatus(build["status"])]
    except ValueError:
        label = build["status"]
    return (f"构建 #{build['id']} 当前为「{label}」，只有未发布过的构建可以手动删除；"
            "已发布过的版本由系统自动清理（保留最近 20 个）")


def _purge_artifacts(build_id: int) -> None:
    """删除产物目录；只接受数据库里的整数构建号，避免误删。"""
    try:
        folder = (config.BUILDS_DIR / str(int(build_id))).resolve()
    except (TypeError, ValueError):
        return
    if folder.parent != config.BUILDS_DIR.resolve():
        return
    shutil.rmtree(folder, ignore_errors=True)


def _delete_build(conn, build, operator: str) -> int:
    """删除构建并清理其发布历史；调用方需先校验状态（仅「已构建」可删）。"""
    removed = conn.execute(
        "DELETE FROM releases WHERE build_id=?", (build["id"],)).rowcount
    conn.execute("DELETE FROM builds WHERE id=?", (build["id"],))
    security.audit(conn, operator, "删除构建", "build", build["id"],
                   {"releases_removed": removed, "status": build["status"],
                    "note": build["note"]})
    return removed


class BuildBody(BaseModel):
    note: str = Field(default="", max_length=256)
    preview_regional_names: bool = False
    preview_service_aliases: bool = False


class BatchIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class BuildError(Exception):
    pass


def _alias_snapshot(conn) -> dict:
    from ..services import quality_funnel, routing_planner
    now = int(time.time())
    cutoff = now - quality_funnel._settings(conn)["refresh_seconds"]
    catalog = {node["emit_name"]: node for node in node_rename.regional_catalog(conn)
               if not node.get("retired")}
    evidence = {}
    for name, row in quality_funnel.load_results().get("nodes", {}).items():
        if not isinstance(row, dict) or not row.get("revision"):
            continue
        proofs = routing_planner.service_proofs(row, earliest=cutoff, latest=now)
        if proofs:
            node = catalog.get(name)
            flag, _ = node_rename.regional_region((node or {}).get("raw_name") or name)
            local = bool(node and node.get("source_id") is None)
            evidence[name] = {
                "revision": row["revision"], "services": list(proofs),
                "preferred_ai": local and flag in ("🇺🇸", "🇯🇵"),
                "regions": {pid: proof["result"].get("region") for pid, proof in proofs.items()},
                "latencies": {pid: proof["result"].get("latency_ms") or proof.get("delay_ms") or 10**9
                              for pid, proof in proofs.items()},
            }
    return evidence


def current_policy(conn) -> tuple[dict, str]:
    regional = db.get_setting(conn, "build_regional_node_names", "0") == "1"
    snapshot = collect_snapshot(conn, regional=regional)
    if regional:
        snapshot["regional_catalog"] = node_rename.regional_catalog(conn)
        if db.get_setting(conn, "probe_build_aliases", "1") == "1":
            snapshot["service_aliases"] = _alias_snapshot(conn)
    policy_sha = security.sha256_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    )
    return snapshot, policy_sha


def create_build(operator: str, note: str = "",
                 snapshot: dict | None = None,
                 policy_sha: str | None = None, *,
                 preview_regional_names: bool = False,
                 preview_service_aliases: bool = False) -> tuple[int, str]:
    """创建构建，返回 (build_id, verify_status)。

    定时任务与手动创建共用；没有引擎平台时抛 BuildError。
    新构建的生命周期状态为「已构建」（从未发布过）。
    写事务只用于落库，渲染与核心校验在事务之外执行，
    避免慢校验长期占用 SQLite 写锁（设备拉取配置会被阻塞）。
    """
    with db.connect() as conn:
        if preview_regional_names or preview_service_aliases:
            # 预览用独立策略摘要，自动构建不会复用这个预览产物。
            snapshot = {**collect_snapshot(conn, regional=True),
                        "regional_catalog": node_rename.regional_catalog(conn),
                        "regional_preview": True}
            if preview_service_aliases:
                snapshot["service_aliases"] = _alias_snapshot(conn)
            policy_sha = None
        elif snapshot is None:
            snapshot, current_sha = current_policy(conn)
            policy_sha = policy_sha or current_sha
    if not snapshot["targets"]:
        raise BuildError("尚未配置任何引擎平台，请先在“引擎平台”中添加")
    if policy_sha is None:
        policy_sha = security.sha256_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        )
    # 逐方案校验：返回 {方案id: (errors, warnings)}，方案之间互不阻塞
    validations = validate.validate_policy(snapshot)
    now = db.now()
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO builds(created_at, created_by, status, verify_status, "
            "policy_sha, snapshot, results, note, status_updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (now, operator, releases.BuildStatus.BUILT.value, "building", policy_sha,
             security.encrypt_payload(json.dumps(snapshot, ensure_ascii=False)),
             "{}", note, now),
        )
        build_id = cur.lastrowid

    def scoped_devices(variant_id: int) -> list[dict]:
        """该方案下需要设备专属产物的设备。

        显式适用设备必须单独产物；设备 runtime profile 改变最终生效配置时，
        即使没有被规则 scope 引用也要进入产物矩阵。
        """
        names = set()
        for item in snapshot["groups"] + snapshot["rules"]:
            if int(item.get("variant_id", 0)) != variant_id:
                continue
            names.update(d for d in (item.get("devices") or []) if d != "*")
        by_name = {d["name"]: d for d in snapshot.get("devices", [])}
        result = [by_name[n] for n in sorted(names) if n in by_name]
        target_by_id = {int(t["id"]): t for t in snapshot.get("targets", [])}
        for device in snapshot.get("devices", []):
            target = target_by_id.get(int(device["target_id"]))
            if not target or device["name"] in names:
                continue
            try:
                runtime_profiles.effective_profile(target, device)
                target_profile = runtime_profiles.effective_profile(target)
                device_profile = runtime_profiles.effective_profile(target, device)
            except ValueError:
                # 渲染阶段会给出稳定的 runtime_profile_invalid；这里只负责矩阵。
                continue
            if device_profile != target_profile:
                result.append(device)
        return sorted(result, key=lambda item: item["name"])

    # 产物计划：(产物名, 目标, 设备或 None, 方案或 None)。
    # 默认方案沿用 {target}.yaml / {device}.yaml 命名；自定义方案带 @方案 后缀。
    plan: list[tuple[str, dict, dict | None, dict | None]] = []
    for variant in [v for v in snapshot["variants"] if v.get("enabled", True)]:
        vid = int(variant["id"])
        suffix = "" if vid == 0 else f"@{variant['name']}"
        for target in snapshot["targets"]:
            plan.append((target["name"] + suffix, target, None, variant))
        target_by_id = {int(t["id"]): t for t in snapshot["targets"]}
        for device in scoped_devices(vid):
            target = target_by_id.get(int(device["target_id"]))
            if target:
                plan.append((device["name"] + suffix, target, device, variant))
    # 产物文件名冲突（target/device 名 × 方案名组合重复）会让两份产物互相覆盖
    seen_names: dict[str, str] = {}
    for artifact_name, _, _, variant in plan:
        vid = int(variant["id"]) if variant else 0
        label = "" if vid == 0 else f"方案{variant['name']}"
        if artifact_name in seen_names:
            plan = [p for p in plan if p[0] != artifact_name]
            validations.setdefault(vid, ([], []))
            validations[vid][0].append(
                f"产物文件名冲突：{artifact_name}（{label}），请调整方案或目标/设备名称")
        else:
            seen_names[artifact_name] = label

    results: dict = {}
    overall = "success"
    from ..services import quality_funnel
    with db.connect() as _conn:
        normalize_nodes = db.get_setting(_conn, "node_name_normalize", "1") == "1"
        unlock_badge = db.get_setting(_conn, "node_name_unlock_badge", "0") == "1"
    # 同一方案的 resolve 只做一次：plan 按 variant 展开（T + D 个产物/方案），
    # 原来每个产物都全量解析一遍引用图（2026-11-18 构建性能）
    resolved_by_variant: dict[int, dict] = {}
    from ..services.node_refs import resolve_snapshot
    quality_reader = quality_funnel.result_reader()
    regional_plan = None
    google_time = datetime.now(timezone.utc)
    google_samples = []
    if "regional_catalog" in snapshot:
        reserved = set(config.BUILTIN_TARGETS) | {config.GUARD_PROXY}
        reserved.update(g["name"] for g in snapshot["groups"])
        regional_plan = node_rename.regional_names(snapshot["regional_catalog"], reserved)
        with db.connect() as conn:
            google_samples = google_evidence.observations(conn, now=google_time)
    for artifact_name, target, device, variant in plan:
        vid = int(variant["id"]) if variant else 0
        if vid not in resolved_by_variant:
            try:
                resolved_by_variant[vid] = resolve_snapshot(snapshot, variant_id=vid)
            except Exception as exc:
                # 解析失败按 variant 存异常对象：渲染时抛出并记入该产物结果，
                # 与"渲染时才解析"的原行为一致（不中断其它产物）
                resolved_by_variant[vid] = exc
        policy_errors, policy_warnings = validations.get(vid, ([], []))
        errors = list(policy_errors)
        warnings = list(policy_warnings)
        text = ""
        verification = "未通过"
        core_checked = False
        review = {}

        def review_google(cfg):
            report = google_evidence.artifact_report(
                cfg, snapshot.get("node_catalog", []), regional_plan, google_samples,
                evaluation_at=google_time)
            if report is not None:
                review["google_review"] = report

        if not policy_errors:
            try:
                resolved = resolved_by_variant[vid]
                if isinstance(resolved, Exception):
                    raise resolved
                text = render.render_target(snapshot, target, warnings,
                                            device=device, variant=variant,
                                            normalize_nodes=normalize_nodes,
                                            resolved=resolved,
                                            quality_reader=quality_reader,
                                            quality_badges=unlock_badge,
                                            regional_plan=regional_plan,
                                            google_review=review_google)
                errors.extend(validate.validate_rendered(text, target["engine"]))
            except Exception as exc:  # 渲染异常归为构建失败，不中断其他目标
                errors.append(f"渲染失败：{exc}")
        # Mihomo 目标在核心可用时追加官方配置检查（mihomo -t）
        if not errors and target["engine"] == "mihomo":
            checked, core_error = tester.validate_config(text)
            if checked:
                core_checked = True
                if core_error:
                    errors.append(core_error)
                else:
                    verification = "核心校验通过（mihomo -t）"
        if not errors and not verification.startswith("核心"):
            # Stash 无官方无头校验工具；核心缺失时 Mihomo 也只有静态校验
            verification = ("静态通过（未做核心校验）"
                            if target["engine"] == "mihomo" and not core_checked
                            else "静态通过")
        if errors:
            overall = "failed"
            verification = "未通过"
        else:
            path = artifact_path(build_id, artifact_name)
            with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                tmp = Path(handle.name)
                handle.write(text.encode("utf-8"))
            try:
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
        results[artifact_name] = {
            **(review if not errors else {}),
            "ok": not errors,
            "engine": target["engine"],
            "platform": target["platform"],
            **({"device": device["name"]} if device else {}),
            "target": target["name"],
            **({"variant": variant["name"]} if variant and vid != 0 else {}),
            "errors": errors,
            "warnings": warnings,
            "sha256": security.sha256_text(text) if text else "",
            "size": len(text.encode()),
            "verification": verification,
            # 必须与平台产物一样写出来：自动构建发布的闸门据此判断
            # Mihomo 目标到底做没做核心校验，缺字段会被误判成"没校验"。
            "core_checked": core_checked,
        }
    with db.tx() as conn:
        conn.execute(
            "UPDATE builds SET verify_status=?, results=? WHERE id=?",
            (overall, json.dumps(results, ensure_ascii=False), build_id),
        )
        security.audit(conn, operator, "创建构建", "build", build_id,
                       {"status": overall, "note": note,
                        "artifacts": len(results)})
    return build_id, overall


@router.post("/builds", status_code=201)
def create_build_api(body: BuildBody, user=CurrentUser):
    try:
        build_id, _ = create_build(user["username"], body.note,
                                   preview_regional_names=body.preview_regional_names,
                                   preview_service_aliases=body.preview_service_aliases)
    except BuildError as exc:
        raise HTTPException(400, str(exc))
    with db.connect() as conn:
        row = _get_build(conn, build_id)
    return _build_public(row, with_results=True)


@router.get("/builds/page")
def list_builds_paged(limit: int = 20, offset: int = 0, user=CurrentUser):
    """构建历史分页列表。"""
    with db.connect() as conn:
        data = db.paged(conn, "builds", "", [], "id DESC", limit, offset,
                        columns=('id, created_at, created_by, status, verify_status, policy_sha, note, published_at, published_by, publish_reason, status_updated_at'))
    data["items"] = [_build_public(r) for r in data["items"]]
    return data


@router.get("/builds")
def list_builds(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT id, created_at, created_by, status, verify_status, policy_sha, note, published_at, published_by, publish_reason, status_updated_at FROM builds ORDER BY id DESC LIMIT 200")
    return [_build_public(r) for r in rows]


@router.get("/builds/{bid}")
def get_build(bid: int, user=CurrentUser):
    with db.connect() as conn:
        row = _get_build(conn, bid)
    return _build_public(row, with_results=True)


@router.post("/builds/{bid}/reveal")
def reveal_build(bid: int, user=RequireCapabilities("reveal")):
    with db.tx() as conn:
        row = _get_build(conn, bid)
        security.audit(conn, user['username'], '查看构建快照', 'build', bid, {'fields': ['snapshot']})
    return {"id": bid, "snapshot": json.loads(security.decrypt_payload(row["snapshot"] or "{}") or "{}")}


@router.post("/builds/batch/delete")
def batch_delete_builds(body: BatchIds, user=CurrentUser):
    """批量删除构建：非「已构建」状态的构建保留并返回原因。

    历史发布记录不属于有效引用，会随构建一并清理（删除前由界面确认）。
    """
    deleted: list[int] = []
    blocked: list[dict] = []
    with db.tx() as conn:
        for bid in dict.fromkeys(body.ids):
            build = db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))
            if not build:
                blocked.append({"id": bid, "name": f"#{bid}",
                                "reason": "构建不存在（可能已被删除）"})
                continue
            reason = _delete_guard(build)
            if reason:
                blocked.append({"id": bid, "name": f"#{bid}", "reason": reason})
                continue
            _delete_build(conn, build, user["username"])
            deleted.append(bid)
    for bid in deleted:
        _purge_artifacts(bid)
    return {"ok": True, "deleted": deleted, "blocked": blocked}


@router.delete("/builds/{bid}")
def delete_build(bid: int, user=CurrentUser):
    with db.tx(immediate=True) as conn:
        build = _get_build(conn, bid)
        reason = _delete_guard(build)
        if reason:
            raise HTTPException(400, reason)
        removed = _delete_build(conn, build, user["username"])
    _purge_artifacts(bid)
    return {"ok": True, "deleted_releases": removed}


@router.get("/builds/{bid}/artifact/{target_name}")
def get_artifact(bid: int, target_name: str, user=RequireCapabilities('reveal')):
    """产物仅对维护者开放；本地单节点的凭据会直接出现在产物中。"""
    with db.tx() as conn:
        _get_build(conn, bid)
        security.audit(conn, user['username'], '查看构建产物', 'build', bid, {'fields': ['artifact']})
    path = artifact_file(bid, target_name)
    if not path.exists():
        raise HTTPException(404, "该引擎平台没有构建产物")
    return {"target": target_name, "content": path.read_text(encoding="utf-8")}


@router.get("/builds/{bid}/diff/{other_id}")
def diff_builds(bid: int, other_id: int, user=CurrentUser):
    with db.connect() as conn:
        _get_build(conn, bid)
        _get_build(conn, other_id)
    # 只读路径：读接口不该有副作用（与 artifact_file 的只读设计一致，
    # 原来用 _build_dir 会给被清理过的构建凭空建出空目录，2026-11-18）
    build_dir_a = config.BUILDS_DIR / str(other_id)
    build_dir_b = config.BUILDS_DIR / str(bid)
    a_files = {p.stem for p in build_dir_a.glob("*.yaml")} if build_dir_a.is_dir() else set()
    b_files = {p.stem for p in build_dir_b.glob("*.yaml")} if build_dir_b.is_dir() else set()
    targets = sorted(a_files | b_files)
    diffs = {}
    for name in targets:
        a = build_dir_a / f"{name}.yaml"
        b = build_dir_b / f"{name}.yaml"
        old = a.read_text(encoding="utf-8").splitlines() if a.exists() else []
        new = b.read_text(encoding="utf-8").splitlines() if b.exists() else []
        diffs[name] = {"changed": old != new, "before_lines": len(old), "after_lines": len(new)}
    return {"targets": diffs}


class PublishBody(BaseModel):
    reason: str = Field(default="", max_length=256)
    expected_release_revision: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


def _publish(action: str, bid: int, reason: str, operator: str, body=None) -> dict:
    """发布票据、CAS 与状态切换必须在同一事务内完成。"""
    body = body or PublishBody()
    env = {"test": releases.Env.TESTING, "prod": releases.Env.PRODUCTION,
           "both": releases.Env.PRODUCTION, "rollback": releases.Env.PRODUCTION,
           "offline": releases.Env.TESTING}[action]
    if (body.expected_release_revision is None) != (body.idempotency_key is None):
        raise HTTPException(400, "expected_release_revision 与 idempotency_key 必须同时提供")
    try:
        with db.tx(immediate=True) as conn:
            build = _get_build(conn, bid)
            target_status = {"test": releases.BuildStatus.TESTING.value,
                             "prod": releases.BuildStatus.PRODUCTION.value,
                             "both": releases.BuildStatus.PRODUCTION.value,
                             "rollback": releases.BuildStatus.PRODUCTION.value,
                             "offline": releases.BuildStatus.OFFLINE.value}[action]
            payload_sha = json.dumps({"build": int(build["id"]), "reason": reason,
                                      "status": target_status}, ensure_ascii=False,
                                     sort_keys=True, separators=(',', ':'))
            replay = releases._idempotent(conn, {"test": "publish", "prod": "publish",
                                                  "both": "publish", "rollback": "rollback",
                                                  "offline": "offline"}[action], env,
                                          operator, body.idempotency_key, payload_sha)
            if replay is not None:
                return {"ok": True, **replay}
            if action != "offline":
                publish_gate.prepare_ticket(conn, bid, env=env.value,
                                            now=datetime.now(timezone.utc))
            expected = body.expected_release_revision
            idem = body.idempotency_key
            if action == "test":
                result = releases.publish_to_testing(
                    conn, build, operator, reason, expected_revision=expected,
                    idempotency_key=idem)
            elif action == "prod":
                result = releases.publish_to_production(
                    conn, build, operator, reason, expected_revision=expected,
                    idempotency_key=idem)
            elif action == "both":
                if build["status"] == releases.BuildStatus.PRODUCTION.value:
                    raise releases.ReleaseError("该构建已是当前生产版本")
                result = releases.publish_build(
                    conn, build, operator, reason, releases.Env.PRODUCTION,
                    expected_revisions={"production": expected},
                    idempotency_keys={"production": idem})
            elif action == "rollback":
                result = releases.publish_to_production(
                    conn, build, operator, reason, rollback=True,
                    expected_revision=expected, idempotency_key=idem)
            else:
                result = releases.offline(conn, build, operator, reason,
                    expected_revision=expected, idempotency_key=idem)
    except releases.ReleaseError as exc:
        # 状态码按 ReleaseError.code 映射，不再对文案做字符串前缀匹配
        status = 409 if exc.code == "release_revision_changed" else 400
        raise HTTPException(status, str(exc))
    return {"ok": True, **result}


@router.post("/builds/{bid}/publish-to-test")
def publish_to_test(bid: int, body: PublishBody, user=RequireCapabilities('publish_test')):
    """发布至测试环境：已构建 / 已下线 → 测试中。"""
    return _publish("test", bid, body.reason, user["username"], body)


@router.post("/builds/{bid}/publish-to-prod")
def publish_to_prod(bid: int, body: PublishBody, user=RequireCapabilities('publish_prod')):
    """发布至生产环境：测试中 / 已下线 → 生产中。"""
    return _publish("prod", bid, body.reason, user["username"], body)


@router.post("/builds/{bid}/publish-both")
def publish_both(bid: int, body: PublishBody, user=RequireCapabilities('publish_prod')):
    """一键发布：已构建 / 已下线 → 测试中 + 生产中，一步到位。

    两步同处一个事务，状态原子切换；发布历史只记最终那一条。
    """
    return _publish("both", bid, body.reason, user["username"], body)


@router.post("/builds/{bid}/rollback-to-prod")
def rollback_to_prod(bid: int, body: PublishBody, user=RequireCapabilities('publish_prod')):
    """回滚生产版本：把已下线的历史构建重新设为生产版本。"""
    return _publish("rollback", bid, body.reason, user["username"], body)


@router.post("/builds/{bid}/offline")
def offline_build(bid: int, body: PublishBody, user=RequireCapabilities('publish_test')):
    """手动下线：测试中 → 已下线（测试环境空置）。"""
    return _publish("offline", bid, body.reason, user["username"], body)


@router.get("/release-state")
def release_state(user=CurrentUser):
    """当前生效版本（生产 / 测试）。"""
    with db.connect() as conn:
        return releases.state_public(conn)


@router.get("/releases")
def list_releases(auto_only: bool = False, user=CurrentUser):
    with db.connect() as conn:
        if auto_only:
            # 自动任务固定以“系统”身份发布；手动发布不进入自动构建发布页
            rows = db.all_(
                conn,
                "SELECT * FROM releases WHERE operator='系统' "
                "ORDER BY id DESC LIMIT ?",
                (config.RELEASE_HISTORY_LIMIT,),
            )
        else:
            rows = db.all_(
                conn, "SELECT * FROM releases ORDER BY id DESC LIMIT ?",
                (config.RELEASE_HISTORY_LIMIT,),
            )
    return [db.row_to_dict(r) for r in rows]
