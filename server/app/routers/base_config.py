"""产物基础配置：系统默认 → 通用配置 → 目标通用 → 设备配置 的多级联动。

层级语义（后者覆盖前者）：
① 系统默认：随程序发布的默认内容（按引擎），可直接改；
② 通用配置：按「引擎 + 平台」维护，与"引擎平台"一一对应（如 Stash · macOS）；
③ 设备配置：按设备维护，只对该设备最终下发的配置生效。

每层只保存"与上层不同"的差异，因此：
- 上层默认值变化时，本层没显式改过的键会自动跟随；
- "恢复默认"= 清空本层差异，回到继承上层；
- 界面可以逐层展示"生效值来自哪一层"。
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..compiler import render
from ..deps import CurrentUser
from ..routers import builds
from ..services import base_config as base_config_service
from ..services import releases

ENGINE_LABELS = config.ENGINE_LABELS
PLATFORM_LABELS = config.PLATFORM_LABELS

router = APIRouter(prefix="/api/v1/base-config", tags=["base-config"])


class BaseConfigBody(BaseModel):
    content: str = Field(default="", max_length=200_000)
    updated_at: str = Field(default="", max_length=64)


class PreviewBody(BaseModel):
    engine: str = "stash"
    platform: str = Field(default="", max_length=64)
    device_id: int = 0


class ApplyBody(BaseModel):
    engine: str = "stash"
    platform: str = Field(default="", max_length=64)
    device_id: int = 0
    content: str = Field(default="", max_length=200_000)
    env: str = "production"
    note: str = Field(default="", max_length=256)


def _engine(engine: str) -> str:
    if engine not in base_config_service.ENGINES:
        raise HTTPException(400, "引擎仅支持 stash / mihomo")
    return engine


def _check_scope(conn, engine: str, platform: str, device_id: int,
                 for_write: bool = False) -> tuple[str, int]:
    """校验作用域：平台与设备必须存在且与引擎一致。

    不带平台也不带设备时表示"系统默认"——可以写入：改的是"默认值之上的差异"，
    差异单独存着，随时能删掉恢复默认。
    """
    plat = platform
    if not device_id and not platform:
        return "", 0
    if device_id:
        dev = db.one(conn, "SELECT * FROM devices WHERE id=?", (device_id,))
        if not dev:
            raise HTTPException(404, "设备不存在")
        row = db.one(conn, "SELECT * FROM targets WHERE id=?", (dev["target_id"],))
        if not row:
            raise HTTPException(400, "该设备关联的引擎平台不存在")
        if row["engine"] != engine:
            raise HTTPException(400, f"设备所属引擎平台的引擎是 {row['engine']}，与所选引擎不一致")
        plat = row["platform"]
    elif platform and platform not in PLATFORM_LABELS:
        raise HTTPException(400, f"平台仅支持：{'、'.join(PLATFORM_LABELS)}")
    return plat, int(device_id or 0)


def _all_docs(conn) -> dict:
    """读取全部作用域的覆盖文档，键为 (engine, platform, device_id)。"""
    docs: dict = {}
    for row in db.all_(conn, "SELECT engine, platform, device_id, content FROM base_configs"):
        try:
            docs[(row["engine"], row["platform"] or "", int(row["device_id"] or 0))] = \
                base_config_service.parse_content(row["content"])
        except ValueError:
            continue
    return docs


def _load_scope(conn, engine: str, platform: str, device_id: int):
    key_platform, key_device = (platform or "", int(device_id or 0))
    row = db.one(
        conn, "SELECT * FROM base_configs WHERE engine=? AND platform=? AND device_id=?",
        (engine, key_platform, key_device))
    if not row:
        return "", {}, ""
    try:
        doc = base_config_service.parse_content(row["content"])
    except ValueError:
        doc = {}
    return row["content"], doc, row["updated_at"]


def _save_scope(conn, engine: str, platform: str, device_id: int,
                content: str, operator: str) -> dict:
    try:
        doc = base_config_service.parse_content(content)
        base_config_service.validate_doc(doc)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    normalized = base_config_service.normalize(doc)
    text = base_config_service.to_yaml(normalized)
    key_platform, key_device = (platform or "", int(device_id or 0))
    conn.execute(
        "INSERT INTO base_configs(engine, platform, device_id, content, updated_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(engine, platform, device_id) DO UPDATE SET content=excluded.content, "
        "updated_at=excluded.updated_at",
        (engine, key_platform, key_device, text, db.now()))
    label = f"{engine}:{platform or '通用'}:{device_id or 0}"
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
    """列出全部作用域（系统默认 / 通用配置 / 目标通用 / 设备配置）。"""
    with db.connect() as conn:
        docs = _all_docs(conn)
        # 顺序跟着各自页面走：引擎平台页按 sort，设备管理页按 sort
        targets = db.all_(conn, "SELECT * FROM targets ORDER BY sort, id")
        devices = db.all_(conn, "SELECT * FROM devices ORDER BY sort, id")
    scopes = []
    for engine in base_config_service.ENGINES:
        scopes.append({
            "kind": "builtin", "engine": engine, "platform": "", "device_id": 0,
            "label": f"{ENGINE_LABELS.get(engine, engine)} 默认",
            "name": f"{ENGINE_LABELS.get(engine, engine)} 默认",
            "detail": "系统默认值（随程序发布）；可直接修改，改动以差异保存，可一键恢复默认",
            "customized": bool(docs.get((engine, "", 0))),
        })
    # 通用配置：按「引擎 + 平台」，与引擎平台一一对应
    # 顺序 = 引擎平台页的顺序；名称：该「引擎 + 平台」只有一个引擎平台时
    # 直接用它的名字（与引擎平台页一致），有多个时退回「引擎 · 平台」
    pair_names: dict[tuple, list] = {}
    for row in targets:
        pair_names.setdefault((row["engine"], row["platform"]), []).append(row["name"])
    seen_pairs = []
    for row in targets:
        pair = (row["engine"], row["platform"])
        if pair in seen_pairs:
            continue
        seen_pairs.append(pair)
        platform = PLATFORM_LABELS.get(row["platform"], row["platform"])
        names = pair_names.get(pair) or []
        label = (names[0] if len(names) == 1
                 else f"{ENGINE_LABELS.get(row['engine'], row['engine'])} · {platform}")
        scopes.append({
            "kind": "general", "engine": row["engine"], "platform": row["platform"],
            "device_id": 0,
            "label": label,
            "name": label,
            "detail": "覆盖系统默认；作用于该引擎与平台的全部设备"
                      + (f"（对应引擎平台：{'、'.join(names)}）" if len(names) > 1 else ""),
            "customized": bool(docs.get((row["engine"], row["platform"], 0))),
        })
    for dev in devices:
        target = next((t for t in targets if t["id"] == dev["target_id"]), None)
        if not target:
            continue
        key = (target["engine"], target["platform"], int(dev["id"]))
        platform = PLATFORM_LABELS.get(target["platform"], target["platform"])
        scopes.append({
            "kind": "device", "engine": target["engine"],
            "platform": target["platform"], "device_id": int(dev["id"]),
            "label": f"{dev['name']}（设备配置）",
            "name": dev["name"],
            "detail": f"{ENGINE_LABELS.get(target['engine'], target['engine'])} · {platform}",
            "customized": bool(docs.get(key)),
        })
    return {"scopes": scopes}


@router.get("")
def get_base_config(engine: str = "stash", platform: str = "", device_id: int = 0,
                    user=CurrentUser):
    """返回该作用域的完整信息：继承值、本层差异、生效值、每个键的来源。"""
    engine = _engine(engine)
    with db.connect() as conn:
        plat, dev_id = _check_scope(conn, engine, platform, device_id)
        docs = _all_docs(conn)
        _, overlay, updated_at = _load_scope(conn, engine, plat, dev_id)
    layers = base_config_service.scope_layers(engine, plat, dev_id, docs)
    inherited, _ = base_config_service.cascade(layers[:-1]) if len(layers) > 1 else ({}, {})
    effective, sources = base_config_service.cascade(layers)
    return {
        "engine": engine,
        "platform": plat,
        "device_id": dev_id,
        "readonly": False,   # 系统默认也可改（存的是与默认值的差异）
        "inherited": inherited,
        "overlay": overlay,
        "effective": effective,
        "sources": sources,
        "leaf_sources": base_config_service.leaf_sources(layers),
        "layers": [{"label": label, "keys": sorted(doc.keys())} for label, doc in layers],
        "content": base_config_service.to_yaml(effective),
        "updated_at": updated_at,
        "is_default": not overlay,
    }


@router.put("")
def put_base_config(body: BaseConfigBody, engine: str = "stash", platform: str = "",
                    device_id: int = 0, user=CurrentUser):
    """保存本层覆盖：提交的是"本层编辑后的生效值"，服务端自动与上层求差异。"""
    engine = _engine(engine)
    with db.tx() as conn:
        plat, dev_id = _check_scope(conn, engine, platform, device_id, for_write=True)
        docs = _all_docs(conn)
        _, _, updated_at = _load_scope(conn, engine, plat, dev_id)
        if body.updated_at and updated_at and body.updated_at != updated_at:
            raise HTTPException(409, "基础配置已被其他维护者修改，请刷新后再保存")
        try:
            effective = base_config_service.parse_content(body.content)
            base_config_service.validate_doc(effective, device_scope=bool(dev_id))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        layers = base_config_service.scope_layers(engine, plat, dev_id, docs)
        if not plat and not dev_id:
            # 系统默认：与"程序默认值"求差异，只把改动过的键存下来
            inherited = base_config_service.default_doc(engine)
        else:
            inherited, _ = (base_config_service.cascade(layers[:-1])
                            if len(layers) > 1 else ({}, {}))
        overlay = base_config_service.diff_overlay(inherited, effective)
        base_config_service.validate_doc(overlay, device_scope=bool(dev_id))
        _save_scope(conn, engine, plat, dev_id,
                    base_config_service.to_yaml(base_config_service.normalize(overlay)),
                    user["username"])
        content, stored, updated_at = _load_scope(conn, engine, plat, dev_id)
        docs = _all_docs(conn)
    layers = base_config_service.scope_layers(engine, plat, dev_id, docs)
    effective, sources = base_config_service.cascade(layers)
    return {
        "ok": True,
        "engine": engine,
        "platform": plat,
        "device_id": dev_id,
        "overlay": stored,
        "effective": effective,
        "sources": sources,
        "leaf_sources": base_config_service.leaf_sources(layers),
        "content": content,
        "updated_at": updated_at,
        "is_default": not stored,
    }


@router.post("/reset")
def reset_base_config(engine: str = "stash", platform: str = "", device_id: int = 0,
                      user=CurrentUser):
    """恢复默认：清空本层覆盖，回到继承上层（系统默认 → 通用配置）。"""
    engine = _engine(engine)
    with db.tx() as conn:
        plat, dev_id = _check_scope(conn, engine, platform, device_id, for_write=True)
        _, overlay, _ = _load_scope(conn, engine, plat, dev_id)
        if not plat and not dev_id:
            # 系统默认：删掉覆盖记录即恢复默认（默认值来自源码，不需要保留任何键）
            conn.execute(
                "DELETE FROM base_configs WHERE engine=? AND platform='' AND device_id=0",
                (engine,))
            overlay = {}
            docs = _all_docs(conn)
            layers = base_config_service.scope_layers(engine, plat, dev_id, docs)
            effective, sources = base_config_service.cascade(layers)
            security.audit(conn, user["username"], "恢复系统默认",
                           "base_config", f"{engine}:内置", {})
            return {
                "ok": True, "engine": engine, "platform": plat, "device_id": dev_id,
                "overlay": overlay, "effective": effective, "sources": sources,
                "leaf_sources": base_config_service.leaf_sources(layers),
                "content": base_config_service.to_yaml(effective),
                "updated_at": "", "is_default": True,
            }
        # 个人直连域名与 Fake-IP 过滤属于「配置」而非「默认值」，恢复默认时保留
        keep = {key: overlay[key] for key in
                (base_config_service.DIRECT_DOMAINS_KEY,
                 base_config_service.FAKE_IP_FILTER_KEY,
                 base_config_service.PANEL_DIRECT_KEY)
                if key in overlay}
        if keep:
            _save_scope(conn, engine, plat, dev_id,
                        base_config_service.to_yaml(keep), user["username"])
            overlay = keep
        else:
            conn.execute(
                "DELETE FROM base_configs WHERE engine=? AND platform=? AND device_id=?",
                (engine, plat or "", dev_id))
        docs = _all_docs(conn)
    layers = base_config_service.scope_layers(engine, plat, dev_id, docs)
    effective, sources = base_config_service.cascade(layers)
    return {
        "ok": True,
        "engine": engine,
        "platform": plat,
        "device_id": dev_id,
        "overlay": overlay,
        "effective": effective,
        "sources": sources,
        "content": base_config_service.to_yaml(effective),
        "updated_at": "",
        "is_default": True,
    }


def _pick_target(conn, engine: str, platform: str) -> dict:
    """按「引擎 + 平台」挑一个引擎平台（预览用）。"""
    rows = db.all_(conn, "SELECT * FROM targets ORDER BY id")
    if platform:
        for row in rows:
            if row["engine"] == engine and row["platform"] == platform:
                return {"name": row["name"], "engine": row["engine"],
                        "platform": row["platform"],
                        "extra_yaml": row["extra_yaml"]}
        raise HTTPException(404, "没有该引擎与平台的引擎平台")
    for row in rows:
        if row["engine"] == engine:
            return {"name": row["name"], "engine": row["engine"],
                    "platform": row["platform"],
                    "extra_yaml": row["extra_yaml"]}
    raise HTTPException(400, "还没有该引擎的引擎平台，请先在“引擎平台”中添加")


@router.post("/preview")
def preview(body: PreviewBody, user=CurrentUser):
    engine = _engine(body.engine)
    warnings: list[str] = []
    with db.connect() as conn:
        target = _pick_target(conn, engine, body.platform)
        snapshot, _sha = builds.current_policy(conn)
    text = render.render_target(snapshot, target, warnings)
    if body.device_id:
        with db.connect() as conn:
            docs = _all_docs(conn)
            dev = db.one(conn, "SELECT * FROM devices WHERE id=?", (body.device_id,))
        if dev:
            device_doc = docs.get((target["engine"], target["platform"], int(dev["id"])))
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
    if body.env not in ("production", "testing"):
        raise HTTPException(400, "发布环境仅支持 production / testing")
    with db.tx() as conn:
        plat, dev_id = _check_scope(conn, engine, body.platform, body.device_id)
        docs = _all_docs(conn)
        try:
            effective = base_config_service.parse_content(body.content)
            base_config_service.validate_doc(effective, device_scope=bool(dev_id))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        layers = base_config_service.scope_layers(engine, plat, dev_id, docs)
        inherited, _ = (base_config_service.cascade(layers[:-1])
                        if len(layers) > 1 else ({}, {}))
        overlay = base_config_service.diff_overlay(inherited, effective)
        base_config_service.validate_doc(overlay, device_scope=bool(dev_id))
        _save_scope(conn, engine, plat, dev_id,
                    base_config_service.to_yaml(base_config_service.normalize(overlay)),
                    user["username"])
    try:
        build_id, status = builds.create_build(
            user["username"], note=body.note or "更新基础配置")
    except builds.BuildError as exc:
        raise HTTPException(400, str(exc))
    if status != "success":
        with db.connect() as conn:
            row = builds._get_build(conn, build_id)
        raise HTTPException(400, f"构建未通过校验：{json_results(row)}")
    try:
        with db.tx(immediate=True) as conn:
            build = builds._get_build(conn, build_id)
            result = releases.publish_build(
                conn, build, user["username"], body.note or "更新基础配置",
                releases.Env(body.env))
    except releases.ReleaseError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "build_id": build_id, "env": body.env,
            "status": status, "release": result}


def json_results(row) -> str:
    results = json.loads(row["results"] or "{}")
    parts = []
    for name, item in results.items():
        for err in item.get("errors", []):
            parts.append(f"{name}：{err}")
    return "；".join(parts) or "未知错误"
