"""规则来源：远程规则集与内联规则集，统一由服务端快照向设备分发。"""
import base64

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..deps import CurrentUser
from ..services import fetcher, refs, repo_manager, repo_sync, updater

router = APIRouter(prefix="/api/v1/rule-providers", tags=["rule-providers"])

BEHAVIORS = {"domain", "ipcidr", "classical"}
FORMATS = {"yaml", "text", "mrs"}


class RuleProviderBody(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[^\s/?#%&]+$")
    behavior: str = "domain"
    format: str = "yaml"
    kind: str = "remote"  # remote / inline / repo
    url: str = Field(default="", max_length=1024)
    # 仓库托管的来源：仓库内相对路径，内容由同步写入
    repo_path: str = Field(default="", max_length=512)
    inline_content: str = Field(default="", max_length=2_000_000)
    interval: int = Field(default=86400, ge=600, le=604800)
    client_interval: int = Field(default=0, ge=0, le=604800)
    enabled: bool = True
    # 抓取走代理：服务端出不去规则站时经指定代理中转；留空表示直连
    proxy_url: str | None = Field(default=None, max_length=512)


class BatchIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    force: bool = False


class BatchInterval(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    interval: int = Field(ge=600, le=604800)


def _public(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "behavior": row["behavior"],
        "format": row["format"],
        "kind": row["kind"],
        "url": row["url"],
        "interval": row["interval"],
        "client_interval": row["client_interval"],
        "enabled": bool(row["enabled"]),
        "use_proxy": bool(row["proxy_url_enc"] or ""),
        "proxy_url_masked": (security.mask_url(security.decrypt_text(row["proxy_url_enc"]))
                             if row["proxy_url_enc"] else ""),
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "last_fetched_at": row["last_fetched_at"],
        "last_attempt_at": row["last_attempt_at"],
        # 仓库托管的来源：仓库内相对路径（kind='repo'）
        "repo_path": row["repo_path"] if "repo_path" in row.keys() else "",
        # 二进制格式（MRS）的条目数数不出来，留空由界面显示"—"
        "rule_count": (None if (row["format"] or "yaml") in config.BINARY_FORMATS
                       else row["rule_count"]),
        "sha256": row["sha256"],
        "has_content": bool(row["content"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_body(body: RuleProviderBody) -> None:
    if body.behavior not in BEHAVIORS:
        raise HTTPException(400, f"behavior 仅支持：{'、'.join(sorted(BEHAVIORS))}")
    if body.format not in FORMATS:
        raise HTTPException(400, f"format 仅支持：{'、'.join(sorted(FORMATS))}")
    if body.kind == "remote" and not body.url:
        raise HTTPException(400, "远程规则来源必须填写 URL")
    if body.kind == "inline" and not body.inline_content.strip():
        raise HTTPException(400, "内联规则来源必须填写内容")
    if body.kind == "repo" and not body.repo_path.strip():
        raise HTTPException(400, "仓库托管的规则来源必须指定仓库内路径")


def _get_or_404(conn, rp_id: int):
    row = db.one(conn, "SELECT * FROM rule_providers WHERE id=?", (rp_id,))
    if not row:
        raise HTTPException(404, "规则来源不存在")
    return row


def _rule_refs(conn, name: str) -> list:
    """所有引用该规则来源的分流规则，含已停用规则（重新启用后会再次生效）。"""
    return db.all_(
        conn,
        "SELECT id, enabled, target FROM rules WHERE type='RULE-SET' AND value=? "
        "ORDER BY sort, id",
        (name,),
    )


def _reference_reason(refs: list) -> str:
    ids = "、".join(f"#{r['id']}" for r in refs[:5])
    more = f" 等 {len(refs)} 条" if len(refs) > 5 else ""
    return f"仍被 {len(refs)} 条分流规则引用（{ids}{more}），请先删除或调整对应规则"


def _delete_one(conn, row, operator: str,
                removed_rules: list[dict] | None = None) -> None:
    conn.execute("DELETE FROM rule_providers WHERE id=?", (row["id"],))
    security.audit(conn, operator, "删除规则来源", "rule_provider", row["id"],
                   {"name": row["name"],
                    "removed_rules": [r["id"] for r in (removed_rules or [])]})


def _referencing_rules(conn, names: list[str]) -> dict:
    """找出引用了这些规则来源的分流规则：名字 → [{id, type, value, target}]。

    规则来源改名时也要跟着改引用，这里给出完整清单，
    前端可以直接点进对应的分流规则里改。
    """
    if not names:
        return {}
    marks = ",".join("?" for _ in names)
    rows = db.all_(
        conn,
        f"SELECT id, type, value, target, enabled FROM rules "
        f"WHERE type='RULE-SET' AND value IN ({marks}) ORDER BY sort, id",
        list(names),
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r["value"], []).append({
            "id": r["id"], "type": r["type"], "value": r["value"],
            "target": r["target"], "enabled": bool(r["enabled"]),
        })
    return result


def _public_with_refs(conn, row) -> dict:
    data = _public(row)
    refs = _referencing_rules(conn, [row["name"]]).get(row["name"], [])
    data["referenced_by"] = refs
    return data


class EnabledBody(BaseModel):
    enabled: bool


@router.get("/page")
def list_providers_paged(limit: int = 50, offset: int = 0, keyword: str = "",
                         kind: str = "", behavior: str = "", enabled: str = "",
                         status: str = "", referenced: str = "", user=CurrentUser):
    """规则来源分页列表。

    keyword 匹配名称或 URL；kind（remote/inline）、behavior 精确匹配；
    enabled 取 "0"（停用）/"1"（启用）；
    status 限定抓取结果：ok 成功 / failed 失败 / none 从未抓取。
    内联来源没有抓取这回事，不参与这个筛选。
    referenced 取 "0"（没被分流规则引用）/"1"（被引用）。
    """
    with db.connect() as conn:
        where, args = [], []
        if keyword:
            like = f"%{keyword}%"
            where.append("(name LIKE ? OR url LIKE ?)")
            args += [like, like]
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if behavior:
            where.append("behavior = ?")
            args.append(behavior)
        if enabled in ("0", "1"):
            where.append("enabled = ?")
            args.append(1 if enabled == "1" else 0)
        if status == "ok":
            where.append("kind = 'remote' AND last_status = 'ok'")
        elif status == "failed":
            where.append("kind = 'remote' AND last_status = 'failed'")
        elif status == "none":
            where.append("kind = 'remote' "
                         "AND COALESCE(last_status, '') IN ('never', '')")
        if referenced in ("0", "1"):
            clause = ("EXISTS (SELECT 1 FROM rules WHERE rules.type='RULE-SET' "
                      "AND rules.value = rule_providers.name)")
            where.append(clause if referenced == "1" else f"NOT {clause}")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        data = db.paged(conn, "rule_providers", clause, args, "id", limit, offset)
        data["items"] = [_public_with_refs(conn, r) for r in data["items"]]
        # 未筛选时的总数，界面好写"筛选出 N 个（共 M 个）"
        total_all = db.one(conn, "SELECT COUNT(*) AS c FROM rule_providers")["c"]
    data["total_all"] = total_all
    return data


@router.get("")
def list_providers(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM rule_providers ORDER BY id")
        return [_public_with_refs(conn, r) for r in rows]


@router.get("/{rp_id}/content")
def get_content(rp_id: int, user=CurrentUser):
    """规则内容不涉凭据，允许维护者查看最近快照原文。"""
    with db.connect() as conn:
        row = _get_or_404(conn, rp_id)
    if (row["format"] or "yaml") in config.BINARY_FORMATS:
        # 二进制格式（MRS）：库里存的是 base64，没有可读原文
        return {"name": row["name"], "content": "", "binary": True,
                "format": row["format"],
                "size": len(base64.b64decode(row["content"] or ""))}
    return {"name": row["name"], "content": row["content"], "binary": False}


@router.post("", status_code=201)
def create_provider(body: RuleProviderBody, user=CurrentUser):
    _validate_body(body)
    with db.tx() as conn:
        if db.one(conn, "SELECT id FROM rule_providers WHERE name=?", (body.name,)):
            raise HTTPException(409, "同名规则来源已存在")
        content = body.inline_content if body.kind == "inline" else ""
        count = None
        sha = None
        status = "never"
        fetched = None
        if body.kind == "inline":
            count = fetcher.count_rules(content.encode(), body.behavior)
            sha = security.sha256_text(content)
            status = "ok"
            fetched = db.now()
        now = db.now()
        cur = conn.execute(
            "INSERT INTO rule_providers(name, behavior, format, kind, url, "
            "inline_content, interval, client_interval, enabled, content, "
            "rule_count, sha256, last_status, last_fetched_at, proxy_url_enc, "
            "repo_path, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.name, body.behavior, body.format, body.kind, body.url,
             body.inline_content, body.interval, body.client_interval,
             int(body.enabled), content, count, sha, status, fetched,
             security.encrypt_text(body.proxy_url) if body.proxy_url else "",
             body.repo_path, now, now),
        )
        security.audit(conn, user["username"], "新增规则来源", "rule_provider",
                       cur.lastrowid, {"name": body.name})
        row = _get_or_404(conn, cur.lastrowid)
    return _public(row)


@router.put("/{rp_id}")
def update_provider(rp_id: int, body: RuleProviderBody, force: bool = False,
                  user=CurrentUser):
    _validate_body(body)
    with db.tx() as conn:
        _get_or_404(conn, rp_id)
        clash = db.one(
            conn, "SELECT id FROM rule_providers WHERE name=? AND id!=?",
            (body.name, rp_id),
        )
        if clash:
            raise HTTPException(409, "同名规则来源已存在")
        old = _get_or_404(conn, rp_id)
        renamed_rules: list[dict] = []
        if body.name != old["name"]:
            used_by = _rule_refs(conn, old["name"])
            if used_by and not force:
                raise HTTPException(409, detail={
                    "code": "rule_provider_in_use",
                    "message": f"规则来源“{old['name']}”仍被 {len(used_by)} 条分流规则引用",
                    "provider": {"id": rp_id, "name": old["name"]},
                    "references": [
                        {"id": r["id"], "name": f"#{r['id']}", "type": "分流规则",
                         "extra": r["target"] + ("（已停用）" if not r["enabled"] else "")}
                        for r in used_by
                    ],
                    "rename_to": body.name,
                })
            if used_by:
                renamed_rules = refs.rename_rule_provider(conn, old["name"], body.name)
        content = old["content"]
        count = old["rule_count"]
        sha = old["sha256"]
        status = old["last_status"]
        fetched = old["last_fetched_at"]
        attempt = old["last_attempt_at"]
        # proxy_url 留空表示不改；要改成直连传空字符串
        proxy_enc = old["proxy_url_enc"]
        if body.proxy_url is not None:
            proxy_enc = security.encrypt_text(body.proxy_url) if body.proxy_url else ""
        if body.kind == "inline":
            content = body.inline_content
            count = fetcher.count_rules(content.encode(), body.behavior)
            sha = security.sha256_text(content)
            status = "ok"
            fetched = db.now()
        elif body.kind == "repo":
            # 仓库托管：内容由同步写入，界面改不动
            content = old["content"]
            count = old["rule_count"]
            sha = old["sha256"]
            status = old["last_status"]
            fetched = old["last_fetched_at"]
        elif old["kind"] == "inline":
            # 从 inline 切到 remote：清空旧快照与尝试时间，下一轮立即抓取
            content, count, sha, status, fetched = "", None, None, "never", None
            attempt = None
        # 仓库路径只对 kind='repo' 有意义：换成远程或内联时一并清掉，
        # 否则来源已经不用仓库了，仓库里的同名文件却还删不掉。
        repo_path = body.repo_path.strip() if body.kind == "repo" else ""
        if body.kind == "repo" and not repo_path:
            # 界面上没改路径就沿用原来的
            repo_path = old["repo_path"] if "repo_path" in old.keys() else ""
        conn.execute(
            "UPDATE rule_providers SET name=?, behavior=?, format=?, kind=?, url=?, "
            "inline_content=?, interval=?, client_interval=?, enabled=?, content=?, "
            "rule_count=?, sha256=?, last_status=?, last_fetched_at=?, "
            "last_attempt_at=?, proxy_url_enc=?, repo_path=?, updated_at=? WHERE id=?",
            (body.name, body.behavior, body.format, body.kind, body.url,
             body.inline_content, body.interval, body.client_interval,
             int(body.enabled), content, count, sha, status, fetched, attempt,
             proxy_enc, repo_path, db.now(), rp_id),
        )
        security.audit(conn, user["username"], "更新规则来源", "rule_provider", rp_id,
                       {"name": body.name})
        row = _get_or_404(conn, rp_id)
    return _public(row)


@router.patch("/{rp_id}/enabled")
def set_provider_enabled(rp_id: int, body: EnabledBody, user=CurrentUser):
    """启停规则来源：只改启用状态，其它字段一个都不动。"""
    with db.tx() as conn:
        row = _get_or_404(conn, rp_id)
        conn.execute("UPDATE rule_providers SET enabled=?, updated_at=? WHERE id=?",
                     (int(body.enabled), db.now(), rp_id))
        security.audit(
            conn, user["username"],
            "启用规则来源" if body.enabled else "停用规则来源",
            "rule_provider", rp_id, {"name": row["name"]})
        row = _get_or_404(conn, rp_id)
    return _public(row)


@router.delete("/{rp_id}")
def delete_provider(rp_id: int, force: bool = False, user=CurrentUser):
    """删除规则来源。

    仍被分流规则引用时默认拒绝，并返回引用明细（前端据此弹二次确认）；
    带 force=1 时自动删除这些规则再删来源。
    """
    with db.tx() as conn:
        row = _get_or_404(conn, rp_id)
        used_by = _rule_refs(conn, row["name"])
        if used_by and not force:
            raise HTTPException(409, detail={
                "code": "rule_provider_in_use",
                "message": f"规则来源“{row['name']}”仍被 {len(used_by)} 条分流规则引用",
                "provider": {"id": rp_id, "name": row["name"]},
                "references": [
                    {"id": r["id"], "name": f"#{r['id']}", "type": "分流规则",
                     "extra": r["target"] + ("（已停用）" if not r["enabled"] else "")}
                    for r in used_by
                ],
            })
        removed = refs.detach_rule_provider(conn, row["name"]) if used_by else []
        _delete_one(conn, row, user["username"], removed)
    return {"ok": True, "deleted_rules": removed}


@router.patch("/batch")
def batch_update_providers(body: BatchInterval, user=CurrentUser):
    """批量修改刷新间隔；内联来源的间隔同样会写入后续构建产物。"""
    ids = list(dict.fromkeys(body.ids))
    with db.tx() as conn:
        rows = [r for r in (
            db.one(conn, "SELECT id, name FROM rule_providers WHERE id=?", (i,))
            for i in ids
        ) if r]
        conn.executemany(
            "UPDATE rule_providers SET interval=?, updated_at=? WHERE id=?",
            [(body.interval, db.now(), r["id"]) for r in rows],
        )
        if rows:
            security.audit(conn, user["username"], "批量修改规则来源刷新间隔",
                           "rule_provider", ",".join(str(r["id"]) for r in rows),
                           {"interval": body.interval,
                            "names": [r["name"] for r in rows]})
        missing = [i for i in ids if i not in {r["id"] for r in rows}]
    return {"ok": True, "updated": len(rows), "missing": missing,
            "interval": body.interval}


@router.post("/batch/delete")
def batch_delete_providers(body: BatchIds, user=CurrentUser):
    """批量删除：逐个校验分流规则引用。

    默认被引用的保留并返回引用明细；force=True 时自动删除相关规则后一并删除。
    """
    deleted: list[int] = []
    blocked: list[dict] = []
    removed_rules: list[dict] = []
    with db.tx() as conn:
        for rp_id in dict.fromkeys(body.ids):
            row = db.one(conn, "SELECT * FROM rule_providers WHERE id=?", (rp_id,))
            if not row:
                blocked.append({"id": rp_id, "name": f"#{rp_id}",
                                "reason": "规则来源不存在（可能已被删除）"})
                continue
            used_by = _rule_refs(conn, row["name"])
            if used_by and not body.force:
                blocked.append({
                    "id": rp_id, "name": row["name"],
                    "reason": _reference_reason(used_by),
                    "references": [
                        {"id": r["id"], "name": f"#{r['id']}", "type": "分流规则",
                         "extra": r["target"] + ("（已停用）" if not r["enabled"] else "")}
                        for r in used_by
                    ],
                })
                continue
            gone = refs.detach_rule_provider(conn, row["name"]) if used_by else []
            removed_rules.extend(gone)
            _delete_one(conn, row, user["username"], gone)
            deleted.append(rp_id)
    return {"ok": True, "deleted": deleted, "blocked": blocked,
            "deleted_rules": removed_rules}


@router.post("/{rp_id}/refresh")
def refresh_provider(rp_id: int, user=CurrentUser):
    # 仓库托管的来源不做抓取：只从仓库工作树同步这一个文件的内容
    with db.connect() as conn:
        existing = _get_or_404(conn, rp_id)
        if existing["kind"] == "repo":
            try:
                row = repo_sync.sync_one(conn, existing["name"], user["username"])
            except (repo_sync.SyncError, repo_manager.RepoError) as exc:
                raise HTTPException(400, str(exc))
            return _public(row)
    try:
        row = updater.refresh_provider(rp_id, user["username"])
    except updater.NotFound as exc:
        raise HTTPException(404, str(exc))
    except updater.InvalidOperation as exc:
        raise HTTPException(400, str(exc))
    except fetcher.FetchError as exc:
        raise HTTPException(502, f"抓取失败：{exc}（已保留最近一次成功快照）")
    return _public(row)
