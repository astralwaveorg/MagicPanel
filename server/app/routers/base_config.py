"""产物基础配置：按「引擎默认 / 指定发布目标」维护的顶层键文档。

这是产物内容的最低优先级层：结构化内容（节点、策略组、分流规则）由各自页面维护，
基础配置不允许覆盖；功能模块与发布目标扩展在其之上叠加。

作用范围：
- `target` 为空：引擎默认，作用于该引擎的全部目标；
- `target` 为某个发布目标名：该目标的专属基础配置，叠加在引擎默认之上
  （字典递归、列表整体替换），保存后独立生效，不再随引擎默认变化。
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, security
from ..compiler import render
from ..deps import CurrentUser
from ..routers import builds
from ..services import base_config as base_config_service

router = APIRouter(prefix="/api/v1/base-config", tags=["base-config"])


class BaseConfigBody(BaseModel):
    content: str = Field(default="", max_length=200_000)
    updated_at: str = Field(default="", max_length=64)


class PreviewBody(BaseModel):
    engine: str = "stash"
    target: str = Field(default="", max_length=64)


class ApplyBody(BaseModel):
    engine: str = "stash"
    target: str = Field(default="", max_length=64)
    content: str = Field(default="", max_length=200_000)
    channel: str = "stable"
    note: str = Field(default="", max_length=256)


def _engine(engine: str) -> str:
    if engine not in base_config_service.ENGINES:
        raise HTTPException(400, "引擎仅支持 stash / mihomo")
    return engine


def _check_target(conn, engine: str, name: str) -> str:
    """校验作用范围：目标必须存在且引擎一致；返回目标名（空 = 引擎默认）。"""
    if not name:
        return ""
    row = db.one(conn, "SELECT * FROM targets WHERE name=?", (name,))
    if not row:
        raise HTTPException(404, "发布目标不存在")
    if row["engine"] != engine:
        raise HTTPException(400, f"发布目标“{name}”的引擎是 {row['engine']}，与所选引擎不一致")
    return name


def _load(conn, engine: str, target: str = "") -> tuple[str, dict, str]:
    row = db.one(conn, "SELECT * FROM base_configs WHERE engine=? AND target=?",
                 (engine, target))
    if not row:
        doc = base_config_service.default_doc(engine)
        return base_config_service.to_yaml(doc), doc, ""
    try:
        doc = base_config_service.parse_content(row["content"])
    except ValueError:
        doc = base_config_service.default_doc(engine)
    return row["content"], doc, row["updated_at"]


def _is_default(engine: str, doc: dict, target: str = "") -> bool:
    return base_config_service.normalize(doc) == \
        base_config_service.normalize(base_config_service.default_doc(engine))


def _save(conn, engine: str, target: str, content: str, operator: str) -> dict:
    try:
        doc = base_config_service.parse_content(content)
        base_config_service.validate_doc(doc)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    normalized = base_config_service.normalize(doc)
    text = base_config_service.to_yaml(normalized)
    conn.execute(
        "INSERT INTO base_configs(engine, target, content, updated_at) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(engine, target) DO UPDATE SET content=excluded.content, "
        "updated_at=excluded.updated_at",
        (engine, target, text, db.now()),
    )
    security.audit(conn, operator, "更新基础配置", "base_config",
                   f"{engine}:{target or '默认'}", {"keys": sorted(normalized.keys())})
    return normalized


@router.get("/schema")
def get_schema(engine: str = "stash", user=CurrentUser):
    engine = _engine(engine)
    presets = [
        {"key": key, "label": label, "content": base_config_service.to_yaml(doc)}
        for key, (label, doc) in base_config_service.PRESETS[engine].items()
    ]
    return {
        "engine": engine,
        "fields": base_config_service.schema(engine),
        "groups": base_config_service.GROUP_LABELS,
        "presets": presets,
        "protected": sorted(base_config_service.PROTECTED_KEYS.keys()),
    }


@router.get("/scopes")
def list_scopes(user=CurrentUser):
    """列出可用的作用范围：引擎默认 + 各发布目标。"""
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT name, engine, platform, description "
                             "FROM targets ORDER BY id")
        saved = {(r["engine"], r["target"]) for r in db.all_(
            conn, "SELECT engine, target FROM base_configs WHERE target<>''")}
    scopes = []
    for engine in base_config_service.ENGINES:
        scopes.append({"engine": engine, "target": "", "label": f"{engine} 引擎默认",
                       "platform": "", "customized": (engine, "") in saved})
    for row in rows:
        scopes.append({
            "engine": row["engine"], "target": row["name"],
            "label": f"{row['name']}（{row['platform']}）",
            "platform": row["platform"],
            "description": row["description"],
            "customized": (row["engine"], row["name"]) in saved,
        })
    return {"scopes": scopes}


@router.get("")
def get_base_config(engine: str = "stash", target: str = "",
                    user=CurrentUser):
    engine = _engine(engine)
    with db.connect() as conn:
        _check_target(conn, engine, target)
        content, doc, updated_at = _load(conn, engine, target)
    return {
        "engine": engine,
        "target": target,
        "content": content,
        "doc": base_config_service.normalize(doc),
        "updated_at": updated_at,
        "is_default": _is_default(engine, doc, target),
    }


@router.put("")
def put_base_config(body: BaseConfigBody, engine: str = "stash",
                    target: str = "", user=CurrentUser):
    engine = _engine(engine)
    with db.tx() as conn:
        _check_target(conn, engine, target)
        _, _, updated_at = _load(conn, engine, target)
        if body.updated_at and updated_at and body.updated_at != updated_at:
            raise HTTPException(409, "基础配置已被其他维护者修改，请刷新后再保存")
        _save(conn, engine, target, body.content, user["username"])
        content, doc, updated_at = _load(conn, engine, target)
    return {
        "ok": True,
        "engine": engine,
        "target": target,
        "content": content,
        "doc": base_config_service.normalize(doc),
        "updated_at": updated_at,
        "is_default": _is_default(engine, doc, target),
    }


@router.post("/reset")
def reset_base_config(engine: str = "stash", target: str = "",
                      user=CurrentUser):
    """恢复默认：引擎默认范围恢复为内置默认；目标范围恢复为继承引擎默认。"""
    engine = _engine(engine)
    default = base_config_service.default_doc(engine)
    with db.tx() as conn:
        _check_target(conn, engine, target)
        if target:
            with db.connect() as conn2:
                _, engine_doc, _ = _load(conn2, engine, "")
            default = engine_doc
        _save(conn, engine, target, base_config_service.to_yaml(default),
              user["username"])
        content, doc, updated_at = _load(conn, engine, target)
    return {
        "ok": True,
        "engine": engine,
        "target": target,
        "content": content,
        "doc": base_config_service.normalize(doc),
        "updated_at": updated_at,
        "is_default": _is_default(engine, doc, target),
    }


def _pick_target(conn, engine: str, name: str) -> dict:
    rows = db.all_(conn, "SELECT * FROM targets ORDER BY id")
    if name:
        for row in rows:
            if row["name"] == name:
                return {"name": row["name"], "engine": row["engine"],
                        "platform": row["platform"],
                        "extra_yaml": row["extra_yaml"]}
        raise HTTPException(404, "发布目标不存在")
    for row in rows:
        if row["engine"] == engine:
            return {"name": row["name"], "engine": row["engine"],
                    "platform": row["platform"],
                    "extra_yaml": row["extra_yaml"]}
    raise HTTPException(400, "还没有该引擎的发布目标，请先在“发布目标”中添加")


@router.post("/preview")
def preview(body: PreviewBody, user=CurrentUser):
    engine = _engine(body.engine)
    warnings: list[str] = []
    with db.connect() as conn:
        target = _pick_target(conn, engine, body.target)
        snapshot, _sha = builds.current_policy(conn)
    text = render.render_target(snapshot, target, warnings)
    return {
        "target": target["name"],
        "engine": target["engine"],
        "content": text,
        "warnings": warnings,
        "note": "预览包含 {FEED} / {FEED_HOST} 占位符，客户端实际收到的是替换后的地址。",
    }


@router.post("/apply")
def apply(body: ApplyBody, user=CurrentUser):
    engine = _engine(body.engine)
    if body.channel not in ("stable", "candidate"):
        raise HTTPException(400, "通道仅支持 stable / candidate")
    with db.tx() as conn:
        _check_target(conn, engine, body.target)
        _save(conn, engine, body.target, body.content, user["username"])
    try:
        build_id, status = builds.create_candidate(
            user["username"], note=body.note or "更新基础配置")
    except builds.BuildError as exc:
        raise HTTPException(400, str(exc))
    if status != "success":
        with db.connect() as conn:
            row = builds._get_build(conn, build_id)
        raise HTTPException(400, f"构建未通过校验：{json_results(row)}")
    with db.tx() as conn:
        build = builds._get_build(conn, build_id)
        builds.promote_internal(conn, build, body.channel, "promote",
                                user["username"], body.note or "更新基础配置")
    return {"ok": True, "build_id": build_id, "channel": body.channel,
            "status": status}


def json_results(row) -> str:
    results = json.loads(row["results"] or "{}")
    parts = []
    for name, item in results.items():
        for err in item.get("errors", []):
            parts.append(f"{name}：{err}")
    return "；".join(parts) or "未知错误"
