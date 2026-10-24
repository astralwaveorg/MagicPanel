"""构建与版本发布（状态机）。

构建把当前策略固化为不可变快照并逐目标渲染；发布按状态机切换
版本状态（已构建 / 测试中 / 生产中 / 已下线），失败或空结果不会覆盖现网。
"""
import difflib
import json
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..compiler import render, validate
from ..deps import CurrentUser
from ..services import base_config as base_config_service
from ..services import releases
from ..services import source_nodes as source_node_service
from ..services import tester

router = APIRouter(prefix="/api/v1", tags=["builds"])


def collect_snapshot(conn) -> dict:
    sources = []
    for r in db.all_(conn, "SELECT * FROM sources ORDER BY id"):
        mode = r["mode"] if "mode" in r.keys() else config.SOURCE_MODE_PROVIDER
        item = {"name": r["name"], "enabled": bool(r["enabled"]),
                "filter": r["filter"], "ua": r["ua"],
                "suffix": (r["suffix"] if "suffix" in r.keys() else ""),
                "interval": r["interval"],
                "client_interval": r["client_interval"], "mode": mode}
        if mode == config.SOURCE_MODE_INLINE and r["enabled"] and r["snapshot_enc"]:
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
         "client_interval": r["client_interval"], "enabled": bool(r["enabled"])}
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
        {"name": r["name"], "type": r["type"], "hidden": bool(r["hidden"]),
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
        {"type": r["type"], "value": r["value"], "target": r["target"],
         "enabled": bool(r["enabled"]), "no_resolve": bool(r["no_resolve"]),
         "no_track": bool(r["no_track"]) if "no_track" in r.keys() else False,
         "pre_matching": bool(r["pre_matching"]) if "pre_matching" in r.keys() else False,
         "targets": json.loads(r["targets"] or "[]"),
         "devices": json.loads(r["devices"] or "[]") if "devices" in r.keys() else []}
        for r in db.all_(conn, "SELECT * FROM rules ORDER BY sort, id")
    ]
    targets = [
        {"id": int(r["id"]), "name": r["name"], "engine": r["engine"],
         "platform": r["platform"], "extra_yaml": r["extra_yaml"]}
        for r in db.all_(conn, "SELECT * FROM targets ORDER BY id")
    ]
    devices = [
        {"id": int(r["id"]), "name": r["name"], "target_id": int(r["target_id"]),
         "env": r["env"]}
        for r in db.all_(conn, "SELECT id, name, target_id, env FROM devices "
                               "ORDER BY id")
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
    return {
        "sources": sources, "rule_providers": rule_providers,
        "local_nodes": local_nodes, "groups": groups, "rules": rules,
        "targets": targets, "snippets": snippets, "base": base_docs,
        "base_devices": base_devices, "devices": devices,
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
    return releases.build_public(row, with_results=with_results)


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


class BatchIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class BuildError(Exception):
    pass


def current_policy(conn) -> tuple[dict, str]:
    snapshot = collect_snapshot(conn)
    policy_sha = security.sha256_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    )
    return snapshot, policy_sha


def create_build(operator: str, note: str = "",
                 snapshot: dict | None = None,
                 policy_sha: str | None = None) -> tuple[int, str]:
    """创建构建，返回 (build_id, verify_status)。

    定时任务与手动创建共用；没有引擎平台时抛 BuildError。
    新构建的生命周期状态为「已构建」（从未发布过）。
    写事务只用于落库，渲染与核心校验在事务之外执行，
    避免慢校验长期占用 SQLite 写锁（设备拉取配置会被阻塞）。
    """
    with db.connect() as conn:
        snapshot = collect_snapshot(conn) if snapshot is None else snapshot
    if not snapshot["targets"]:
        raise BuildError("尚未配置任何引擎平台，请先在“引擎平台”中添加")
    if policy_sha is None:
        policy_sha = security.sha256_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        )
    policy_errors, policy_warnings = validate.validate_policy(snapshot)
    now = db.now()
    results: dict = {}
    overall = "success"
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
    for target in snapshot["targets"]:
        errors = list(policy_errors)
        warnings = list(policy_warnings)
        text = ""
        verification = "未通过"
        if not policy_errors:
            try:
                text = render.render_target(snapshot, target, warnings)
                errors.extend(validate.validate_rendered(text, target["engine"]))
            except Exception as exc:  # 渲染异常归为构建失败，不中断其他目标
                errors.append(f"渲染失败：{exc}")
        # Mihomo 目标在核心可用时追加官方配置检查（mihomo -t）
        core_checked = False
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
            path = artifact_path(build_id, target["name"])
            path.write_text(text, encoding="utf-8")
            try:
                path.chmod(0o600)   # 产物含明文节点凭据
            except OSError:
                pass
        results[target["name"]] = {
            "ok": not errors,
            "engine": target["engine"],
            "platform": target["platform"],
            "errors": errors,
            "warnings": warnings,
            "sha256": security.sha256_text(text) if text else "",
            "size": len(text.encode()),
            "verification": verification,
            "core_checked": core_checked,
        }
    # 设备专属产物：同一引擎平台下，个别设备有专属策略组 / 规则时单独出一份。
    # 引擎平台 = 引擎 + 平台，个性化落在设备上，所以产物也要分设备。
    scoped = set()
    for item in list(snapshot.get("rules", [])) + list(snapshot.get("groups", [])):
        scoped.update(item.get("devices") or [])
    if scoped:
        target_by_id = {int(t["id"]): t for t in snapshot["targets"]}
        for device in snapshot.get("devices", []):
            if device["name"] not in scoped:
                continue
            target = target_by_id.get(int(device["target_id"]))
            if not target:
                continue
            errors: list[str] = []
            warnings = list(policy_warnings)
            text = ""
            verification = "未通过"
            core_checked = False
            try:
                text = render.render_target(snapshot, target, warnings, device=device)
                errors.extend(validate.validate_rendered(text, target["engine"]))
            except Exception as exc:
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
                path = artifact_path(build_id, device["name"])
                path.write_text(text, encoding="utf-8")
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
            results[device["name"]] = {
                "ok": not errors,
                "engine": target["engine"],
                "platform": target["platform"],
                "device": device["name"],
                "target": target["name"],
                "errors": errors,
                "warnings": warnings,
                "sha256": security.sha256_text(text) if text else "",
                "size": len(text.encode()),
                "verification": verification,
                # 必须与平台产物一样写出来：自动发布的闸门据此判断
                # Mihomo 目标到底做没做核心校验，缺字段会被误判成"没校验"。
                "core_checked": core_checked,
            }
    with db.tx() as conn:
        conn.execute(
            "UPDATE builds SET verify_status=?, results=? WHERE id=?",
            (overall, json.dumps(results, ensure_ascii=False), build_id),
        )
        security.audit(conn, operator, "创建构建", "build", build_id,
                       {"status": overall, "note": note})
    return build_id, overall


@router.post("/builds", status_code=201)
def create_build_api(body: BuildBody, user=CurrentUser):
    try:
        build_id, _ = create_build(user["username"], body.note)
    except BuildError as exc:
        raise HTTPException(400, str(exc))
    with db.connect() as conn:
        row = _get_build(conn, build_id)
    return _build_public(row, with_results=True)


@router.get("/builds/page")
def list_builds_paged(limit: int = 20, offset: int = 0, user=CurrentUser):
    """构建历史分页列表。"""
    with db.connect() as conn:
        data = db.paged(conn, "builds", "", [], "id DESC", limit, offset)
    data["items"] = [_build_public(r) for r in data["items"]]
    return data


@router.get("/builds")
def list_builds(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM builds ORDER BY id DESC LIMIT 200")
    return [_build_public(r) for r in rows]


@router.get("/builds/{bid}")
def get_build(bid: int, user=CurrentUser):
    with db.connect() as conn:
        row = _get_build(conn, bid)
    return _build_public(row, with_results=True)


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
def get_artifact(bid: int, target_name: str, user=CurrentUser):
    """产物仅对维护者开放；本地单节点的凭据会直接出现在产物中。"""
    with db.connect() as conn:
        _get_build(conn, bid)
    path = artifact_file(bid, target_name)
    if not path.exists():
        raise HTTPException(404, "该目标没有构建产物")
    return {"target": target_name, "content": path.read_text(encoding="utf-8")}


@router.get("/builds/{bid}/diff/{other_id}")
def diff_builds(bid: int, other_id: int, user=CurrentUser):
    with db.connect() as conn:
        _get_build(conn, bid)
        _get_build(conn, other_id)
    build_dir_a = _build_dir(other_id)
    build_dir_b = _build_dir(bid)
    targets = sorted({p.stem for p in build_dir_a.glob("*.yaml")}
                     | {p.stem for p in build_dir_b.glob("*.yaml")})
    diffs = {}
    for name in targets:
        a = build_dir_a / f"{name}.yaml"
        b = build_dir_b / f"{name}.yaml"
        old = a.read_text(encoding="utf-8").splitlines() if a.exists() else []
        new = b.read_text(encoding="utf-8").splitlines() if b.exists() else []
        diffs[name] = "\n".join(difflib.unified_diff(
            old, new, fromfile=f"构建 #{other_id}", tofile=f"构建 #{bid}",
            lineterm="",
        ))
    return {"targets": diffs}


class PublishBody(BaseModel):
    reason: str = Field(default="", max_length=256)


def _publish(action: str, bid: int, reason: str, operator: str) -> dict:
    """执行一次状态切换并把状态机错误翻译成 400。"""
    try:
        with db.tx(immediate=True) as conn:
            build = _get_build(conn, bid)
            if action == "test":
                result = releases.publish_to_testing(
                    conn, build, operator, reason)
            elif action == "prod":
                result = releases.publish_to_production(
                    conn, build, operator, reason)
            elif action == "rollback":
                result = releases.publish_to_production(
                    conn, build, operator, reason, rollback=True)
            else:
                result = releases.offline(conn, build, operator, reason)
    except releases.ReleaseError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, **result}


@router.post("/builds/{bid}/publish-to-test")
def publish_to_test(bid: int, body: PublishBody, user=CurrentUser):
    """发布至测试环境：已构建 / 已下线 → 测试中。"""
    return _publish("test", bid, body.reason, user["username"])


@router.post("/builds/{bid}/publish-to-prod")
def publish_to_prod(bid: int, body: PublishBody, user=CurrentUser):
    """发布至生产环境：测试中 / 已下线 → 生产中。"""
    return _publish("prod", bid, body.reason, user["username"])


@router.post("/builds/{bid}/rollback-to-prod")
def rollback_to_prod(bid: int, body: PublishBody, user=CurrentUser):
    """回滚生产版本：把已下线的历史构建重新设为生产版本。"""
    return _publish("rollback", bid, body.reason, user["username"])


@router.post("/builds/{bid}/offline")
def offline_build(bid: int, body: PublishBody, user=CurrentUser):
    """手动下线：测试中 → 已下线（测试环境空置）。"""
    return _publish("offline", bid, body.reason, user["username"])


@router.get("/release-state")
def release_state(user=CurrentUser):
    """当前生效版本（生产 / 测试）。"""
    with db.connect() as conn:
        return releases.state_public(conn)


@router.get("/releases")
def list_releases(auto_only: bool = False, user=CurrentUser):
    with db.connect() as conn:
        if auto_only:
            # 自动任务固定以“系统”身份发布；手动发布不进入自动发布页
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
