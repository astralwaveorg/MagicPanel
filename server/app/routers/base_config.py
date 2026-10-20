"""产物基础配置：内置默认 → 通用配置 → 目标通用 → 设备专属 的多级联动。

层级语义（后者覆盖前者）：
① 内置默认：随程序发布，只读可见；
② 通用配置：按引擎维护，作用于该引擎的全部目标与设备；
③ 目标通用：按发布目标维护（可选中间层）；
④ 设备专属：按设备维护，只对该设备最终下发的配置生效。

每层只保存"与上层不同"的差异，因此：
- 上层默认值变化时，本层没显式改过的键会自动跟随；
- "恢复默认"= 清空本层差异，回到继承上层；
- 界面可以逐层展示"生效值来自哪一层"。
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
    device_id: int = 0


class ApplyBody(BaseModel):
    engine: str = "stash"
    target: str = Field(default="", max_length=64)
    device_id: int = 0
    content: str = Field(default="", max_length=200_000)
    channel: str = "stable"
    note: str = Field(default="", max_length=256)


def _engine(engine: str) -> str:
    if engine not in base_config_service.ENGINES:
        raise HTTPException(400, "引擎仅支持 stash / mihomo")
    return engine


def _check_scope(conn, engine: str, target: str, device_id: int) -> tuple[str, int]:
    """校验作用域：目标与设备必须存在且与引擎一致。"""
    target_name = target
    if device_id:
        dev = db.one(conn, "SELECT * FROM devices WHERE id=?", (device_id,))
        if not dev:
            raise HTTPException(404, "设备不存在")
        row = db.one(conn, "SELECT * FROM targets WHERE id=?", (dev["target_id"],))
        if not row:
            raise HTTPException(400, "该设备关联的发布目标不存在")
        if row["engine"] != engine:
            raise HTTPException(400, f"设备所属目标“{row['name']}”的引擎是 {row['engine']}，与所选引擎不一致")
        target_name = row["name"]
    elif target:
        row = db.one(conn, "SELECT * FROM targets WHERE name=?", (target,))
        if not row:
            raise HTTPException(404, "发布目标不存在")
        if row["engine"] != engine:
            raise HTTPException(400, f"发布目标“{target}”的引擎是 {row['engine']}，与所选引擎不一致")
    return target_name, int(device_id or 0)


def _all_docs(conn) -> dict:
    """读取全部作用域的覆盖文档，键为 (engine, target, device_id)。"""
    docs: dict = {}
    for row in db.all_(conn, "SELECT engine, target, device_id, content FROM base_configs"):
        try:
            docs[(row["engine"], row["target"] or "", int(row["device_id"] or 0))] = \
                base_config_service.parse_content(row["content"])
        except ValueError:
            continue
    return docs


def _scope_key(target: str, device_id: int) -> tuple[str, int]:
    """作用域存储键：设备专属用 ('', device_id)，其余用 (target, 0)。"""
    if device_id:
        return "", int(device_id)
    return target or "", 0


def _load_scope(conn, engine: str, target: str, device_id: int):
    key_target, key_device = _scope_key(target, device_id)
    row = db.one(
        conn, "SELECT * FROM base_configs WHERE engine=? AND target=? AND device_id=?",
        (engine, key_target, key_device))
    if not row:
        return "", {}, ""
    try:
        doc = base_config_service.parse_content(row["content"])
    except ValueError:
        doc = {}
    return row["content"], doc, row["updated_at"]


def _save_scope(conn, engine: str, target: str, device_id: int,
                content: str, operator: str) -> dict:
    try:
        doc = base_config_service.parse_content(content)
        base_config_service.validate_doc(doc)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    normalized = base_config_service.normalize(doc)
    text = base_config_service.to_yaml(normalized)
    key_target, key_device = _scope_key(target, device_id)
    conn.execute(
        "INSERT INTO base_configs(engine, target, device_id, content, updated_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(engine, target, device_id) DO UPDATE SET content=excluded.content, "
        "updated_at=excluded.updated_at",
        (engine, key_target, key_device, text, db.now()))
    label = f"{engine}:{target or '通用'}:{device_id or 0}"
    security.audit(conn, operator, "更新基础配置", "base_config", label,
                   {"keys": sorted(normalized.keys())})
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
    """列出全部作用域（内置默认 / 通用配置 / 目标通用 / 设备专属）。"""
    with db.connect() as conn:
        docs = _all_docs(conn)
        targets = db.all_(conn, "SELECT * FROM targets ORDER BY id")
        devices = db.all_(conn, "SELECT * FROM devices ORDER BY id")
    scopes = []
    for engine in base_config_service.ENGINES:
        scopes.append({
            "kind": "builtin", "engine": engine, "target": "", "device_id": 0,
            "label": f"{engine} 内置默认",
            "detail": "程序内置，只读；作为该引擎全部配置的起点",
            "customized": False,
        })
    for engine in base_config_service.ENGINES:
        scopes.append({
            "kind": "engine", "engine": engine, "target": "", "device_id": 0,
            "label": f"{engine} 通用配置",
            "detail": "覆盖内置默认，作用于该引擎的全部目标与设备",
            "customized": bool(docs.get((engine, "", 0))),
        })
    for row in targets:
        key = (row["engine"], row["name"], 0)
        if docs.get(key):
            scopes.append({
                "kind": "target", "engine": row["engine"], "target": row["name"],
                "device_id": 0, "label": f"{row['name']}（目标通用）",
                "detail": row["description"] or "该发布目标专用的基础配置",
                "customized": True,
            })
    for dev in devices:
        target = next((t for t in targets if t["id"] == dev["target_id"]), None)
        if not target:
            continue
        key = (target["engine"], "", int(dev["id"]))
        scopes.append({
            "kind": "device", "engine": target["engine"], "target": target["name"],
            "device_id": int(dev["id"]),
            "label": f"{dev['note'] or dev['name']}（设备专属）",
            "detail": f"目标 {target['name']}；只影响这台设备",
            "customized": bool(docs.get(key)),
        })
    return {"scopes": scopes}


@router.get("")
def get_base_config(engine: str = "stash", target: str = "", device_id: int = 0,
                    user=CurrentUser):
    """返回该作用域的完整信息：继承值、本层差异、生效值、每个键的来源。"""
    engine = _engine(engine)
    with db.connect() as conn:
        target_name, dev_id = _check_scope(conn, engine, target, device_id)
        docs = _all_docs(conn)
        _, overlay, updated_at = _load_scope(conn, engine, target_name, dev_id)
    layers = base_config_service.scope_layers(engine, target_name, dev_id, docs)
    inherited, _ = base_config_service.cascade(layers[:-1]) if len(layers) > 1 else ({}, {})
    effective, sources = base_config_service.cascade(layers)
    return {
        "engine": engine,
        "target": target_name,
        "device_id": dev_id,
        "inherited": inherited,
        "overlay": overlay,
        "effective": effective,
        "sources": sources,
        "layers": [{"label": label, "keys": sorted(doc.keys())} for label, doc in layers],
        "content": base_config_service.to_yaml(effective),
        "updated_at": updated_at,
        "is_default": not overlay,
    }


@router.put("")
def put_base_config(body: BaseConfigBody, engine: str = "stash", target: str = "",
                    device_id: int = 0, user=CurrentUser):
    """保存本层覆盖：提交的是"本层编辑后的生效值"，服务端自动与上层求差异。"""
    engine = _engine(engine)
    with db.tx() as conn:
        target_name, dev_id = _check_scope(conn, engine, target, device_id)
        docs = _all_docs(conn)
        _, _, updated_at = _load_scope(conn, engine, target_name, dev_id)
        if body.updated_at and updated_at and body.updated_at != updated_at:
            raise HTTPException(409, "基础配置已被其他维护者修改，请刷新后再保存")
        try:
            effective = base_config_service.parse_content(body.content)
            base_config_service.validate_doc(effective)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        layers = base_config_service.scope_layers(engine, target_name, dev_id, docs)
        inherited, _ = (base_config_service.cascade(layers[:-1])
                        if len(layers) > 1 else ({}, {}))
        overlay = base_config_service.diff_overlay(inherited, effective)
        base_config_service.validate_doc(overlay)
        _save_scope(conn, engine, target_name, dev_id,
                    base_config_service.to_yaml(base_config_service.normalize(overlay)),
                    user["username"])
        content, stored, updated_at = _load_scope(conn, engine, target_name, dev_id)
        docs = _all_docs(conn)
    layers = base_config_service.scope_layers(engine, target_name, dev_id, docs)
    effective, sources = base_config_service.cascade(layers)
    return {
        "ok": True,
        "engine": engine,
        "target": target_name,
        "device_id": dev_id,
        "overlay": stored,
        "effective": effective,
        "sources": sources,
        "content": content,
        "updated_at": updated_at,
        "is_default": not stored,
    }


@router.post("/reset")
def reset_base_config(engine: str = "stash", target: str = "", device_id: int = 0,
                      user=CurrentUser):
    """恢复默认：清空本层覆盖，回到继承上层（内置默认 → 通用 → 目标）。"""
    engine = _engine(engine)
    with db.tx() as conn:
        target_name, dev_id = _check_scope(conn, engine, target, device_id)
        _, overlay, _ = _load_scope(conn, engine, target_name, dev_id)
        # 个人直连域名与 Fake-IP 过滤属于「配置」而非「默认值」，恢复默认时保留
        keep = {key: overlay[key] for key in
                (base_config_service.DIRECT_DOMAINS_KEY,
                 base_config_service.FAKE_IP_FILTER_KEY,
                 base_config_service.PANEL_DIRECT_KEY)
                if key in overlay}
        if keep:
            _save_scope(conn, engine, target_name, dev_id,
                        base_config_service.to_yaml(keep), user["username"])
        else:
            key_target, key_device = _scope_key(target_name, dev_id)
            conn.execute(
                "DELETE FROM base_configs WHERE engine=? AND target=? AND device_id=?",
                (engine, key_target, key_device))
        docs = _all_docs(conn)
    layers = base_config_service.scope_layers(engine, target_name, dev_id, docs)
    effective, sources = base_config_service.cascade(layers)
    return {
        "ok": True,
        "engine": engine,
        "target": target_name,
        "device_id": dev_id,
        "overlay": {},
        "effective": effective,
        "sources": sources,
        "content": base_config_service.to_yaml(effective),
        "updated_at": "",
        "is_default": True,
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
    if body.device_id:
        with db.connect() as conn:
            docs = _all_docs(conn)
            dev = db.one(conn, "SELECT * FROM devices WHERE id=?", (body.device_id,))
        if dev:
            device_doc = docs.get((target["engine"], "", int(dev["id"])))
            if device_doc:
                try:
                    text = render.apply_device_overlay(
                        text, base_config_service.to_yaml(device_doc))
                except ValueError as exc:
                    raise HTTPException(400, str(exc))
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
        target_name, dev_id = _check_scope(conn, engine, body.target, body.device_id)
        docs = _all_docs(conn)
        try:
            effective = base_config_service.parse_content(body.content)
            base_config_service.validate_doc(effective)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        layers = base_config_service.scope_layers(engine, target_name, dev_id, docs)
        inherited, _ = (base_config_service.cascade(layers[:-1])
                        if len(layers) > 1 else ({}, {}))
        overlay = base_config_service.diff_overlay(inherited, effective)
        base_config_service.validate_doc(overlay)
        _save_scope(conn, engine, target_name, dev_id,
                    base_config_service.to_yaml(base_config_service.normalize(overlay)),
                    user["username"])
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
