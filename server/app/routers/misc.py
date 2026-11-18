"""概览、审计、设置、核心与备份。"""
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import config, db, security
from ..deps import CurrentUser, RequireCapabilities
from ..services import direct, releases, tester, webdav
from ..services.capabilities import require_capability
from ..services.access_dto import audit_public, error_summary
from . import targets_devices

router = APIRouter(prefix="/api/v1", tags=["misc"])

EDITABLE_SETTINGS = {
    "base_url", "session_ttl_hours", "profile_update_interval", "core_proxy",
    "scheduler_enabled", "auto_fetch_sources", "auto_fetch_rules",
    "auto_fetch_snippets", "auto_test_sources", "auto_build_enabled",
    "auto_build_interval_hours", "auto_publish_enabled", "auto_publish_env",
    "node_name_normalize", "node_name_unlock_badge", "unlock_batch_auto",
    "unlock_batch_size",
}
BOOL_SETTINGS = {
    "scheduler_enabled", "auto_fetch_sources", "auto_fetch_rules",
    "auto_fetch_snippets", "auto_test_sources", "auto_build_enabled",
    "auto_publish_enabled", "node_name_normalize", "node_name_unlock_badge",
    "unlock_batch_auto",
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
                "last_status": r["last_status"], "last_error": error_summary(r["last_error"]),
                "has_error": bool(r["last_error"]),
                "last_fetched_at": r["last_fetched_at"], "node_count": r["node_count"],
                "tested_at": r["tested_at"],
                "filter_unavailable": bool(r["filter_unavailable"]),
                "tested_ok": ok, "tested_failed": failed,
            })
        rule_providers = [
            {"id": r["id"], "name": r["name"], "enabled": bool(r["enabled"]),
             "last_status": r["last_status"], "last_error": error_summary(r["last_error"]),
             "has_error": bool(r["last_error"]),
             "last_fetched_at": r["last_fetched_at"], "rule_count": r["rule_count"]}
            for r in db.all_(conn, "SELECT * FROM rule_providers ORDER BY id")
        ]
        # profile_update_interval 全局一份：读一次传给每台设备的判断（N+1 收口）
        profile_interval = db.get_setting(conn, "profile_update_interval", "12")
        devices = [
            {"id": r["id"], "name": r["name"],
             "display_name": r["note"] or r["name"],
             "platform": r["platform"],
             "env": r["env"], "last_pull_at": r["last_pull_at"],
             "last_config_at": r["last_config_at"],
             "config_stale": targets_devices.config_stale(conn, r, profile_interval),
             "pull_count": r["pull_count"]}
            for r in db.all_(conn, "SELECT * FROM devices ORDER BY id")
        ]
        recent_audit = [
            audit_public(r) for r in db.all_(
                conn, "SELECT * FROM audit ORDER BY id DESC LIMIT 8"
            )
        ]
        counts = {
            "groups": db.one(conn, "SELECT COUNT(*) c FROM proxy_groups")["c"],
            "rules": db.one(conn, "SELECT COUNT(*) c FROM rules")["c"],
            "rules_enabled": db.one(conn, "SELECT COUNT(*) c FROM rules WHERE enabled=1")["c"],
            # 配置本体没更新的设备数：这类故障在界面上必须看得见
            "devices_stale": sum(1 for d in devices if d["config_stale"]),
        }
        # 健康结论要在连接存活时算：待生效变更等检查需要查库
        health = _health_snapshot(conn)
    return {
        "release_state": release_state,
        "sources": sources,
        "rule_providers": rule_providers,
        "devices": devices,
        "counts": counts,
        "recent_audit": recent_audit,
        "health": health,
        "note": "下载成功仅代表文件取回，不代表配置加载、VPN 启动或规则生效。",
    }


def _health_snapshot(conn) -> dict:
    """运行状态自检：把"系统是否健康"一次性算清楚。

    概览页直接展示这些结论。备份与测速核心之外，2026-11-18 加入三类
    "静默失效"检查——这类问题原来只落在 automation_runs / settings 里，
    不主动进概览，管理者不点子页面就永远看不见：
    待生效的基础配置改动、自动任务最近失败、自动发布退避中。
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

    # 待生效变更：基础配置层的改动晚于当前生产构建的创建时间。
    # 保存成功 ≠ 产物生效，这个差值必须在概览看得见。
    prod = db.one(conn, "SELECT created_at FROM builds WHERE status='PRODUCTION' LIMIT 1")
    if prod:
        # 空差异（"{}"）不是真实改动：保存相同内容也会刷新 updated_at，不能算待生效
        pending = db.one(
            conn,
            "SELECT COUNT(*) c FROM base_configs "
            "WHERE updated_at > ? AND REPLACE(REPLACE(TRIM(content), ' ', ''), CHAR(10), '') != '{}'",
            (prod["created_at"],))["c"]
        if pending:
            issues.append(
                f"有 {pending} 层基础配置改动尚未进入当前生产版本"
                "——去「基础配置」重新保存并构建，或在「构建发布」创建新构建")

    # 自动任务最近一次失败（24 小时内有 build_error 才报，避免陈旧噪声）
    row = db.one(conn, "SELECT summary, at FROM automation_runs ORDER BY id DESC LIMIT 1")
    if row:
        try:
            summary = json.loads(row["summary"] or "{}")
        except ValueError:
            summary = {}
        err = str(summary.get("build_error") or "")
        at = _parse_ts(row["at"])
        if err and at and (datetime.now(timezone.utc).astimezone() - at).total_seconds() < 86400:
            issues.append(f"自动任务最近失败（{row['at'][:16].replace('T', ' ')}）：{err[:120]}")

    # 自动发布退避中：发布连续失败后的指数退避窗口
    backoff = db.get_setting(conn, "auto_build_backoff_until", "")
    if backoff:
        try:
            bt = datetime.fromisoformat(backoff)
            if bt.tzinfo is None:
                bt = bt.replace(tzinfo=timezone.utc)
            if bt > datetime.now(timezone.utc):
                issues.append("自动发布失败退避重试中"
                              f"（约 {backoff[11:16].replace('T', ' ')} 后自动重试）")
        except ValueError:
            pass

    # 依赖仓库同步失败（仅在功能开启时报，避免关闭后残留错误误报）
    if db.get_setting(conn, "deps_enabled", "0") == "1":
        deps_err = db.get_setting(conn, "deps_last_error", "")
        if deps_err:
            issues.append(f"依赖仓库同步失败：{deps_err[:120]}")

    return {
        "ok": not issues,
        "issues": issues,
        "last_backup_at": (datetime.fromtimestamp(last_backup, timezone.utc)
                           .astimezone().isoformat(timespec="seconds")
                           if last_backup else ""),
        "core_available": bool(core.get("available")),
        "core_version": core.get("version", ""),
    }


def _parse_ts(value: str):
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


@router.get("/direct-check")
def direct_check(refresh: bool = False, user=CurrentUser):
    """读取最近出口信息；GET 不触发网络检测。"""
    if refresh:
        raise HTTPException(409, {"code": "action_required",
            "message": "主动检测须先预演检测任务并确认预算",
            "action": "probe_task_preview", "request_id": uuid4().hex})
    return direct.last_observation()


@router.post("/direct-observe")
def direct_observe(user=RequireCapabilities("probe")):
    """主动发起路径观测：境外/境内回显差分，判定透明代理是否接管。"""
    try:
        return direct.observe()
    except Exception as exc:
        raise HTTPException(502, f"路径观测失败：{exc}")


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
        where = "WHERE action LIKE ? OR actor LIKE ? OR object_type LIKE ? OR object_id LIKE ?"
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
        "items": [audit_public(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/audit/{audit_id}/reveal")
def reveal_audit(audit_id: int, user=RequireCapabilities("reveal")):
    with db.tx() as conn:
        row = db.one(conn, "SELECT * FROM audit WHERE id=?", (audit_id,))
        if not row:
            raise HTTPException(404, "审计记录不存在")
        security.audit(conn, user["username"], "查看历史审计原文", "audit", audit_id,
                       {"fields": ["detail"]})
    return {"id": audit_id, "detail": row["detail"]}


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
    if not body.all and len(body.ids) > 500:
        # 原来静默截断到 500 条，多传的 id 无声丢弃：显式拒绝提示分批
        raise HTTPException(400, "单次最多删除 500 条，请分批提交")
    with db.tx() as conn:
        if body.all:
            removed = conn.execute("DELETE FROM audit").rowcount
        else:
            ids = [int(i) for i in body.ids]
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
    result = {r["key"]: r["value"] for r in rows
              if r["key"] in EDITABLE_SETTINGS - {"core_proxy"}}
    base = result.get("base_url", "")
    parsed = urlsplit(base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        result["base_url"] = security.mask_url(base)
    return result


@router.post("/settings/reveal")
def reveal_settings(user=RequireCapabilities("reveal")):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT key, value FROM settings")
    return {r["key"]: r["value"] for r in rows if r["key"] in EDITABLE_SETTINGS}


class SettingsBody(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


@router.put("/settings")
def put_settings(body: SettingsBody, user=CurrentUser):
    if body.values.keys() & {"core_proxy", "base_url"}:
        require_capability(user, "reveal")
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
        parsed = urlsplit(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HTTPException(400, "对外基础地址不能包含凭据、查询参数或片段")
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
        # 数值键必须有类型与范围校验：这两个键被 create_session / config_stale
        # 直接 int() 读取，写进非数字会让所有登录接口 500（2026-11-18 修复）
        if key == "session_ttl_hours":
            try:
                hours = int(value)
            except ValueError:
                raise HTTPException(400, "登录会话有效期必须是整数小时")
            if not 1 <= hours <= 8760:
                raise HTTPException(400, "登录会话有效期需在 1–8760 小时之间")
        if key == "unlock_batch_size":
            try:
                size = int(value)
            except ValueError:
                raise HTTPException(400, "批量检测每批节点数必须是整数")
            if not 1 <= size <= 50:
                raise HTTPException(400, "批量检测每批节点数需在 1–50 之间")
        if key == "profile_update_interval":
            try:
                hours = int(value)
            except ValueError:
                raise HTTPException(400, "订阅更新间隔必须是整数小时")
            if not 0 <= hours <= 168:
                raise HTTPException(400, "订阅更新间隔需在 0–168 小时之间")
        if key == "auto_publish_env" and value not in ("production", "testing"):
            raise HTTPException(400, "自动构建发布环境仅支持 production / testing")
    with db.tx(immediate=True) as conn:
        if body.values.keys() & {"scheduler_enabled", "auto_build_enabled", "auto_publish_enabled", "auto_publish_env"}:
            effective = {key: body.values.get(key, db.get_setting(conn, key, default)) for key, default in (
                ("auto_build_enabled", "1"), ("auto_publish_enabled", "1"),
                ("auto_publish_env", "production"))}
            if (effective["auto_build_enabled"] == "1" and effective["auto_publish_enabled"] == "1"
                    and effective["auto_publish_env"] == "production"):
                require_capability(user, "publish_prod")
        for key, value in body.values.items():
            db.set_setting(conn, key, value.strip())
        security.audit(conn, user["username"], "更新设置", "settings", "",
                       {k: security.mask_secret_value(k, v)
                        for k, v in body.values.items()})
    return {"ok": True}


@router.get("/core/status")
def core_status(user=CurrentUser):
    return tester.core_status()


@router.post("/core/install")
def core_install(user=RequireCapabilities('edit', 'reveal')):
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
async def core_upload(request: Request, user=RequireCapabilities('edit', 'reveal')):
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
        return _webdav_public(conn)


def _webdav_public(conn):
    result = webdav.status(conn)
    result["url"] = security.mask_url(result.get("url") or "")
    return result


@router.post("/backup/webdav/reveal")
def reveal_webdav_settings(user=RequireCapabilities("reveal")):
    with db.connect() as conn:
        return webdav.status(conn)


@router.put("/backup/webdav")
def webdav_save(body: WebDavSettingsBody, user=CurrentUser):
    """保存 WebDAV 配置。口令加密存储；password 为空表示不修改，null 表示清除。"""
    values = dict(body.values or {})
    if values.keys() & {"url", "username", "password", "directory"}:
        require_capability(user, "reveal")
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
                       {"fields": sorted(values)})
    with db.connect() as conn:
        return _webdav_public(conn)


@router.post("/backup/webdav/test")
def webdav_test(user=RequireCapabilities('backup')):
    """测试 WebDAV 连接与鉴权。"""
    with db.connect() as conn:
        try:
            detail = webdav.test_connection(conn)
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc))
    return {"ok": True, "detail": detail}


@router.post("/backup/webdav/upload")
def webdav_upload(user=RequireCapabilities('backup')):
    """立即执行一次 WebDAV 备份。"""
    with db.connect() as conn:
        try:
            result = webdav.run_backup(conn, operator=user["username"], trigger="manual")
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc))
    return {"ok": True, **result}


@router.get("/backup/webdav/files")
def webdav_files(user=RequireCapabilities('backup')):
    """列出远端备份。"""
    with db.connect() as conn:
        try:
            return {"files": webdav.list_backups(conn)}
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc))


@router.post("/backup/webdav/restore")
def webdav_restore(body: RestoreBody, response: Response, user=RequireCapabilities('restore')):
    """从远端归档创建隔离恢复目录，运行库切换由维护流程执行。"""
    response.headers["Cache-Control"] = "no-store"
    if not body.confirm:
        raise HTTPException(400, "请设置 confirm=true 确认创建隔离恢复目录")
    name = (body.data or {}).get("file", "")
    data_root = config.DATA_DIR.resolve()
    staging_root = data_root / "restore-staging"
    if (staging_root.is_symlink() or
            (hasattr(staging_root, "is_junction") and staging_root.is_junction()) or
            not staging_root.is_relative_to(data_root)):
        raise HTTPException(400, "隔离恢复目录不可用")
    destination = staging_root / uuid4().hex
    if destination.exists():
        raise HTTPException(409, "隔离恢复目录已存在，请重试")
    with db.connect() as conn:
        try:
            result = webdav.restore_from_remote(
                conn, name, user["username"], destination=destination, key_path=config.SECRET_KEY_PATH)
        except webdav.WebDavError as exc:
            raise HTTPException(400, str(exc), headers={"Cache-Control": "no-store"})
    return {"ok": True, "status": result["status"], "verification_status": result["verification_status"],
            "restored": False, "staging_name": destination.name,
            "requires_maintenance_restart": True, "key_restored": False}
