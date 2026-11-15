"""固定角色能力；未知角色和动作默认拒绝。"""
from uuid import uuid4

from fastapi import HTTPException

CAPABILITIES = frozenset({"view", "edit", "probe", "reveal", "publish_test",
    "publish_prod", "runtime_read", "runtime_write", "manage_users", "backup", "restore"})
ROLE_CAPABILITIES = {
    "admin": CAPABILITIES,
    "operator": frozenset({"view", "edit", "probe", "publish_test", "runtime_read"}),
    "viewer": frozenset({"view"}),
}


def effective_capabilities(user: dict) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(user.get("role"), frozenset())


def require_capability(user: dict, action: str) -> None:
    if action not in CAPABILITIES or action not in effective_capabilities(user):
        raise HTTPException(403, {"code": "forbidden", "message": "当前账号没有执行此操作的权限",
                                  "request_id": uuid4().hex})
