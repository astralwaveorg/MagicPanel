"""自动任务：状态、运行记录与手动触发一轮。"""
import json

from fastapi import APIRouter, BackgroundTasks

from .. import db, security
from ..deps import CurrentUser
from ..services import scheduler

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
def run_automation(background_tasks: BackgroundTasks, user=CurrentUser):
    """后台强制执行一轮（忽略到期时间）；结果通过 status / runs 查看。"""
    with db.tx() as conn:
        security.audit(
            conn, user["username"], "手动触发自动任务", "automation", "",
            {"mode": "force", "note": "忽略到期时间，强制执行抓取、测速与构建检查"},
        )
    background_tasks.add_task(
        scheduler.run_once_safe, True, "manual", user["username"])
    return {"accepted": True, "mode": "force"}
