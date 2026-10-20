"""候选构建、通道发布与回滚。

构建把当前策略固化为不可变快照并逐目标渲染；发布只移动通道指针，
失败或空结果不会覆盖旧发布。
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
from ..services import tester

router = APIRouter(prefix="/api/v1", tags=["builds"])

CHANNELS = {"stable", "candidate"}


def collect_snapshot(conn) -> dict:
    sources = [
        {"name": r["name"], "enabled": bool(r["enabled"]), "filter": r["filter"],
         "ua": r["ua"], "interval": r["interval"],
         "client_interval": r["client_interval"]}
        for r in db.all_(conn, "SELECT * FROM sources ORDER BY id")
    ]
    rule_providers = [
        {"name": r["name"], "behavior": r["behavior"], "format": r["format"],
         "kind": r["kind"], "interval": r["interval"],
         "client_interval": r["client_interval"], "enabled": bool(r["enabled"])}
        for r in db.all_(conn, "SELECT * FROM rule_providers ORDER BY id")
    ]
    local_nodes = [
        {"id": r["id"], "name": r["name"], "protocol": r["protocol"],
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
         "local_first": bool(r["local_first"]) if "local_first" in r.keys() else False,
         "interval": r["interval"], "timeout": r["timeout"],
         "tolerance": r["tolerance"], "lazy": bool(r["lazy"]),
         "strategy": r["strategy"]}
        for r in db.all_(conn, "SELECT * FROM proxy_groups ORDER BY sort, id")
    ]
    rules = [
        {"type": r["type"], "value": r["value"], "target": r["target"],
         "enabled": bool(r["enabled"]), "no_resolve": bool(r["no_resolve"]),
         "targets": json.loads(r["targets"] or "[]")}
        for r in db.all_(conn, "SELECT * FROM rules ORDER BY sort, id")
    ]
    targets = [
        {"name": r["name"], "engine": r["engine"], "platform": r["platform"],
         "extra_yaml": r["extra_yaml"]}
        for r in db.all_(conn, "SELECT * FROM targets ORDER BY id")
    ]
    base_docs: dict[str, dict] = {}      # 通用配置：引擎+平台 → 覆盖文档
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
        "base_devices": base_devices,
    }


def _build_dir(build_id: int):
    path = config.BUILDS_DIR / str(build_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_path(build_id: int, target_name: str):
    return _build_dir(build_id) / f"{target_name}.yaml"


def _build_public(row, with_results: bool = False) -> dict:
    data = {
        "id": row["id"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "status": row["status"],
        "policy_sha": row["policy_sha"],
        "note": row["note"],
    }
    if with_results:
        data["results"] = json.loads(row["results"] or "{}")
        data["snapshot"] = json.loads(
            security.decrypt_payload(row["snapshot"] or "{}") or "{}")
    return data


def _get_build(conn, bid: int):
    row = db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))
    if not row:
        raise HTTPException(404, "候选构建不存在")
    return row


def _channel_refs(conn, bid: int) -> list[str]:
    return [r["channel"] for r in db.all_(
        conn, "SELECT channel FROM pointers WHERE build_id=? ORDER BY channel", (bid,))]


def _channel_reason(channels: list[str]) -> str:
    labels = {"stable": "稳定", "candidate": "候选"}
    return (f"仍发布在{'、'.join(labels.get(c, c) for c in channels)}通道，"
            "不能删除；请先把该通道发布或回滚到其他构建")


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
    """删除构建并清理其发布历史；调用方需先校验通道指针。"""
    removed = conn.execute(
        "DELETE FROM releases WHERE build_id=?", (build["id"],)).rowcount
    conn.execute("DELETE FROM builds WHERE id=?", (build["id"],))
    security.audit(conn, operator, "删除候选构建", "build", build["id"],
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


def create_candidate(operator: str, note: str = "",
                     snapshot: dict | None = None,
                     policy_sha: str | None = None) -> tuple[int, str]:
    """创建候选构建，返回 (build_id, status)。

    定时任务与手动创建共用；没有引擎平台时抛 BuildError。
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
            "INSERT INTO builds(created_at, created_by, status, policy_sha, snapshot, "
            "results, note) VALUES(?,?,?,?,?,?,?)",
            (now, operator, "building", policy_sha,
             security.encrypt_payload(json.dumps(snapshot, ensure_ascii=False)),
             "{}", note),
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
                    verification = "核心校验通过（mihomo -t），实机行为待验收"
        if not errors and not verification.startswith("核心"):
            # Stash 无官方无头校验工具；核心缺失时 Mihomo 也只有静态校验
            verification = ("静态通过（未做核心校验），实机待验收"
                            if target["engine"] == "mihomo" and not core_checked
                            else "静态通过，实机待验收")
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
    with db.tx() as conn:
        conn.execute(
            "UPDATE builds SET status=?, results=? WHERE id=?",
            (overall, json.dumps(results, ensure_ascii=False), build_id),
        )
        security.audit(conn, operator, "创建候选构建", "build", build_id,
                       {"status": overall, "note": note})
    return build_id, overall


@router.post("/builds", status_code=201)
def create_build(body: BuildBody, user=CurrentUser):
    try:
        build_id, _ = create_candidate(user["username"], body.note)
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
    """批量删除构建：仍被通道指针引用的构建保留并返回原因。

    历史发布记录不属于有效引用，会随构建一并清理（删除前由界面确认）。
    """
    deleted: list[int] = []
    blocked: list[dict] = []
    with db.tx() as conn:
        for bid in dict.fromkeys(body.ids):
            build = db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))
            if not build:
                blocked.append({"id": bid, "name": f"#{bid}",
                                "reason": "候选构建不存在（可能已被删除）"})
                continue
            channels = _channel_refs(conn, bid)
            if channels:
                blocked.append({"id": bid, "name": f"#{bid}",
                                "reason": _channel_reason(channels)})
                continue
            _delete_build(conn, build, user["username"])
            deleted.append(bid)
    for bid in deleted:
        _purge_artifacts(bid)
    return {"ok": True, "deleted": deleted, "blocked": blocked}


@router.delete("/builds/{bid}")
def delete_build(bid: int, user=CurrentUser):
    with db.tx() as conn:
        build = _get_build(conn, bid)
        channels = _channel_refs(conn, bid)
        if channels:
            raise HTTPException(400, f"构建 #{bid} {_channel_reason(channels)}")
        removed = _delete_build(conn, build, user["username"])
    _purge_artifacts(bid)
    return {"ok": True, "deleted_releases": removed}


@router.get("/builds/{bid}/artifact/{target_name}")
def get_artifact(bid: int, target_name: str, user=CurrentUser):
    """产物仅对维护者开放；本地单节点的凭据会直接出现在产物中。"""
    with db.connect() as conn:
        _get_build(conn, bid)
    path = artifact_path(bid, target_name)
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


class PromoteBody(BaseModel):
    channel: str
    reason: str = Field(default="", max_length=256)


def promote_internal(conn, build, channel: str, action: str, operator: str, reason: str):
    if build["status"] != "success":
        raise HTTPException(400, "只有校验全部通过的候选构建才能发布")
    now = db.now()
    conn.execute(
        "INSERT INTO pointers(channel, build_id, released_at, operator, action, reason) "
        "VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(channel) DO UPDATE SET build_id=excluded.build_id, "
        "released_at=excluded.released_at, operator=excluded.operator, "
        "action=excluded.action, reason=excluded.reason",
        (channel, build["id"], now, operator, action, reason),
    )
    conn.execute(
        "INSERT INTO releases(build_id, channel, action, operator, reason, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (build["id"], channel, action, operator, reason, now),
    )
    # 发布历史只保留最近 N 条；完整操作仍可在审计日志中追溯
    conn.execute(
        "DELETE FROM releases WHERE id NOT IN "
        "(SELECT id FROM releases ORDER BY id DESC LIMIT ?)",
        (config.RELEASE_HISTORY_LIMIT,),
    )
    security.audit(conn, operator,
                   "发布到稳定通道" if action == "promote" and channel == "stable"
                   else ("发布到候选通道" if action == "promote" else "回滚"),
                   "build", build["id"], {"channel": channel, "reason": reason})


@router.post("/builds/{bid}/promote")
def promote_build(bid: int, body: PromoteBody, user=CurrentUser):
    if body.channel not in CHANNELS:
        raise HTTPException(400, "通道仅支持 stable / candidate")
    with db.tx() as conn:
        build = _get_build(conn, bid)
        promote_internal(conn, build, body.channel, "promote", user["username"], body.reason)
    return {"ok": True, "channel": body.channel, "build_id": bid}


class RollbackBody(BaseModel):
    build_id: int
    reason: str = Field(default="", max_length=256)


@router.post("/channels/{channel}/rollback")
def rollback_to(channel: str, body: RollbackBody, user=CurrentUser):
    """回滚即把通道指针移回指定的历史构建；客户端下次拉取才生效。"""
    with db.tx() as conn:
        build = _get_build(conn, body.build_id)
        promote_internal(conn, build, channel, "rollback", user["username"], body.reason)
    return {"ok": True, "channel": channel, "build_id": body.build_id}


@router.get("/channels")
def list_channels(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM pointers")
        result = {}
        for channel in CHANNELS:
            result[channel] = None
        for r in rows:
            build = db.one(conn, "SELECT * FROM builds WHERE id=?", (r["build_id"],))
            if not build:
                continue
            data = _build_public(build, with_results=True)
            # 旧数据没有指针元数据时，回退到该通道最近一条发布记录
            release = db.one(
                conn,
                "SELECT * FROM releases WHERE channel=? ORDER BY id DESC LIMIT 1",
                (r["channel"],),
            )
            data["publish"] = {
                "at": r["released_at"] or (release["created_at"] if release else ""),
                "operator": r["operator"] or (release["operator"] if release else ""),
                "action": r["action"] or (release["action"] if release else ""),
                "reason": r["reason"] or (release["reason"] if release else ""),
            }
            result[r["channel"]] = data
    return result


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
