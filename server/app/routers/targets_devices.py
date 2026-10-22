"""引擎平台（引擎 + 平台，对应一类客户端）与设备管理。

设备令牌只在创建／轮换时返回一次；服务器只保存摘要。
泄露后的处置：轮换或撤销令牌，已下发的节点凭据需联系机场重置。
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import json

import yaml

from .. import db, security
from ..deps import CurrentUser
from ..services import base_config as base_config_service
from ..services import refs

router = APIRouter(prefix="/api/v1", tags=["targets-devices"])

ENGINES = {"stash", "mihomo"}
PLATFORMS = {"ios", "macos", "tvos", "windows", "android", "linux"}
ENVS = {"production", "testing"}


class TargetBody(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    engine: str
    platform: str
    description: str = Field(default="", max_length=256)
    extra_yaml: str = Field(default="", max_length=200_000)


class DeviceBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    platform: str
    target_id: int
    env: str = "production"
    note: str = Field(default="", max_length=256)
    # 设备级个性化统一走「产物配置 → 设备独立配置」作用域，
    # 这里的 extra_yaml 曾是另一条从未接通的通道（写了不生效），已移除。


def _check_target(body: TargetBody) -> None:
    if body.engine not in ENGINES:
        raise HTTPException(400, "引擎仅支持 stash / mihomo")
    if body.platform not in PLATFORMS:
        raise HTTPException(400, f"平台仅支持：{'、'.join(sorted(PLATFORMS))}")
    if body.extra_yaml.strip():
        try:
            overlay = yaml.safe_load(body.extra_yaml)
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"平台扩展 YAML 解析失败：{exc}")
        if overlay is not None and not isinstance(overlay, dict):
            raise HTTPException(400, "平台扩展必须是 YAML 映射（键值结构）")
        for key, reason in base_config_service.PROTECTED_KEYS.items():
            if overlay and key in overlay:
                raise HTTPException(400, f"平台扩展不能包含“{key}”：{reason}")


def _target_public(row) -> dict:
    return db.row_to_dict(row)


def _device_public(row, base_url: str = "") -> dict:
    # name 是下载文件名；note 是用户可读的设备名，缺省时回退文件名。
    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row["note"] or row["name"],
        "platform": row["platform"],
        "target_id": row["target_id"],
        "env": row["env"],
        "token_hint": row["token_hint"],
        "note": row["note"],
        "created_at": row["created_at"],
        "last_pull_at": row["last_pull_at"],
        "last_pull_ip": row["last_pull_ip"],
        "pull_count": row["pull_count"],
    }


def _get_target(conn, tid: int):
    row = db.one(conn, "SELECT * FROM targets WHERE id=?", (tid,))
    if not row:
        raise HTTPException(404, "引擎平台不存在")
    return row


def _remap_target_refs(conn, old_name: str, new_name: str) -> int:
    """引擎平台改名后，同步更新策略组与规则里的"适用目标"引用。

    不这样做的话，改名会让引用指向不存在的引擎平台，
    对应的策略组与规则会在构建时被静默剔除（产物少了一大片却没有任何提示）。
    """
    changed = 0
    for table in ("proxy_groups", "rules"):
        for row in db.all_(conn, f"SELECT id, targets FROM {table} "
                                 "WHERE targets IS NOT NULL AND targets <> '' "
                                 "AND targets <> '[]'"):
            try:
                names = json.loads(row["targets"])
            except (TypeError, ValueError):
                continue
            if not isinstance(names, list) or old_name not in names:
                continue
            names = [new_name if n == old_name else n for n in names]
            conn.execute(f"UPDATE {table} SET targets=? WHERE id=?",
                         (json.dumps(names, ensure_ascii=False), row["id"]))
            changed += 1
    return changed


def _clean_target_refs(conn, name: str) -> int:
    """删除引擎平台后，清理策略组与规则里指向它的引用。"""
    changed = 0
    for table in ("proxy_groups", "rules"):
        for row in db.all_(conn, f"SELECT id, targets FROM {table} "
                                 "WHERE targets IS NOT NULL AND targets <> '' "
                                 "AND targets <> '[]'"):
            try:
                names = json.loads(row["targets"])
            except (TypeError, ValueError):
                continue
            if not isinstance(names, list) or name not in names:
                continue
            names = [n for n in names if n != name]
            conn.execute(f"UPDATE {table} SET targets=? WHERE id=?",
                         (json.dumps(names, ensure_ascii=False), row["id"]))
            changed += 1
    return changed


def _get_device(conn, did: int):
    row = db.one(conn, "SELECT * FROM devices WHERE id=?", (did,))
    if not row:
        raise HTTPException(404, "设备不存在")
    return row


@router.get("/targets/page")
def list_targets_paged(limit: int = 50, offset: int = 0, keyword: str = "",
                       user=CurrentUser):
    """引擎平台分页列表。"""
    with db.connect() as conn:
        where, args = "", []
        if keyword:
            where = "WHERE name LIKE ?"
            args = [f"%{keyword}%"]
        data = db.paged(conn, "targets", where, args, "sort, id", limit, offset)
    data["items"] = [_target_public(r) for r in data["items"]]
    return data


@router.get("/targets")
def list_targets(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM targets ORDER BY sort, id")
    return [_target_public(r) for r in rows]


def _rekey_device_base_config(conn, device_id: int, engine: str,
                              platform: str) -> None:
    """设备独立配置的键 = (引擎, 平台, 设备)，必须跟着设备所在的引擎平台走。

    引擎平台改了引擎/平台，或设备迁移到别的引擎平台后，旧键会让这一层
    配置悄悄失效（界面看不到、下发也不生效）。
    """
    rows = db.all_(conn, "SELECT engine, platform, content FROM base_configs "
                         "WHERE device_id=?", (device_id,))
    for row in rows:
        if row["engine"] == engine and row["platform"] == platform:
            continue
        taken = db.one(
            conn, "SELECT 1 FROM base_configs WHERE engine=? AND platform=? "
                  "AND device_id=?", (engine, platform, device_id))
        if taken:
            # 目标键已被占用：先并入对方（同名键取对方的值），再删旧行
            conn.execute("DELETE FROM base_configs WHERE engine=? AND platform=? "
                         "AND device_id=?",
                         (row["engine"], row["platform"], device_id))
            continue
        conn.execute("UPDATE base_configs SET engine=?, platform=? "
                     "WHERE engine=? AND platform=? AND device_id=?",
                     (engine, platform, row["engine"], row["platform"], device_id))


def _check_engine_platform_unique(conn, engine: str, platform: str,
                                 exclude_id: int | None = None) -> None:
    """同一「引擎 + 平台」只能有一个引擎平台。

    引擎平台代表"本项目支持的某引擎在某平台上的产物"，
    它不是给某个人用的：个性化（谁走哪条规则、谁用哪个策略组）
    应该落在设备上，而不是复制一份引擎平台。
    """
    sql = "SELECT id, name FROM targets WHERE engine=? AND platform=?"
    args: list = [engine, platform]
    if exclude_id:
        sql += " AND id!=?"
        args.append(exclude_id)
    row = db.one(conn, sql, tuple(args))
    if row:
        raise HTTPException(
            409,
            f"「{engine} + {platform}」已存在引擎平台“{row['name']}”。"
            "同一引擎 + 平台只能有一个；个性化请在“设备管理”里配置设备独立配置。")


@router.post("/targets", status_code=201)
def create_target(body: TargetBody, user=CurrentUser):
    _check_target(body)
    try:
        with db.tx() as conn:
            if db.one(conn, "SELECT id FROM targets WHERE name=?", (body.name,)):
                raise HTTPException(409, "同名引擎平台已存在")
            _check_engine_platform_unique(conn, body.engine, body.platform)
            now = db.now()
            sort = db.one(conn, "SELECT COALESCE(MAX(sort), 0) + 1 AS n FROM targets")["n"]
            cur = db.insert_unique(conn,
                "INSERT INTO targets(name, engine, platform, description, extra_yaml, "
                "sort, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (body.name, body.engine, body.platform, body.description,
                 body.extra_yaml, sort, now, now),
            )
            security.audit(conn, user["username"], "新增引擎平台", "target", cur.lastrowid,
                           {"name": body.name})
            row = _get_target(conn, cur.lastrowid)
    except db.UniqueViolation:
        raise HTTPException(409, "同名引擎平台已存在")

    return _target_public(row)


@router.post("/targets/reorder")
def reorder_targets(ids: list[int], user=CurrentUser):
    """列表已分页：按提交的这些 id 重排（它们之间按新顺序，其余记录不动）。"""
    with db.tx() as conn:
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "排序列表里有重复项")
        known = {r["id"] for r in db.all_(conn, "SELECT id FROM targets")}
        if any(i not in known for i in ids):
            raise HTTPException(400, "排序列表包含不存在的记录")
        if not db.reorder_subset(conn, "targets", ids):
            raise HTTPException(400, "排序未生效")
        security.audit(conn, user["username"], "调整引擎平台顺序", "target", "")
    return {"ok": True}


@router.put("/targets/{tid}")
def update_target(tid: int, body: TargetBody, user=CurrentUser):
    _check_target(body)
    with db.tx() as conn:
        _get_target(conn, tid)
        clash = db.one(
            conn, "SELECT id FROM targets WHERE name=? AND id!=?", (body.name, tid)
        )
        if clash:
            raise HTTPException(409, "同名引擎平台已存在")
        _check_engine_platform_unique(conn, body.engine, body.platform, exclude_id=tid)
        old = _get_target(conn, tid)
        conn.execute(
            "UPDATE targets SET name=?, engine=?, platform=?, description=?, "
            "extra_yaml=?, updated_at=? WHERE id=?",
            (body.name, body.engine, body.platform, body.description,
             body.extra_yaml, db.now(), tid),
        )
        remapped = 0
        if old["name"] != body.name:
            remapped = _remap_target_refs(conn, old["name"], body.name)
        if old["engine"] != body.engine or old["platform"] != body.platform:
            for dev in db.all_(conn, "SELECT id FROM devices WHERE target_id=?",
                               (tid,)):
                _rekey_device_base_config(conn, int(dev["id"]), body.engine,
                                          body.platform)
        security.audit(conn, user["username"], "更新引擎平台", "target", tid,
                       {"name": body.name, "remapped_refs": remapped})
        row = _get_target(conn, tid)
    return _target_public(row)


@router.delete("/targets/{tid}")
def delete_target(tid: int, force: bool = False, move_to: int | None = None,
                  user=CurrentUser):
    """删除引擎平台。

    还有设备在用它时默认拒绝，并返回设备清单与可选的目标平台；
    带 force=1 时把这些设备迁移到 move_to 指定的平台再删除。
    """
    with db.tx() as conn:
        row = _get_target(conn, tid)
        devices = refs.target_devices(conn, tid)
        if devices and not force:
            others = [
                {"id": t["id"], "name": t["name"], "platform": t["platform"]}
                for t in db.all_(
                    conn, "SELECT id, name, platform FROM targets "
                          "WHERE id!=? ORDER BY sort, id", (tid,))
            ]
            raise HTTPException(409, detail={
                "code": "target_in_use",
                "message": f"引擎平台“{row['name']}”仍有 {len(devices)} 台设备在用",
                "target": {"id": tid, "name": row["name"]},
                "references": [
                    {"id": d["id"], "name": d["name"], "type": "设备",
                     "extra": d.get("platform") or ""} for d in devices
                ],
                "candidates": others,
            })
        moved: list[str] = []
        if devices:
            if not move_to:
                raise HTTPException(400, "请先指定把设备迁移到哪个引擎平台")
            dest = db.one(conn, "SELECT id, name FROM targets WHERE id=?", (move_to,))
            if not dest:
                raise HTTPException(400, "目标引擎平台不存在")
            if dest["id"] == tid:
                raise HTTPException(400, "设备不能迁移到正在删除的引擎平台")
            conn.execute("UPDATE devices SET target_id=? WHERE target_id=?",
                         (dest["id"], tid))
            moved = [d["name"] for d in devices]
        cleaned = _clean_target_refs(conn, row["name"])
        conn.execute("DELETE FROM targets WHERE id=?", (tid,))
        security.audit(conn, user["username"], "删除引擎平台", "target", tid,
                       {"name": row["name"], "moved_devices": moved})
    return {"ok": True, "moved_devices": moved}


# ---- 设备 ----

def subscription_url(request: Request, conn, token: str) -> str:
    base = db.get_setting(conn, "base_url", "").rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/feed/{token}/config.yaml"


@router.get("/devices/page")
def list_devices_paged(limit: int = 50, offset: int = 0, keyword: str = "",
                       user=CurrentUser):
    """设备分页列表。"""
    with db.connect() as conn:
        where, args = "", []
        if keyword:
            where = "WHERE name LIKE ? OR note LIKE ?"
            args = [f"%{keyword}%", f"%{keyword}%"]
        data = db.paged(conn, "devices", where, args, "sort, id", limit, offset)
    data["items"] = [_device_public(r) for r in data["items"]]
    return data


@router.get("/devices")
def list_devices(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM devices ORDER BY sort, id")
    return [_device_public(r) for r in rows]


@router.post("/devices", status_code=201)
def create_device(body: DeviceBody, request: Request, user=CurrentUser):
    if body.env not in ENVS:
        raise HTTPException(400, "订阅环境仅支持 production / testing")
    if body.platform not in PLATFORMS:
        raise HTTPException(400, f"平台仅支持：{'、'.join(sorted(PLATFORMS))}")
    token = security.new_device_token()
    with db.tx() as conn:
        _get_target(conn, body.target_id)
        if db.one(conn, "SELECT id FROM devices WHERE name=?", (body.name,)):
            raise HTTPException(409, "同名设备已存在")
        sort = (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM devices"))["s"]
        cur = conn.execute(
            "INSERT INTO devices(name, platform, target_id, env, token_hash, "
            "token_hint, token_enc, note, created_at, sort) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (body.name, body.platform, body.target_id, body.env,
             security.sha256_text(token), token[:10], security.encrypt_text(token),
             body.note, db.now(), sort),
        )
        security.audit(conn, user["username"], "新增设备", "device", cur.lastrowid,
                       {"name": body.name})
        row = _get_device(conn, cur.lastrowid)
        url = subscription_url(request, conn, token)
    data = _device_public(row)
    data["token"] = token
    data["subscription_url"] = url
    return data


@router.put("/devices/{did}")
def update_device(did: int, body: DeviceBody, user=CurrentUser):
    if body.env not in ENVS:
        raise HTTPException(400, "订阅环境仅支持 production / testing")
    if body.platform not in PLATFORMS:
        raise HTTPException(400, f"平台仅支持：{'、'.join(sorted(PLATFORMS))}")
    with db.tx() as conn:
        _get_device(conn, did)
        _get_target(conn, body.target_id)
        clash = db.one(
            conn, "SELECT id FROM devices WHERE name=? AND id!=?", (body.name, did)
        )
        if clash:
            raise HTTPException(409, "同名设备已存在")
        old_row = _get_device(conn, did)
        conn.execute(
            "UPDATE devices SET name=?, platform=?, target_id=?, env=?, note=? "
            "WHERE id=?",
            (body.name, body.platform, body.target_id, body.env, body.note, did),
        )
        if int(old_row["target_id"]) != int(body.target_id):
            target = _get_target(conn, body.target_id)
            _rekey_device_base_config(conn, did, target["engine"],
                                      target["platform"])
        security.audit(conn, user["username"], "更新设备", "device", did,
                       {"name": body.name})
        row = _get_device(conn, did)
    return _device_public(row)


# ---- 设备的批量操作与排序 ----

class BatchDeviceIds(BaseModel):
    ids: list[int] = Field(default_factory=list)


class BatchDevicePatch(BaseModel):
    """批量修改设备。字段为 null 表示不修改；空字符串表示清空。"""
    ids: list[int] = Field(default_factory=list)
    target_id: int | None = None
    env: str | None = None
    note: str | None = None


@router.post("/devices/reorder")
def reorder_devices(ids: list[int], user=CurrentUser):
    """设备排序：列表已分页时按提交的这些 id 重排，其余记录不动。"""
    with db.tx() as conn:
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "排序列表里有重复项")
        known = {r["id"] for r in db.all_(conn, "SELECT id FROM devices")}
        if any(i not in known for i in ids):
            raise HTTPException(400, "排序列表包含不存在的记录")
        if not db.reorder_subset(conn, "devices", ids):
            raise HTTPException(400, "排序未生效")
        security.audit(conn, user["username"], "调整设备顺序", "device",
                       ",".join(str(i) for i in ids))
    return {"ok": True}


@router.patch("/devices/batch")
def batch_update_devices(body: BatchDevicePatch, user=CurrentUser):
    """批量修改设备的共性配置（引擎平台、订阅环境、备注）。

    换引擎平台时平台的取值随目标一起改，避免与目标不一致。
    """
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(400, "请先选择要修改的设备")
    if body.target_id is None and body.env is None and body.note is None:
        raise HTTPException(400, "请至少选择一个要修改的字段")
    if body.env is not None and body.env not in ENVS:
        raise HTTPException(400, "订阅环境仅支持 production / testing")
    updated = 0
    skipped: list[dict] = []
    missing: list[int] = []
    with db.tx() as conn:
        target = None
        if body.target_id is not None:
            target = _get_target(conn, body.target_id)
        for did in ids:
            row = db.one(conn, "SELECT * FROM devices WHERE id=?", (did,))
            if not row:
                missing.append(did)
                continue
            fields: list[str] = []
            args: list = []
            notes: list[str] = []
            if body.target_id is not None:
                fields.append("target_id=?")
                args.append(body.target_id)
                # 平台跟随目标，避免出现"目标是 Stash-iOS、平台却是 macOS"
                fields.append("platform=?")
                args.append(target["platform"])
            if body.env is not None:
                fields.append("env=?")
                args.append(body.env)
            if body.note is not None:
                fields.append("note=?")
                args.append(body.note)
            if not fields:
                continue
            conn.execute(
                f"UPDATE devices SET {', '.join(fields)} WHERE id=?",
                (*args, did))
            updated += 1
            if notes:
                skipped.append({"id": did, "name": row["name"],
                                "reason": "；".join(notes)})
        security.audit(conn, user["username"], "批量修改设备", "device",
                       ",".join(str(i) for i in ids),
                       {"target_id": body.target_id, "env": body.env,
                        "note": body.note})
    return {"ok": True, "updated": updated, "missing": missing, "skipped": skipped}


@router.post("/devices/batch/delete")
def batch_delete_devices(body: BatchDeviceIds, user=CurrentUser):
    """批量删除设备：设备专属配置一并清理，令牌同时失效。"""
    deleted: list[int] = []
    missing: list[int] = []
    with db.tx() as conn:
        for did in dict.fromkeys(body.ids):
            row = db.one(conn, "SELECT * FROM devices WHERE id=?", (did,))
            if not row:
                missing.append(did)
                continue
            conn.execute("DELETE FROM devices WHERE id=?", (did,))
            # 设备独立配置一并清理，否则会成为孤儿行进入构建快照
            conn.execute("DELETE FROM base_configs WHERE device_id=?", (did,))
            deleted.append(did)
            security.audit(conn, user["username"], "批量删除设备（令牌同时失效）",
                           "device", did, {"name": row["name"]})
    return {"ok": True, "deleted": deleted, "missing": missing}


@router.post("/devices/{did}/rotate-token")
def rotate_token(did: int, request: Request, user=CurrentUser):
    """轮换令牌：旧令牌立即失效，新令牌仅本次返回。"""
    token = security.new_device_token()
    with db.tx() as conn:
        row = _get_device(conn, did)
        conn.execute(
            "UPDATE devices SET token_hash=?, token_hint=?, token_enc=? WHERE id=?",
            (security.sha256_text(token), token[:10],
             security.encrypt_text(token), did),
        )
        security.audit(conn, user["username"], "轮换设备令牌", "device", did,
                       {"name": row["name"]})
        url = subscription_url(request, conn, token)
    return {"id": did, "token": token, "subscription_url": url}


@router.post("/devices/{did}/reveal")
def reveal_device(did: int, request: Request, user=CurrentUser):
    """重新展示设备订阅地址。地址即凭据，拿到即可拉取完整配置。"""
    with db.connect() as conn:
        row = _get_device(conn, did)
        if not row["token_enc"]:
            raise HTTPException(409, "该设备缺少可展示的令牌，请轮换一次令牌")
        token = security.decrypt_text(row["token_enc"])
        url = subscription_url(request, conn, token)
        security.audit(conn, user["username"], "查看设备订阅地址", "device", did,
                       {"name": row["name"]})
    return {"id": did, "subscription_url": url}


@router.delete("/devices/{did}")
def delete_device(did: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_device(conn, did)
        conn.execute("DELETE FROM devices WHERE id=?", (did,))
        # 设备独立配置一并清理，否则会成为孤儿行进入构建快照
        conn.execute("DELETE FROM base_configs WHERE device_id=?", (did,))
        security.audit(conn, user["username"], "删除设备（令牌同时失效）", "device",
                       did, {"name": row["name"]})
    return {"ok": True}
