"""发布目标（客户端模板）与设备管理。

设备令牌只在创建／轮换时返回一次；服务器只保存摘要。
泄露后的处置：轮换或撤销令牌，已下发的节点凭据需联系机场重置。
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import yaml

from .. import db, security
from ..deps import CurrentUser
from ..services import base_config as base_config_service

router = APIRouter(prefix="/api/v1", tags=["targets-devices"])

ENGINES = {"stash", "mihomo"}
PLATFORMS = {"ios", "macos", "tvos", "windows", "android"}
CHANNELS = {"stable", "candidate"}


class TargetBody(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    engine: str
    platform: str
    description: str = Field(default="", max_length=256)
    extra_yaml: str = Field(default="", max_length=200_000)
    update_interval: int = Field(default=12, ge=1, le=168)


class DeviceBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    platform: str
    target_id: int
    channel: str = "stable"
    note: str = Field(default="", max_length=256)


def _check_target(body: TargetBody) -> None:
    if body.engine not in ENGINES:
        raise HTTPException(400, "引擎仅支持 stash / mihomo")
    if body.platform not in PLATFORMS:
        raise HTTPException(400, f"平台仅支持：{'、'.join(sorted(PLATFORMS))}")
    if body.extra_yaml.strip():
        try:
            overlay = yaml.safe_load(body.extra_yaml)
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"目标扩展 YAML 解析失败：{exc}")
        if overlay is not None and not isinstance(overlay, dict):
            raise HTTPException(400, "目标扩展必须是 YAML 映射（键值结构）")
        for key, reason in base_config_service.PROTECTED_KEYS.items():
            if overlay and key in overlay:
                raise HTTPException(400, f"目标扩展不能包含“{key}”：{reason}")


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
        "channel": row["channel"],
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
        raise HTTPException(404, "发布目标不存在")
    return row


def _get_device(conn, did: int):
    row = db.one(conn, "SELECT * FROM devices WHERE id=?", (did,))
    if not row:
        raise HTTPException(404, "设备不存在")
    return row


@router.get("/targets")
def list_targets(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM targets ORDER BY sort, id")
    return [_target_public(r) for r in rows]


@router.post("/targets", status_code=201)
def create_target(body: TargetBody, user=CurrentUser):
    _check_target(body)
    with db.tx() as conn:
        if db.one(conn, "SELECT id FROM targets WHERE name=?", (body.name,)):
            raise HTTPException(409, "同名发布目标已存在")
        now = db.now()
        sort = db.one(conn, "SELECT COALESCE(MAX(sort), 0) + 1 AS n FROM targets")["n"]
        cur = conn.execute(
            "INSERT INTO targets(name, engine, platform, description, extra_yaml, "
            "update_interval, sort, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (body.name, body.engine, body.platform, body.description,
             body.extra_yaml, body.update_interval, sort, now, now),
        )
        security.audit(conn, user["username"], "新增发布目标", "target", cur.lastrowid,
                       {"name": body.name})
        row = _get_target(conn, cur.lastrowid)
    return _target_public(row)


@router.post("/targets/reorder")
def reorder_targets(ids: list[int], user=CurrentUser):
    with db.tx() as conn:
        existing = {r["id"] for r in db.all_(conn, "SELECT id FROM targets")}
        if set(ids) != existing:
            raise HTTPException(400, "排序列表与现有发布目标不一致")
        for index, tid in enumerate(ids, start=1):
            conn.execute("UPDATE targets SET sort=? WHERE id=?", (index, tid))
        security.audit(conn, user["username"], "调整发布目标顺序", "target", "")
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
            raise HTTPException(409, "同名发布目标已存在")
        conn.execute(
            "UPDATE targets SET name=?, engine=?, platform=?, description=?, "
            "extra_yaml=?, update_interval=?, updated_at=? WHERE id=?",
            (body.name, body.engine, body.platform, body.description,
             body.extra_yaml, body.update_interval, db.now(), tid),
        )
        security.audit(conn, user["username"], "更新发布目标", "target", tid,
                       {"name": body.name})
        row = _get_target(conn, tid)
    return _target_public(row)


@router.delete("/targets/{tid}")
def delete_target(tid: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_target(conn, tid)
        used = db.one(
            conn, "SELECT COUNT(*) AS c FROM devices WHERE target_id=?", (tid,)
        )["c"]
        if used:
            raise HTTPException(400, f"仍有 {used} 台设备使用该发布目标")
        conn.execute("DELETE FROM targets WHERE id=?", (tid,))
        security.audit(conn, user["username"], "删除发布目标", "target", tid,
                       {"name": row["name"]})
    return {"ok": True}


# ---- 设备 ----

def subscription_url(request: Request, conn, token: str) -> str:
    base = db.get_setting(conn, "base_url", "").rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/feed/{token}/config.yaml"


@router.get("/devices")
def list_devices(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM devices ORDER BY id")
    return [_device_public(r) for r in rows]


@router.post("/devices", status_code=201)
def create_device(body: DeviceBody, request: Request, user=CurrentUser):
    if body.channel not in CHANNELS:
        raise HTTPException(400, "通道仅支持 stable / candidate")
    if body.platform not in PLATFORMS:
        raise HTTPException(400, f"平台仅支持：{'、'.join(sorted(PLATFORMS))}")
    token = security.new_device_token()
    with db.tx() as conn:
        _get_target(conn, body.target_id)
        if db.one(conn, "SELECT id FROM devices WHERE name=?", (body.name,)):
            raise HTTPException(409, "同名设备已存在")
        cur = conn.execute(
            "INSERT INTO devices(name, platform, target_id, channel, token_hash, "
            "token_hint, token_enc, note, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (body.name, body.platform, body.target_id, body.channel,
             security.sha256_text(token), token[:10], security.encrypt_text(token),
             body.note, db.now()),
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
    if body.channel not in CHANNELS:
        raise HTTPException(400, "通道仅支持 stable / candidate")
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
        conn.execute(
            "UPDATE devices SET name=?, platform=?, target_id=?, channel=?, note=? "
            "WHERE id=?",
            (body.name, body.platform, body.target_id, body.channel, body.note, did),
        )
        security.audit(conn, user["username"], "更新设备", "device", did,
                       {"name": body.name})
        row = _get_device(conn, did)
    return _device_public(row)


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
        security.audit(conn, user["username"], "删除设备（令牌同时失效）", "device",
                       did, {"name": row["name"]})
    return {"ok": True}
