"""总览、审计、设置、核心与备份。"""
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import CurrentUser
from ..services import tester

router = APIRouter(prefix="/api/v1", tags=["misc"])

EDITABLE_SETTINGS = {
    "base_url", "session_ttl_hours", "profile_update_interval", "core_proxy",
    "scheduler_enabled", "auto_fetch_sources", "auto_fetch_rules",
    "auto_test_sources", "auto_build_enabled", "auto_build_interval_hours",
    "auto_publish_enabled", "auto_publish_channel",
}
BOOL_SETTINGS = {
    "scheduler_enabled", "auto_fetch_sources", "auto_fetch_rules",
    "auto_test_sources", "auto_build_enabled", "auto_publish_enabled",
}


@router.get("/overview")
def overview(user=CurrentUser):
    with db.connect() as conn:
        pointers = {
            r["channel"]: r["build_id"]
            for r in db.all_(conn, "SELECT * FROM pointers")
        }
        builds = {"stable": None, "candidate": None}
        for channel, bid in pointers.items():
            build = db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))
            if build:
                builds[channel] = {
                    "id": build["id"],
                    "created_at": build["created_at"],
                    "status": build["status"],
                    "policy_sha": build["policy_sha"],
                    "results": json.loads(build["results"] or "{}"),
                }
        sources = [
            {"id": r["id"], "name": r["name"], "enabled": bool(r["enabled"]),
             "last_status": r["last_status"], "last_error": r["last_error"],
             "last_fetched_at": r["last_fetched_at"], "node_count": r["node_count"],
             "tested_at": r["tested_at"],
             "filter_unavailable": bool(r["filter_unavailable"]),
             "tested_ok": sum(1 for v in json.loads(r["test_results"] or "{}").values() if v >= 0),
             "tested_failed": sum(1 for v in json.loads(r["test_results"] or "{}").values() if v < 0),
             }
            for r in db.all_(conn, "SELECT * FROM sources ORDER BY id")
        ]
        rule_providers = [
            {"id": r["id"], "name": r["name"], "enabled": bool(r["enabled"]),
             "last_status": r["last_status"], "last_error": r["last_error"],
             "last_fetched_at": r["last_fetched_at"], "rule_count": r["rule_count"]}
            for r in db.all_(conn, "SELECT * FROM rule_providers ORDER BY id")
        ]
        devices = [
            {"id": r["id"], "name": r["name"],
             "display_name": r["note"] or r["name"],
             "platform": r["platform"],
             "channel": r["channel"], "last_pull_at": r["last_pull_at"],
             "pull_count": r["pull_count"]}
            for r in db.all_(conn, "SELECT * FROM devices ORDER BY id")
        ]
        recent_audit = [
            db.row_to_dict(r) for r in db.all_(
                conn, "SELECT * FROM audit ORDER BY id DESC LIMIT 8"
            )
        ]
    return {
        "channels": builds,
        "sources": sources,
        "rule_providers": rule_providers,
        "devices": devices,
        "recent_audit": recent_audit,
        "note": "下载成功仅代表客户端取回了文件，不代表已加载或已生效。",
    }


@router.get("/audit")
def list_audit(limit: int = 100, user=CurrentUser):
    limit = min(max(limit, 1), 500)
    with db.connect() as conn:
        rows = db.all_(
            conn, "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        )
    return [db.row_to_dict(r) for r in rows]


@router.get("/settings")
def get_settings(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT key, value FROM settings")
    return {r["key"]: r["value"] for r in rows}


class SettingsBody(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


@router.put("/settings")
def put_settings(body: SettingsBody, user=CurrentUser):
    for key in body.values:
        if key not in EDITABLE_SETTINGS:
            raise HTTPException(400, f"不支持的设置项：{key}")
    base_url = body.values.get("base_url", "")
    if base_url and not base_url.startswith(("https://", "http://")):
        raise HTTPException(400, "对外基础地址必须以 http(s):// 开头")
    for key, value in body.values.items():
        if key in BOOL_SETTINGS and value not in ("0", "1"):
            raise HTTPException(400, f"{key} 只能是 0 或 1")
        if key == "auto_build_interval_hours":
            try:
                hours = int(value)
            except ValueError:
                raise HTTPException(400, "自动构建间隔必须是整数小时")
            if not 1 <= hours <= 168:
                raise HTTPException(400, "自动构建间隔需在 1–168 小时之间")
        if key == "auto_publish_channel" and value not in ("stable", "candidate"):
            raise HTTPException(400, "自动发布通道仅支持 stable / candidate")
    with db.tx() as conn:
        for key, value in body.values.items():
            db.set_setting(conn, key, value.strip())
        security.audit(conn, user["username"], "更新设置", "settings", "",
                       {k: ("***" if "token" in k else v)
                        for k, v in body.values.items()})
    return {"ok": True}


BACKUP_TABLES = [
    "users", "sources", "rule_providers", "local_nodes", "proxy_groups", "rules",
    "targets", "snippets", "devices", "builds", "releases", "pointers", "settings",
    "base_configs",
]


@router.get("/core/status")
def core_status(user=CurrentUser):
    return tester.core_status()


@router.post("/core/install")
def core_install(user=CurrentUser):
    """下载固定版本的 Mihomo 核心到 data/bin，用于节点连通性测试。"""
    with db.connect() as conn:
        proxy = db.get_setting(conn, "core_proxy", "")
    try:
        result = tester.install_core(proxy=proxy)
    except tester.TestError as exc:
        raise HTTPException(400, str(exc))
    with db.tx() as conn:
        security.audit(conn, user["username"], "安装测速核心", "core", "",
                       {"version": result["version"], "sha256": result["sha256"]})
    return result


@router.post("/core/upload")
async def core_upload(request: Request, user=CurrentUser):
    """本地上传安装 / 更新核心（.gz / .zip / 裸二进制，原始字节直传）。

    适用于服务端无法直连 GitHub 的环境：在本机下载与服务端平台一致的
    发布包后上传，服务端自动解压并校验后替换现有核心。
    """
    data = await request.body()
    try:
        result = tester.install_core_from_upload(data)
    except tester.TestError as exc:
        raise HTTPException(400, str(exc))
    with db.tx() as conn:
        security.audit(conn, user["username"], "上传安装测速核心", "core", "",
                       {"version": result["version"], "sha256": result["sha256"]})
    return result


@router.get("/backup/export")
def backup_export(user=CurrentUser):
    """导出全部策略与运行数据。

    文件包含加密后的订阅地址与设备令牌摘要；与 data/secret.key
    分开保管，泄露等同于泄露全部凭据的密文与主密钥保管边界。
    """
    with db.connect() as conn:
        tables = {
            t: [db.row_to_dict(r) for r in db.all_(conn, f"SELECT * FROM {t}")]
            for t in BACKUP_TABLES
        }
        security.audit(conn, user["username"], "导出备份", "backup", "")
    return {"version": 1, "exported_at": db.now(), "tables": tables}


class RestoreBody(BaseModel):
    confirm: bool = False
    data: dict


@router.post("/backup/restore")
def backup_restore(body: RestoreBody, user=CurrentUser):
    if not body.confirm:
        raise HTTPException(400, "恢复会覆盖当前全部数据，请设置 confirm=true 确认")
    tables = (body.data or {}).get("tables")
    if not isinstance(tables, dict):
        raise HTTPException(400, "备份文件格式不正确")
    unknown = set(tables) - set(BACKUP_TABLES)
    if unknown:
        raise HTTPException(400, f"备份包含未知数据表：{'、'.join(sorted(unknown))}")
    with db.tx() as conn:
        for table in BACKUP_TABLES:
            conn.execute(f"DELETE FROM {table}")
        for table, rows in tables.items():
            for row in rows:
                columns = ",".join(row.keys())
                marks = ",".join("?" for _ in row)
                conn.execute(
                    f"INSERT INTO {table}({columns}) VALUES({marks})",
                    tuple(row.values()),
                )
        security.audit(conn, user["username"], "恢复备份", "backup", "")
    return {"ok": True}
