"""候选构建、通道发布与回滚。

构建把当前策略固化为不可变快照并逐目标渲染；发布只移动通道指针，
失败或空结果不会覆盖旧发布。
"""
import difflib
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..compiler import render, validate
from ..deps import CurrentUser
from ..services import tester

router = APIRouter(prefix="/api/v1", tags=["builds"])

CHANNELS = {"stable", "candidate"}


def collect_snapshot(conn) -> dict:
    sources = [
        {"name": r["name"], "enabled": bool(r["enabled"]), "filter": r["filter"],
         "ua": r["ua"], "interval": r["interval"],
         "last_status": r["last_status"], "node_count": r["node_count"]}
        for r in db.all_(conn, "SELECT * FROM sources ORDER BY id")
    ]
    rule_providers = [
        {"name": r["name"], "behavior": r["behavior"], "format": r["format"],
         "kind": r["kind"], "interval": r["interval"], "enabled": bool(r["enabled"])}
        for r in db.all_(conn, "SELECT * FROM rule_providers ORDER BY id")
    ]
    groups = [
        {"name": r["name"], "type": r["type"], "hidden": bool(r["hidden"]),
         "filter": r["filter"], "use_sources": json.loads(r["use_sources"] or "[]"),
         "proxies": json.loads(r["proxies"] or "[]"), "url": r["url"],
         "interval": r["interval"], "timeout": r["timeout"],
         "tolerance": r["tolerance"], "lazy": bool(r["lazy"]),
         "strategy": r["strategy"]}
        for r in db.all_(conn, "SELECT * FROM proxy_groups ORDER BY sort, id")
    ]
    rules = [
        {"type": r["type"], "value": r["value"], "target": r["target"],
         "enabled": bool(r["enabled"])}
        for r in db.all_(conn, "SELECT * FROM rules ORDER BY sort, id")
    ]
    targets = [
        {"name": r["name"], "engine": r["engine"], "platform": r["platform"],
         "extra_yaml": r["extra_yaml"], "update_interval": r["update_interval"]}
        for r in db.all_(conn, "SELECT * FROM targets ORDER BY id")
    ]
    snippets = [
        {"name": r["name"], "category": r["category"], "engine": r["engine"],
         "content": r["content"]}
        for r in db.all_(
            conn, "SELECT * FROM snippets WHERE enabled=1 ORDER BY sort, id")
    ]
    return {
        "sources": sources, "rule_providers": rule_providers,
        "groups": groups, "rules": rules, "targets": targets,
        "snippets": snippets,
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
        data["snapshot"] = json.loads(row["snapshot"])
    return data


def _get_build(conn, bid: int):
    row = db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))
    if not row:
        raise HTTPException(404, "候选构建不存在")
    return row


class BuildBody(BaseModel):
    note: str = Field(default="", max_length=256)


@router.post("/builds", status_code=201)
def create_build(body: BuildBody, user=CurrentUser):
    with db.tx() as conn:
        snapshot = collect_snapshot(conn)
        if not snapshot["targets"]:
            raise HTTPException(400, "尚未配置任何发布目标，请先在“发布目标”中添加")
        policy_errors, policy_warnings = validate.validate_policy(snapshot)
        policy_sha = security.sha256_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        )
        now = db.now()
        results: dict = {}
        overall = "success"
        cur = conn.execute(
            "INSERT INTO builds(created_at, created_by, status, policy_sha, snapshot, "
            "results, note) VALUES(?,?,?,?,?,?,?)",
            (now, user["username"], "building", policy_sha,
             json.dumps(snapshot, ensure_ascii=False), "{}", body.note),
        )
        build_id = cur.lastrowid
        for target in snapshot["targets"]:
            errors = list(policy_errors)
            warnings = list(policy_warnings)
            text = ""
            verification = "未通过"
            if not policy_errors:
                try:
                    text = render.render_target(snapshot, target)
                    errors.extend(validate.validate_rendered(text))
                except Exception as exc:  # 渲染异常归为构建失败，不中断其他目标
                    errors.append(f"渲染失败：{exc}")
            # Mihomo 目标在核心可用时追加官方配置检查（mihomo -t）
            if not errors and target["engine"] == "mihomo":
                checked, core_error = tester.validate_config(text)
                if checked:
                    if core_error:
                        errors.append(core_error)
                    else:
                        verification = "核心校验通过（mihomo -t），实机行为待验收"
            if not errors and not verification.startswith("核心"):
                # Stash 无官方无头校验工具；核心缺失时 Mihomo 也只有静态校验
                verification = "静态通过，实机待验收" if not errors else "未通过"
            if errors:
                overall = "failed"
                verification = "未通过"
            else:
                path = artifact_path(build_id, target["name"])
                path.write_text(text, encoding="utf-8")
            results[target["name"]] = {
                "ok": not errors,
                "engine": target["engine"],
                "platform": target["platform"],
                "errors": errors,
                "warnings": warnings,
                "sha256": security.sha256_text(text) if text else "",
                "size": len(text.encode()),
                "verification": verification,
            }
        conn.execute(
            "UPDATE builds SET status=?, results=? WHERE id=?",
            (overall, json.dumps(results, ensure_ascii=False), build_id),
        )
        security.audit(conn, user["username"], "创建候选构建", "build", build_id,
                       {"status": overall, "note": body.note})
        row = _get_build(conn, build_id)
    return _build_public(row, with_results=True)


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


@router.get("/builds/{bid}/artifact/{target_name}")
def get_artifact(bid: int, target_name: str, user=CurrentUser):
    """产物不含令牌与节点凭据（均为 {FEED} 占位与子资源引用），可直接预览。"""
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


def _promote(conn, build, channel: str, action: str, operator: str, reason: str):
    if build["status"] != "success":
        raise HTTPException(400, "只有校验全部通过的候选构建才能发布")
    conn.execute(
        "INSERT INTO pointers(channel, build_id) VALUES(?, ?) "
        "ON CONFLICT(channel) DO UPDATE SET build_id=excluded.build_id",
        (channel, build["id"]),
    )
    conn.execute(
        "INSERT INTO releases(build_id, channel, action, operator, reason, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (build["id"], channel, action, operator, reason, db.now()),
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
        _promote(conn, build, body.channel, "promote", user["username"], body.reason)
    return {"ok": True, "channel": body.channel, "build_id": bid}


class RollbackBody(BaseModel):
    build_id: int
    reason: str = Field(default="", max_length=256)


@router.post("/channels/{channel}/rollback")
def rollback_to(channel: str, body: RollbackBody, user=CurrentUser):
    """回滚即把通道指针移回指定的历史构建；客户端下次拉取才生效。"""
    with db.tx() as conn:
        build = _get_build(conn, body.build_id)
        _promote(conn, build, channel, "rollback", user["username"], body.reason)
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
            result[r["channel"]] = _build_public(build, with_results=True) if build else None
    return result


@router.get("/releases")
def list_releases(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM releases ORDER BY id DESC LIMIT 200")
    return [db.row_to_dict(r) for r in rows]
