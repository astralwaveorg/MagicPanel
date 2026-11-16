"""网络解锁检测接口：面板出口 / 指定节点两种模式。"""
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
