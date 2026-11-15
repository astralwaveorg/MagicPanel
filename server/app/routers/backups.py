"""保留逻辑备份旧 URL；完整私密归档由独立接口提供。"""
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from .. import db, security
from ..deps import CurrentUser, RequireCapabilities
from ..services import backups

router = APIRouter(prefix="/api/v1/backup", tags=["backups"])


class RestoreBody(BaseModel):
    confirm: bool = False
    dry_run: bool = False
    data: dict


def _failure(exc: ValueError) -> HTTPException:
    codes = {"backup_missing_variants", "backup_missing_resource", "backup_invalid_reference",
             "backup_invalid", "backup_schema_unregistered", "backup_transaction_required"}
    code = str(exc) if str(exc) in codes else "backup_invalid"
    return HTTPException(400, {"code": code, "message": "逻辑备份校验失败，当前数据未替换",
                               "request_id": uuid4().hex})


def _audit(actor: str, action: str, detail="") -> None:
    with db.tx() as conn:
        security.audit(conn, actor, action, "backup", "", detail)


@router.get("/export")
def backup_export(response: Response, user=RequireCapabilities('backup')):
    """JSON 含私密密文，密钥另存；files 仅为清单，不携带文件。"""
    response.headers["Cache-Control"] = "no-store"
    _audit(user["username"], "开始导出备份")
    try:
        with db.connect() as conn:
            conn.execute("BEGIN")
            payload = backups.export_logical(conn)
    except ValueError as exc:
        raise _failure(exc) from None
    _audit(user["username"], "导出备份")
    return payload


@router.post("/restore")
def backup_restore(body: RestoreBody, response: Response, user=RequireCapabilities('restore')):
    response.headers["Cache-Control"] = "no-store"
    if not body.dry_run and not body.confirm:
        raise HTTPException(400, "恢复会覆盖当前全部数据，请设置 confirm=true 确认")
    _audit(user["username"], "开始校验备份" if body.dry_run else "开始恢复备份")
    try:
        with db.connect() as conn:
            conn.execute("BEGIN")
            report = backups.validate_logical(conn, body.data)
        if not body.dry_run:
            with db.tx(immediate=True) as conn:
                report = backups.restore_logical(conn, body.data)
    except ValueError as exc:
        raise _failure(exc) from None
    _audit(user["username"], "校验备份" if body.dry_run else "恢复备份", report)
    return {"ok": True, "dry_run": body.dry_run, **report,
            "staging": {"validated": True, "kind": "logical", "complete_archive": False}}
