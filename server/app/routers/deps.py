"""自主维护：依赖文件库的管理接口。

前缀 /api/v1/deps，全部需要登录 + CSRF。
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import CurrentUser
from ..services import repo_manager, repo_sync

router = APIRouter(prefix="/api/v1/deps", tags=["deps"])


def _fail(exc) -> None:
    """把内部异常翻成 400，带上用户看得懂的中文。"""
    if isinstance(exc, repo_manager.BusyError):
        # 另一个 Git 操作正在跑：409 让前端知道这是"冲突"而不是"出错"
        raise HTTPException(409, str(exc))
    raise HTTPException(400, str(exc))


class SettingsBody(BaseModel):
    enabled: bool | None = None
    url: str | None = None
    branch: str | None = None
    auth: str | None = None
    # 私钥与 token 只写不读：空串表示不修改，clear_* 显式清空
    private_key: str | None = None
    token: str | None = None
    clear_private_key: bool = False
    clear_token: bool = False
    commit_name: str | None = None
    commit_email: str | None = None
    sync_hours: int | None = Field(default=None, ge=1, le=168)
    auto_push: bool | None = None
    auto_create_rule_sources: bool | None = None
    exclude_paths: str | None = None


class FileBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(default="", max_length=2_000_000)


class CommitBody(BaseModel):
    message: str = Field(default="", max_length=256)
    push: bool = False


class ResolveBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    resolution: str = "manual"          # manual / theirs / ours
    content: str | None = None


class RevertBody(BaseModel):
    commit: str = Field(min_length=4, max_length=64)
    message: str = Field(default="", max_length=256)


@router.get("/status")
def deps_status(user=CurrentUser):
    with db.connect() as conn:
        return repo_manager.status(conn)


@router.get("/settings")
def deps_get_settings(user=CurrentUser):
    with db.connect() as conn:
        return repo_manager.get_settings(conn)


@router.put("/settings")
def deps_put_settings(body: SettingsBody, user=CurrentUser):
    with db.tx() as conn:
        values: dict = {}
        if body.enabled is not None:
            values["deps_enabled"] = "1" if body.enabled else "0"
        if body.url is not None:
            values["deps_url"] = body.url.strip()
        if body.branch is not None:
            values["deps_branch"] = body.branch.strip() or "main"
        if body.auth is not None:
            if body.auth not in ("ssh", "https", "none"):
                raise HTTPException(400, "鉴权方式仅支持 ssh / https / none")
            values["deps_auth"] = body.auth
        if body.private_key:
            values["deps_private_key_enc"] = security.encrypt_text(body.private_key)
        if body.clear_private_key:
            values["deps_private_key_enc"] = ""
        if body.token:
            values["deps_token_enc"] = security.encrypt_text(body.token)
        if body.clear_token:
            values["deps_token_enc"] = ""
        if body.commit_name is not None:
            values["deps_commit_name"] = body.commit_name.strip()
        if body.commit_email is not None:
            values["deps_commit_email"] = body.commit_email.strip()
        if body.sync_hours is not None:
            values["deps_sync_hours"] = str(body.sync_hours)
        if body.auto_push is not None:
            values["deps_auto_push"] = "1" if body.auto_push else "0"
        if body.auto_create_rule_sources is not None:
            values["deps_auto_create_rule_sources"] = "1" if body.auto_create_rule_sources else "0"
        if body.exclude_paths is not None:
            values["deps_exclude_paths"] = body.exclude_paths.strip()
        repo_manager.save_settings(conn, values)
        security.audit(conn, user["username"], "更新自主维护设置", "deps", "",
                       {"keys": sorted(values.keys())})
        return repo_manager.get_settings(conn)


@router.post("/clone")
def deps_clone(user=CurrentUser):
    with db.tx() as conn:
        try:
            with repo_manager.operation("克隆仓库"):
                result = repo_manager.clone(conn)
        except repo_manager.RepoError as exc:
            _fail(exc)
        security.audit(conn, user["username"], "克隆依赖仓库", "deps", "",
                       {"commit": result.get("commit", "")})
        return {"ok": True, **result}


@router.post("/generate-key")
def deps_generate_key(user=CurrentUser):
    """生成 SSH 密钥对：只回显公钥，私钥加密落库。"""
    try:
        private, public = repo_manager.generate_keypair()
    except repo_manager.RepoError as exc:
        _fail(exc)
    with db.tx() as conn:
        repo_manager.save_settings(conn, {
            "deps_private_key_enc": security.encrypt_text(private),
            "deps_auth": "ssh",
        })
        security.audit(conn, user["username"], "生成仓库部署密钥", "deps", "",
                       {"fingerprint": public.strip().split()[-1] if public.strip() else ""})
    return {"public_key": public, "private_key_saved": True}


@router.get("/files")
def deps_files(user=CurrentUser):
    with db.connect() as conn:
        try:
            return {"files": repo_manager.list_files(conn)}
        except repo_manager.RepoError as exc:
            _fail(exc)


@router.get("/file")
def deps_get_file(path: str = Query(...), user=CurrentUser):
    with db.connect() as conn:
        try:
            return repo_manager.read_file(conn, path)
        except repo_manager.RepoError as exc:
            _fail(exc)


@router.put("/file")
def deps_put_file(body: FileBody, user=CurrentUser):
    with db.connect() as conn:
        try:
            repo_manager.write_file(conn, body.path, body.content)
        except repo_manager.RepoError as exc:
            _fail(exc)
    return {"ok": True}


@router.post("/file")
def deps_post_file(body: FileBody, user=CurrentUser):
    with db.connect() as conn:
        try:
            repo_manager.create_file(conn, body.path, body.content)
        except repo_manager.RepoError as exc:
            _fail(exc)
    return {"ok": True}


@router.delete("/file")
def deps_delete_file(path: str = Query(...), user=CurrentUser):
    with db.connect() as conn:
        # 被规则来源消费的文件不允许直接删：先告诉用户引用关系
        used = repo_manager._rule_source_for(path, conn)
        if used:
            raise HTTPException(409, f"该文件已被规则来源「{used}」引用，先停用或改掉它")
        try:
            repo_manager.delete_file(conn, path)
        except repo_manager.RepoError as exc:
            _fail(exc)
    return {"ok": True}


@router.post("/commit")
def deps_commit(body: CommitBody, user=CurrentUser):
    with db.tx() as conn:
        try:
            # 提交与推送算一整件事：中间不让别的操作插进来，
            # 否则第二次点击会撞上"没有可提交的改动"。
            with repo_manager.operation("提交并推送" if body.push else "提交改动"):
                commit = repo_manager.commit_all(conn, body.message or "面板提交")
                if body.push:
                    repo_manager.push(conn)
        except repo_manager.RepoError as exc:
            _fail(exc)
        security.audit(conn, user["username"], "提交仓库改动", "deps", "",
                       {"commit": commit, "push": body.push})
        return {"ok": True, "commit": commit, "pushed": body.push}


@router.post("/sync")
def deps_sync(user=CurrentUser):
    """立即同步：拉取仓库并把 rule/*.yaml 同步进规则来源。"""
    with db.tx() as conn:
        try:
            with repo_manager.operation("同步仓库"):
                result = repo_sync.run_sync(conn, user["username"])
        except repo_sync.SyncError as exc:
            _fail(exc)
        except repo_manager.RepoError as exc:
            _fail(exc)
        security.audit(conn, user["username"], "同步依赖仓库", "deps", "",
                       {"created": result["created"], "updated": result["updated"]})
        return result


@router.get("/conflicts")
def deps_conflicts(user=CurrentUser):
    with db.connect() as conn:
        try:
            files = repo_manager.conflicted_files(conn)
            out = []
            for rel in files:
                out.append({"path": rel, **repo_manager.three_way(conn, rel)})
            return {"conflicts": out}
        except repo_manager.RepoError as exc:
            _fail(exc)


@router.post("/conflicts/resolve")
def deps_resolve(body: ResolveBody, user=CurrentUser):
    with db.tx() as conn:
        try:
            repo_manager.conflict_stage(conn, body.path, body.content, body.resolution)
        except repo_manager.RepoError as exc:
            _fail(exc)
        security.audit(conn, user["username"], "解决仓库冲突", "deps", "",
                       {"path": body.path, "resolution": body.resolution})
        return {"ok": True}


@router.get("/history")
def deps_history(limit: int = 30, user=CurrentUser):
    with db.connect() as conn:
        try:
            return {"history": repo_manager.history(conn, limit)}
        except repo_manager.RepoError as exc:
            _fail(exc)


@router.get("/diff")
def deps_diff(commit: str = Query(...), user=CurrentUser):
    with db.connect() as conn:
        try:
            return repo_manager.show_commit(conn, commit)
        except repo_manager.RepoError as exc:
            _fail(exc)


@router.post("/revert")
def deps_revert(body: RevertBody, user=CurrentUser):
    with db.tx() as conn:
        try:
            commit = repo_manager.revert_commit(conn, body.commit, body.message)
        except repo_manager.RepoError as exc:
            _fail(exc)
        security.audit(conn, user["username"], "回滚仓库提交", "deps", "",
                       {"commit": commit})
        return {"ok": True, "commit": commit}


@router.get("/migrations")
def deps_migrations(user=CurrentUser):
    """迁移存档与核对结果（切换规则来源到仓库托管时的留档）。"""
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM repo_migrations ORDER BY id DESC LIMIT 200")
    return {"migrations": [dict(r) for r in rows]}


@router.post("/rollback-migration")
def deps_rollback_migration(batch: int = Query(...), user=CurrentUser):
    """一键回退某一批：还原来源的 kind / url / repo_path 等字段。"""
    with db.tx() as conn:
        rows = db.all_(conn, "SELECT * FROM repo_migrations WHERE batch=?", (batch,))
        if not rows:
            raise HTTPException(404, "没有这一批的存档")
        for row in rows:
            conn.execute(
                "UPDATE rule_providers SET kind=?, url=?, repo_path=?, behavior=?, "
                "enabled=?, updated_at=? WHERE id=?",
                (row["origin_kind"], row["origin_url"], row["origin_repo_path"],
                 row["origin_behavior"], row["origin_enabled"], db.now(),
                 row["object_id"]),
            )
            conn.execute(
                "UPDATE repo_migrations SET reverted_at=? WHERE id=?",
                (db.now(), row["id"]),
            )
        security.audit(conn, user["username"], "回退仓库托管迁移", "deps", "",
                       {"batch": batch, "count": len(rows)})
    return {"ok": True, "reverted": len(rows)}
