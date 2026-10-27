"""概览、审计、设置、核心与备份。"""
import json
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import config, db, security
from ..deps import CurrentUser
from ..services import direct, releases, tester, webdav

router = APIRouter(prefix="/api/v1", tags=["misc"])

EDITABLE_SETTINGS = {
    "base_url", "session_ttl_hours", "profile_update_interval", "core_proxy",
    "scheduler_enabled", "auto_fetch_sources", "auto_fetch_rules",
    "auto_fetch_snippets", "auto_test_sources", "auto_build_enabled",
    "auto_build_interval_hours", "auto_publish_enabled", "auto_publish_env",
}
BOOL_SETTINGS = {
    "scheduler_enabled", "auto_fetch_sources", "auto_fetch_rules",
    "auto_fetch_snippets", "auto_test_sources", "auto_build_enabled",
    "auto_publish_enabled",
}


@router.get("/overview")
def overview(user=CurrentUser):
    with db.connect() as conn:
        release_state = releases.state_public(conn)
        # 可用率口径与「节点来源」页一致：以当前节点列表为准，
        # 测速结果里已消失的节点不计入（否则两边数字对不上）。
        sources = []
        for r in db.all_(conn, "SELECT * FROM sources ORDER BY id"):
            results = json.loads(r["test_results"] or "{}")
            names = [n.get("name") for n in json.loads(r["nodes_meta"] or "[]")]
            ok = sum(1 for n in names if results.get(n, -1) >= 0)
            failed = sum(1 for n in names if results.get(n, -1) < 0)
            sources.append({
                "id": r["id"], "name": r["name"], "enabled": bool(r["enabled"]),
                "last_status": r["last_status"], "last_error": r["last_error"],
                "last_fetched_at": r["last_fetched_at"], "node_count": r["node_count"],
                "tested_at": r["tested_at"],
                "filter_unavailable": bool(r["filter_unavailable"]),
                "tested_ok": ok, "tested_failed": failed,
            })
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
             "env": r["env"], "last_pull_at": r["last_pull_at"],
             "pull_count": r["pull_count"]}
            for r in db.all_(conn, "SELECT * FROM devices ORDER BY id")
        ]
        recent_audit = [
            db.row_to_dict(r) for r in db.all_(
                conn, "SELECT * FROM audit ORDER BY id DESC LIMIT 8"
            )
        ]
        counts = {
            "groups": db.one(conn, "SELECT COUNT(*) c FROM proxy_groups")["c"],
            "rules": db.one(conn, "SELECT COUNT(*) c FROM rules")["c"],
            "rules_enabled": db.one(conn, "SELECT COUNT(*) c FROM rules WHERE enabled=1")["c"],
        }
    return {
        "release_state": release_state,
        "sources": sources,
        "rule_providers": rule_providers,
        "devices": devices,
        "counts": counts,
        "recent_audit": recent_audit,
        "health": _health_snapshot(conn),
        "note": "下载成功仅代表文件取回，不代表配置加载、VPN 启动或规则生效。",
    }


def _health_snapshot(conn) -> dict:
    """运行状态自检：把"系统是否健康"一次性算清楚。

    概览页直接展示这些结论。只保留备份与测速核心两类真正需要处理的项——
    磁盘、设备拉取时效属于使用者自己掌握的运行细节，不进健康结论
    （2026-10-28 概览改版时移除）。
    """
    from datetime import datetime, timezone

    issues: list[str] = []
    data_dir = config.DATA_DIR

    # 最近一次备份
    last_backup = ""
    backup_dir = data_dir / "backup"
    snapshots = sorted(backup_dir.glob("magicpanel-*.db")) if backup_dir.is_dir() else []
    if snapshots:
        last_backup = snapshots[-1].stat().st_mtime
        age_hours = (datetime.now(timezone.utc).timestamp() - last_backup) / 3600
        if age_hours > 48:
            issues.append(f"最近一次备份已是 {int(age_hours)} 小时前")
    else:
        issues.append("还没有任何备份快照")

    core = tester.core_status()
    if not core.get("available"):
        issues.append("测速核心未安装，节点测速与 Mihomo 核心校验不可用")

    return {
        "ok": not issues,
        "issues": issues,
        "last_backup_at": (datetime.fromtimestamp(last_backup, timezone.utc)
                           .astimezone().isoformat(timespec="seconds")
                           if last_backup else ""),
        "core_available": bool(core.get("available")),
        "core_version": core.get("version", ""),
    }


@router.get("/direct-check")
def direct_check(refresh: bool = False, user=CurrentUser):
    """测速链路直连自检：出口地址、代理环境变量与结论。"""
    return direct.check(refresh=refresh)


@router.get("/audit")
def list_audit(limit: int = 100, offset: int = 0, keyword: str = "",
               user=CurrentUser):
    """审计日志分页查询。

    之前只返回前 N 条且没有翻页，记录多了就再也翻不到更早的内容；
    这里补上 offset 与关键字过滤，前端用常规分页组件即可。
    """
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)
    keyword = (keyword or "").strip()
    where = ""
    args: list = []
    if keyword:
        where = "WHERE action LIKE ? OR actor LIKE ? OR object_type LIKE ? OR detail LIKE ?"
        like = f"%{keyword}%"
        args = [like, like, like, like]
    with db.connect() as conn:
        total = db.one(conn, f"SELECT COUNT(*) AS c FROM audit {where}", args)["c"]
        rows = db.all_(
            conn,
            f"SELECT * FROM audit {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        )
    return {
        "items": [db.row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


class AuditDeleteBody(BaseModel):
    ids: list[int] = Field(default_factory=list)
    all: bool = False


@router.post("/audit/delete")
def delete_audit(body: AuditDeleteBody, user=CurrentUser):
    """批量删除审计记录；all=true 时清空全部。

    删除动作本身不会写审计日志（否则每次清理都会再产生一条记录）。
    """
    if not body.all and not body.ids:
        raise HTTPException(400, "请选择要删除的记录")
    with db.tx() as conn:
        if body.all:
            removed = conn.execute("DELETE FROM audit").rowcount
        else:
            ids = [int(i) for i in body.ids][:500]
            if not ids:
                raise HTTPException(400, "请选择要删除的记录")
            marks = ",".join("?" * len(ids))
            removed = conn.execute(
                f"DELETE FROM audit WHERE id IN ({marks})", ids).rowcount
    return {"ok": True, "removed": removed}


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
    if base_url:
        if not base_url.startswith(("https://", "http://")):
            raise HTTPException(400, "对外基础地址必须以 http(s):// 开头")
        # 只允许常规 URL 字符：引号、反斜杠等会把下发配置写坏，
        # 也可能被用来往产物里注入内容。
        if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", base_url):
            raise HTTPException(400, "对外基础地址含有不允许的字符")
        if "'" in base_url or "\\" in base_url or '"' in base_url:
            raise HTTPException(400, "对外基础地址含有不允许的字符")
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
        if key == "auto_publish_env" and value not in ("production", "testing"):
            raise HTTPException(400, "自动构建发布环境仅支持 production / testing")
    with db.tx() as conn:
        for key, value in body.values.items():
            db.set_setting(conn, key, value.strip())
        security.audit(conn, user["username"], "更新设置", "settings", "",
                       {k: security.mask_secret_value(k, v)
                        for k, v in body.values.items()})
    return {"ok": True}


# 备份表清单。顺序即"依赖正序"：父表在前，恢复时先插父表再插子表；
# 清空时按倒序删除，否则会触发外键约束失败（devices → targets、
# releases → builds 都有外键）。
BACKUP_TABLES = [
    "users", "sources", "rule_providers", "local_nodes", "proxy_groups", "rules",
    "targets", "snippets", "devices", "builds", "releases", "settings",
    "base_configs",
]
# 恢复范围比导出多一张表：sessions。
# users 被删除时 sessions.user_id 是 ON DELETE CASCADE，会话会一起消失，
# 恢复完把管理员踢下线；把会话一起还原才不会。
RESTORE_TABLES = BACKUP_TABLES + ["sessions"]
# 恢复时允许写入的列白名单：只接受表结构里真实存在的列，
# 避免备份文件里的任意列名拼进 SQL。
def _table_columns(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


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


class RestoreBody(BaseModel):
    confirm: bool = False
    data: dict


class WebDavSettingsBody(BaseModel):
    values: dict = Field(default_factory=dict)


@router.get("/backup/webdav")
def webdav_status(user=CurrentUser):
    """WebDAV 备份配置与状态（不回显口令）。"""
    with db.connect() as conn:
        return webdav.status(conn)


@router.put("/backup/webdav")
def webdav_save(body: WebDavSettingsBody, user=CurrentUser):
    """保存 WebDAV 配置。口令加密存储；password 为空表示不修改，null 表示清除。"""
    values = dict(body.values or {})
    if "interval_hours" in values:
        try:
            hours = int(values["interval_hours"])
        except (TypeError, ValueError):
            raise HTTPException(400, "备份间隔必须是整数小时")
        if not 1 <= hours <= 720:
            raise HTTPException(400, "备份间隔需在 1–720 小时之间")
        values["interval_hours"] = str(hours)
    if "keep" in values:
        try:
            keep = int(values["keep"])
        except (TypeError, ValueError):
            raise HTTPException(400, "保留份数必须是整数")
        if not 1 <= keep <= 100:
            raise HTTPException(400, "保留份数需在 1–100 之间")
        values["keep"] = str(keep)
    if values.get("url") and not str(values["url"]).startswith(("http://", "https://")):
        raise HTTPException(400, "WebDAV 地址必须以 http(s):// 开头")
    with db.tx() as conn:
        webdav.save_settings(conn, values)
        security.audit(conn, user["username"], "更新 WebDAV 备份配置", "backup", "",
                       {k: ("***" if k == "password" else v) for k, v in values.items()})
    with db.connect() as conn:
        return webdav.status(conn)


@router.post("/backup/webdav/test")
def webdav_test(user=CurrentUser):
    """测试 WebDAV 连接与鉴权。"""
    with db.connect() as conn:
        try:
            detail = webdav.test_connection(conn)
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc))
    return {"ok": True, "detail": detail}


@router.post("/backup/webdav/upload")
def webdav_upload(user=CurrentUser):
    """立即执行一次 WebDAV 备份。"""
    with db.connect() as conn:
        try:
            result = webdav.run_backup(conn, operator=user["username"], trigger="manual")
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc))
    return {"ok": True, **result}


@router.get("/backup/webdav/files")
def webdav_files(user=CurrentUser):
    """列出远端备份。"""
    with db.connect() as conn:
        try:
            return {"files": webdav.list_backups(conn)}
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc))


@router.post("/backup/webdav/restore")
def webdav_restore(body: RestoreBody, user=CurrentUser):
    """从远端快照恢复（会覆盖当前数据，必须显式确认）。"""
    if not body.confirm:
        raise HTTPException(400, "恢复会覆盖当前全部数据，请设置 confirm=true 确认")
    name = (body.data or {}).get("file", "")
    with db.connect() as conn:
        try:
            result = webdav.restore_from_remote(conn, name, user["username"])
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc))
    return {"ok": True, **result}


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
        # 先按依赖倒序清空（子表先删），再按依赖正序插入（父表先插）
        for table in reversed(RESTORE_TABLES):
            conn.execute(f"DELETE FROM {table}")
        for table in RESTORE_TABLES:
            rows = tables.get(table)
            if not rows:
                continue
            allowed = _table_columns(conn, table)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                columns = [c for c in row.keys() if c in allowed]
                if not columns:
                    continue
                marks = ",".join("?" for _ in columns)
                values = [row[c] for c in columns]
                conn.execute(
                    f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})",
                    tuple(values),
                )
        security.audit(conn, user["username"], "恢复备份", "backup", "")
    return {"ok": True}
