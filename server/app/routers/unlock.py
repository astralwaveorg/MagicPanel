"""网络解锁检测接口：面板出口 / 指定节点两种模式 + 节点批量检测。"""
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..deps import CurrentUser, RequireCapabilities
from ..services import unlock_check

router = APIRouter(prefix="/api/v1/unlock", tags=["unlock"])


class RunBody(BaseModel):
    exit: str = "panel"
    ids: list[str] = Field(default_factory=list)


@router.get("/catalog")
def catalog(user=CurrentUser):
    return {"checks": [
        {"id": c["id"], "name": c["name"], "icon": c["icon"], "category": c["category"]}
        for c in unlock_check.CHECKS
    ], "categories": unlock_check.CATEGORY_NAMES}


@router.get("/last")
def last(exit: str = "panel", user=CurrentUser):
    return unlock_check.last_results(exit)


@router.post("/run")
def run(body: RunBody, user=RequireCapabilities("probe")):
    try:
        return unlock_check.run_checks(body.exit, body.ids, operator=user["username"])
    except LookupError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


class BatchBody(BaseModel):
    qty: int = Field(default=3, ge=1, le=50)
    ids: list[str] = Field(default_factory=list)


@router.post("/batch-detect")
def batch_detect(body: BatchBody, user=RequireCapabilities("probe")):
    """批量检测一批节点的 AI 解锁能力（后台线程）。

    结果写 unlock 缓存（exit_id=原始节点名），重命名引擎据此给
    「AI 全解锁」的节点加 🔓 徽章。每节点要起一次测速核心，
    一批 3 个约 40-60 秒——放后台线程，接口立即返回进度查询方式。
    """
    state = unlock_check.batch_state()
    if state.get("running"):
        raise HTTPException(409, "已有批量检测在进行中，请等待完成或查询进度")

    def worker():
        try:
            unlock_check.run_batch(qty=body.qty, ids=body.ids or None,
                                   operator=user["username"])
        except Exception as exc:
            unlock_check.logger.exception("批量解锁检测异常")

    threading.Thread(target=worker, daemon=True, name="unlock-batch").start()
    return {"ok": True, "started": True, "qty": body.qty}


@router.get("/batch-status")
def batch_status(user=CurrentUser):
    return unlock_check.batch_state()


@router.get("/capability-coverage")
def capability_coverage(user=CurrentUser):
    """解锁能力缓存覆盖率：构建页据此提示「产物里哪些节点还没有能力标记」。"""
    try:
        return unlock_check.coverage()
    except Exception as exc:
        raise HTTPException(500, f"统计解锁能力覆盖率失败：{exc}")


@router.get("/node-capabilities")
def node_capabilities(user=CurrentUser):
    """各节点的能力徽章（构建产物里节点名的徽章来源）。"""
    try:
        nodes = unlock_check.detectable_nodes()
    except Exception as exc:
        raise HTTPException(500, f"读取节点列表失败：{exc}")
    out = []
    for name in nodes:
        badges = unlock_check.capability_badges(name)
        out.append({"name": name, "badges": badges,
                    "tested": bool(badges) or bool(unlock_check._states_of(name))})
    return {"items": out, "total": len(out),
            "with_badges": sum(1 for i in out if i["badges"])}
