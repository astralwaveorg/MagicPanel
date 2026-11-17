"""自动任务：状态、运行记录与手动触发一轮。"""
import json

from fastapi import APIRouter, BackgroundTasks

from .. import db, security
from ..deps import CurrentUser, RequireCapabilities
from ..services import scheduler
from ..services.capabilities import require_capability

router = APIRouter(prefix="/api/v1/automation", tags=["automation"])


@router.get("/status")
def automation_status(user=CurrentUser):
    return scheduler.status()


@router.get("/runs")
def automation_runs(limit: int = 20, user=CurrentUser):
    limit = min(max(limit, 1), 50)
    with db.connect() as conn:
        rows = db.all_(
            conn, "SELECT * FROM automation_runs ORDER BY id DESC LIMIT ?", (limit,))
    return [
        {
            "id": row["id"],
            "at": row["at"],
            "trigger": row["trigger"],
            "summary": json.loads(row["summary"] or "{}"),
        }
        for row in rows
    ]


@router.post("/run")
def run_automation(background_tasks: BackgroundTasks, user=RequireCapabilities('probe')):
    """后台强制执行一轮（忽略到期时间）；结果通过 status / runs 查看。"""
    with db.connect() as conn:
        if (db.get_setting(conn, "auto_build_enabled", "1") == "1" and
                db.get_setting(conn, "auto_publish_enabled", "1") == "1"):
            env = db.get_setting(conn, "auto_publish_env", "production")
            require_capability(user, "publish_test" if env == "testing" else "publish_prod")
    with db.tx() as conn:
        security.audit(
            conn, user["username"], "手动触发自动任务", "automation", "",
            {"mode": "force", "note": "忽略到期时间，强制执行抓取、测速与构建检查"},
        )
    background_tasks.add_task(
        scheduler.run_once_safe, True, "manual", user["username"], actor_user_id=user["id"])
    # run_once 用非阻塞锁：定时轮正在跑时手动这轮会被静默跳过，
    # 结果只藏在 status.last_result——返回体必须把这一点说清（2026-11-18）
    return {"accepted": True, "mode": "force",
            "note": "若上一轮任务仍在运行，本轮会被跳过（结果见自动化状态页）"}
