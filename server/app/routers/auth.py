"""认证与维护者账号。多维护者共享同一份数据，账号仅用于访问控制。"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import SESSION_COOKIE, CurrentUser, create_session, destroy_session

router = APIRouter(prefix="/api/v1", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SetupBody(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=64)


class UserBody(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=64)


class PasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _set_cookie(response: Response, token: str, ttl_hours: int) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=ttl_hours * 3600, httponly=True, samesite="lax",
    )


@router.get("/setup/status")
def setup_status():
    with db.connect() as conn:
        count = db.one(conn, "SELECT COUNT(*) AS c FROM users")["c"]
    return {"initialized": count > 0}


@router.post("/setup")
def setup(body: SetupBody, request: Request, response: Response):
    with db.tx() as conn:
        count = db.one(conn, "SELECT COUNT(*) AS c FROM users")["c"]
        if count > 0:
            raise HTTPException(409, "系统已初始化，请直接登录")
        digest, salt = security.hash_password(body.password)
        cur = conn.execute(
            "INSERT INTO users(username, password_hash, salt, display_name, role, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (body.username, digest, salt, body.display_name, "admin", db.now()),
        )
        token, csrf, ttl = create_session(
            conn, cur.lastrowid, request.client.host if request.client else "",
            request.headers.get("user-agent", ""),
        )
        security.audit(conn, body.username, "初始化系统", "user", cur.lastrowid)
    _set_cookie(response, token, ttl)
    return {"username": body.username, "csrf_token": csrf}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    with db.tx() as conn:
        row = db.one(conn, "SELECT * FROM users WHERE username=?", (body.username,))
        if not row or not security.verify_password(
            body.password, row["password_hash"], row["salt"]
        ):
            raise HTTPException(401, "用户名或密码不正确")
        token, csrf, ttl = create_session(
            conn, row["id"], request.client.host if request.client else "",
            request.headers.get("user-agent", ""),
        )
        conn.execute(
            "UPDATE users SET last_login_at=? WHERE id=?", (db.now(), row["id"])
        )
        security.audit(conn, row["username"], "登录", "user", row["id"])
    _set_cookie(response, token, ttl)
    return {
        "username": row["username"],
        "display_name": row["display_name"],
        "csrf_token": csrf,
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response, user=CurrentUser):
    with db.tx() as conn:
        destroy_session(conn, user["token"])
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/auth/me")
def me(user=CurrentUser):
    return {
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "csrf_token": user["csrf_token"],
        "has_portal_pin": bool(user.get("portal_pin_hash")),
    }


@router.get("/users")
def list_users(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(
            conn,
            "SELECT id, username, display_name, role, portal_pin_hash, created_at, "
            "last_login_at FROM users ORDER BY id",
        )
    result = []
    for r in rows:
        item = db.row_to_dict(r)
        item["has_portal_pin"] = bool(item.pop("portal_pin_hash"))
        result.append(item)
    return result


@router.post("/users", status_code=201)
def create_user(body: UserBody, user=CurrentUser):
    with db.tx() as conn:
        if db.one(conn, "SELECT id FROM users WHERE username=?", (body.username,)):
            raise HTTPException(409, "用户名已存在")
        digest, salt = security.hash_password(body.password)
        cur = conn.execute(
            "INSERT INTO users(username, password_hash, salt, display_name, role, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (body.username, digest, salt, body.display_name, "admin", db.now()),
        )
        security.audit(conn, user["username"], "新增维护者", "user", cur.lastrowid,
                       {"username": body.username})
        row = db.one(
            conn,
            "SELECT id, username, display_name, role, created_at, last_login_at "
            "FROM users WHERE id=?",
            (cur.lastrowid,),
        )
    return db.row_to_dict(row)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user=CurrentUser):
    if user_id == user["id"]:
        raise HTTPException(400, "不能删除当前登录的账号")
    with db.tx() as conn:
        row = db.one(conn, "SELECT username FROM users WHERE id=?", (user_id,))
        if not row:
            raise HTTPException(404, "账号不存在")
        if db.one(conn, "SELECT COUNT(*) AS c FROM users")["c"] <= 1:
            raise HTTPException(400, "至少需要保留一个维护者账号")
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        security.audit(conn, user["username"], "删除维护者", "user", user_id,
                       {"username": row["username"]})
    return {"ok": True}


@router.post("/auth/password")
def change_password(body: PasswordBody, user=CurrentUser):
    with db.tx() as conn:
        row = db.one(conn, "SELECT * FROM users WHERE id=?", (user["id"],))
        if not security.verify_password(
            body.old_password, row["password_hash"], row["salt"]
        ):
            raise HTTPException(400, "原密码不正确")
        digest, salt = security.hash_password(body.new_password)
        conn.execute(
            "UPDATE users SET password_hash=?, salt=? WHERE id=?",
            (digest, salt, user["id"]),
        )
        # 修改口令后吊销该账号的其他会话
        conn.execute(
            "DELETE FROM sessions WHERE user_id=? AND token_hash!=?",
            (user["id"], security.sha256_text(user["token"])),
        )
        security.audit(conn, user["username"], "修改密码", "user", user["id"])
    return {"ok": True}
