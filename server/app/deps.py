"""请求级依赖：会话认证与 CSRF 校验。

管理接口使用 HttpOnly Cookie 会话，写操作要求 X-CSRF-Token；
使用 Bearer 令牌（非 Cookie）的请求不经过浏览器，免于 CSRF 校验。
feed 接口使用独立的高熵 URL 令牌，不经过此依赖。
"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security.utils import get_authorization_scheme_param

from . import config, db, security
from .services.capabilities import require_capability

SESSION_COOKIE = "mp_session"


def _hash(token: str) -> str:
    return security.sha256_text(token)


def create_session(conn, user_id: int, ip: str, ua: str) -> tuple[str, str, int]:
    token = security.new_session_token()
    csrf = security.random_csrf()
    ttl = int(db.get_setting(conn, "session_ttl_hours", str(config.SESSION_TTL_HOURS)))
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl)
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, expires_at, ip, ua) "
        "VALUES(?,?,?,?,?,?,?)",
        (_hash(token), user_id, csrf, db.now(),
         expires.isoformat(timespec="seconds"), ip, ua),
    )
    return token, csrf, ttl


def destroy_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))


def _load_session(conn, token: str):
    row = db.one(
        conn,
        "SELECT s.token_hash, s.csrf_token, s.expires_at, u.id AS uid, u.username, "
        "u.display_name, u.role, u.portal_pin_hash, u.avatar_mime FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
        (_hash(token),),
    )
    if not row:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if expires < datetime.now(timezone.utc):
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))
        conn.commit()
        return None
    return row


def _authenticated_user(request: Request) -> dict:
    cookie_token = request.cookies.get(SESSION_COOKIE, "")
    auth = request.headers.get("Authorization", "")
    scheme, param = get_authorization_scheme_param(auth)
    bearer = param if scheme.lower() == "bearer" else ""

    token = cookie_token or bearer
    if not token:
        raise HTTPException(401, "未登录或会话已过期")
    with db.connect() as conn:
        row = _load_session(conn, token)
        if not row:
            raise HTTPException(401, "未登录或会话已过期")
        # Cookie 会话的写操作必须携带匹配的 CSRF 令牌
        if cookie_token and request.method not in ("GET", "HEAD", "OPTIONS"):
            header = request.headers.get("X-CSRF-Token", "")
            if not header or header != row["csrf_token"]:
                raise HTTPException(403, "CSRF 校验失败，请刷新页面后重试")
        return {
            "id": row["uid"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "csrf_token": row["csrf_token"],
            "portal_pin_hash": row["portal_pin_hash"],
            "avatar_mime": row["avatar_mime"],
            "token": token,
        }


def require_user(request: Request, user=Depends(_authenticated_user)) -> dict:
    # 本人账户自服务只要求有效身份；领域写操作默认 edit。
    self_service = request.url.path in {
        "/api/v1/auth/logout", "/api/v1/auth/password", "/api/v1/auth/avatar"}
    action = "view" if self_service or request.method in ("GET", "HEAD", "OPTIONS") else "edit"
    require_capability(user, action)
    return user


def RequireCapabilities(*actions: str):
    """按动作授权；原文读取统一禁止缓存并只审计路由模板。"""
    def dependency(request: Request, response: Response, user=Depends(_authenticated_user)):
        require_capability(user, "view")
        for action in actions:
            require_capability(user, action)
        if "reveal" in actions:
            response.headers["Cache-Control"] = "no-store"
            with db.tx() as conn:
                route = request.scope.get("route")
                references = {}
                for key, value in request.path_params.items():
                    text = str(value)
                    if key in {"node_id", "source_id", "bid", "tid", "did", "sid", "user_id"} and text.isdecimal():
                        references[key] = int(text)
                    elif key == "node_uid" and text.isascii() and len(text) <= 80 and text.replace("-", "").replace("_", "").isalnum():
                        references[key] = text
                security.audit(conn, user["username"], "访问私密内容", "api",
                               getattr(route, "path", ""), {"references": references})
        return user
    return Depends(dependency)


CurrentUser = Depends(require_user)
