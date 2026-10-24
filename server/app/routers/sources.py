"""节点来源：订阅地址加密存储，列表与详情只返回脱敏形式。"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..deps import CurrentUser
from ..services import fetcher, refs, tester, updater

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


class SourceBody(BaseModel):
    # 名称会进入 provider 的订阅 URL（/res/provider/<name>），
    # 允许空格或斜杠会让 URL 失效、客户端拿不到节点。
    name: str = Field(min_length=1, max_length=64, pattern=r"^[^\s/?#%&]+$")
    url: str | None = Field(default=None, max_length=1024)  # 更新时留空表示不变
    enabled: bool = True
    filter: str = Field(default="", max_length=512)
    ua: str = Field(default="Stash", max_length=128)
    # 节点名后缀：不同来源可能有同名节点，客户端按名字去重会互相覆盖。
    # 填了就在客户端侧给这个来源的节点名追加后缀（additional-suffix）。
    suffix: str = Field(default="", max_length=32)
    # 下发方式：provider（写进 proxy-providers，客户端自己更新）
    # 或 inline（节点写进顶层 proxies，能进 GLOBAL 组）
    mode: str = Field(default=config.SOURCE_MODE_PROVIDER, max_length=16)
    interval: int = Field(default=21600, ge=600, le=604800)
    test_interval: int = Field(default=21600, ge=0, le=604800)
    client_interval: int = Field(default=0, ge=0, le=604800)
    auto_fetch: bool = True
    auto_test: bool = True
    allow_private: bool = False
    filter_unavailable: bool = False
    # 抓取走代理：服务端出不去机场订阅站时经指定代理中转；留空表示直连
    proxy_url: str | None = Field(default=None, max_length=512)


class BatchIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    force: bool = False


class BatchInterval(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    interval: int | None = Field(default=None, ge=600, le=604800)
    test_interval: int | None = Field(default=None, ge=0, le=604800)


def _check_filter(value: str) -> None:
    if value:
        try:
            re.compile(value)
        except re.error as exc:
            raise HTTPException(400, f"过滤正则无效：{exc}")


def _check_mode(value: str) -> str:
    if value not in config.SOURCE_MODES:
        raise HTTPException(400, f"下发方式仅支持：{'、'.join(config.SOURCE_MODES)}")
    return value


def _public(row, with_meta: bool = True) -> dict:
    url = security.decrypt_text(row["url_enc"])
    data = {
        "id": row["id"],
        "name": row["name"],
        "url_masked": security.mask_url(url),
        "enabled": bool(row["enabled"]),
        "filter": row["filter"],
        "ua": row["ua"],
        "suffix": row["suffix"] if "suffix" in row.keys() else "",
        "mode": (row["mode"] if "mode" in row.keys()
                 else config.SOURCE_MODE_PROVIDER),
        "interval": row["interval"],
        "test_interval": row["test_interval"],
        "client_interval": row["client_interval"],
        "auto_fetch": bool(row["auto_fetch"]),
        "auto_test": bool(row["auto_test"]),
        "allow_private": bool(row["allow_private"]),
        "filter_unavailable": bool(row["filter_unavailable"]),
        "use_proxy": bool(row["proxy_url_enc"] or ""),
        "proxy_url_masked": (security.mask_url(security.decrypt_text(row["proxy_url_enc"]))
                             if row["proxy_url_enc"] else ""),
        "tested_at": row["tested_at"],
        "test_attempt_at": row["test_attempt_at"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "last_fetched_at": row["last_fetched_at"],
        "last_attempt_at": row["last_attempt_at"],
        "node_count": row["node_count"],
        "sha256": row["sha256"],
        "fail_count": row["fail_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if with_meta:
        results = json.loads(row["test_results"] or "{}")
        nodes = []
        for node in json.loads(row["nodes_meta"] or "[]"):
            entry = dict(node)
            if node["name"] not in results:
                entry["status"] = "untested"
                entry["delay"] = None
            elif results[node["name"]] >= 0:
                entry["status"] = "ok"
                entry["delay"] = results[node["name"]]
            else:
                entry["status"] = "failed"
                entry["delay"] = None
            nodes.append(entry)
        data["nodes"] = nodes
        data["tested_ok"] = sum(1 for n in nodes if n["status"] == "ok")
        data["tested_failed"] = sum(1 for n in nodes if n["status"] == "failed")
    return data


def _get_or_404(conn, source_id: int):
    row = db.one(conn, "SELECT * FROM sources WHERE id=?", (source_id,))
    if not row:
        raise HTTPException(404, "节点来源不存在")
    return row


def _group_refs(conn, name: str) -> list[dict]:
    """按名称找出引用该来源的策略组（构建按名称固化引用）。"""
    return refs.source_refs(conn, name)


def _reference_reason(refs_list: list[dict]) -> str:
    names = "、".join(r["name"] for r in refs_list)
    return f"仍被策略组引用：{names}，请先调整策略组"


def _delete_one(conn, row, operator: str, detached: list[str] | None = None) -> None:
    conn.execute("DELETE FROM sources WHERE id=?", (row["id"],))
    security.audit(conn, operator, "删除节点来源", "source", row["id"],
                   {"name": row["name"], "detached_groups": detached or []})


@router.get("/page")
def list_sources_paged(limit: int = 50, offset: int = 0, keyword: str = "",
                       mode: str = "", enabled: str = "", status: str = "",
                       auto_fetch: str = "", user=CurrentUser):
    """节点来源分页列表。

    keyword 匹配名称；mode（provider/inline）按下发方式精确匹配；
    enabled 取 "0"（停用）/"1"（启用）；auto_fetch 同理，指自动抓取开关；
    status 限定抓取结果：ok 成功 / failed 失败 / none 从未抓取。
    """
    with db.connect() as conn:
        where, args = [], []
        if keyword:
            where.append("name LIKE ?")
            args.append(f"%{keyword}%")
        if mode:
            where.append("COALESCE(mode, ?) = ?")
            args += [config.SOURCE_MODE_PROVIDER, mode]
        if enabled in ("0", "1"):
            where.append("enabled = ?")
            args.append(1 if enabled == "1" else 0)
        if auto_fetch in ("0", "1"):
            where.append("auto_fetch = ?")
            args.append(1 if auto_fetch == "1" else 0)
        if status == "ok":
            where.append("last_status = 'ok'")
        elif status == "failed":
            where.append("last_status = 'failed'")
        elif status == "none":
            where.append("COALESCE(last_status, '') IN ('never', '')")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        data = db.paged(conn, "sources", clause, args, "id", limit, offset)
        data["items"] = [_public(r) for r in data["items"]]
        # 未筛选时的总数，界面好写"筛选出 N 个（共 M 个）"
        total_all = db.one(conn, "SELECT COUNT(*) AS c FROM sources")["c"]
    data["total_all"] = total_all
    return data


@router.get("")
def list_sources(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM sources ORDER BY id")
    return [_public(r) for r in rows]


@router.post("", status_code=201)
def create_source(body: SourceBody, user=CurrentUser):
    if not body.url:
        raise HTTPException(400, "订阅地址不能为空")
    _check_filter(body.filter)
    _check_mode(body.mode)
    try:
        with db.tx() as conn:
            if db.one(conn, "SELECT id FROM sources WHERE name=?", (body.name,)):
                raise HTTPException(409, "同名节点来源已存在")
            now = db.now()
            cur = db.insert_unique(conn,
                "INSERT INTO sources(name, url_enc, enabled, filter, ua, suffix, interval, "
                "client_interval, test_interval, auto_fetch, auto_test, allow_private, "
                "filter_unavailable, proxy_url_enc, mode, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (body.name, security.encrypt_text(body.url), int(body.enabled),
                 body.filter, body.ua, body.suffix, body.interval, body.client_interval,
                 body.test_interval, int(body.auto_fetch), int(body.auto_test),
                 int(body.allow_private), int(body.filter_unavailable),
                 security.encrypt_text(body.proxy_url) if body.proxy_url else "",
                 body.mode, now, now),
            )
            security.audit(conn, user["username"], "新增节点来源", "source", cur.lastrowid,
                           {"name": body.name})
            row = _get_or_404(conn, cur.lastrowid)
    except db.UniqueViolation:
        raise HTTPException(409, "同名节点来源已存在")

    return _public(row)


@router.put("/{source_id}")
def update_source(source_id: int, body: SourceBody, force: bool = False,
                  user=CurrentUser):
    _check_filter(body.filter)
    _check_mode(body.mode)
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        clash = db.one(
            conn, "SELECT id FROM sources WHERE name=? AND id!=?", (body.name, source_id)
        )
        if clash:
            raise HTTPException(409, "同名节点来源已存在")
        renamed_groups: list[str] = []
        if body.name != row["name"]:
            used_by = _group_refs(conn, row["name"])
            if used_by and not force:
                raise HTTPException(409, detail={
                    "code": "source_in_use",
                    "message": f"节点来源“{row['name']}”仍被 {len(used_by)} 个策略组引用",
                    "source": {"id": source_id, "name": row["name"]},
                    "references": used_by,
                    "rename_to": body.name,
                })
            if used_by:
                renamed_groups = refs.rename_source(conn, row["name"], body.name)
        url_enc = row["url_enc"]
        if body.url:
            url_enc = security.encrypt_text(body.url)
        # proxy_url 留空表示不改；要改成直连传空字符串
        proxy_enc = row["proxy_url_enc"]
        if body.proxy_url is not None:
            proxy_enc = security.encrypt_text(body.proxy_url) if body.proxy_url else ""
        conn.execute(
            "UPDATE sources SET name=?, url_enc=?, enabled=?, filter=?, ua=?, "
            "suffix=?, interval=?, client_interval=?, test_interval=?, auto_fetch=?, "
            "auto_test=?, allow_private=?, filter_unavailable=?, proxy_url_enc=?, "
            "mode=?, updated_at=? WHERE id=?",
            (body.name, url_enc, int(body.enabled), body.filter, body.ua,
             body.suffix, body.interval, body.client_interval, body.test_interval,
             int(body.auto_fetch), int(body.auto_test), int(body.allow_private),
             int(body.filter_unavailable), proxy_enc, body.mode,
             db.now(), source_id),
        )
        security.audit(conn, user["username"], "更新节点来源", "source", source_id,
                       {"name": body.name, "url_changed": bool(body.url),
                        "renamed_groups": renamed_groups})
        row = _get_or_404(conn, source_id)
    return _public(row)


class EnabledBody(BaseModel):
    enabled: bool


@router.patch("/{source_id}/enabled")
def set_source_enabled(source_id: int, body: EnabledBody, user=CurrentUser):
    """启停节点来源：只改启用状态，其它字段一个都不动。"""
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        conn.execute("UPDATE sources SET enabled=?, updated_at=? WHERE id=?",
                     (int(body.enabled), db.now(), source_id))
        security.audit(
            conn, user["username"],
            "启用节点来源" if body.enabled else "停用节点来源",
            "source", source_id, {"name": row["name"]})
        row = _get_or_404(conn, source_id)
    return _public(row)


@router.delete("/{source_id}")
def delete_source(source_id: int, force: bool = False, user=CurrentUser):
    """删除节点来源。

    仍被策略组引用时默认拒绝，并返回引用明细（前端据此弹二次确认）；
    带 force=1 时自动把这些策略组里的引用摘掉再删除。
    """
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        used_by = _group_refs(conn, row["name"])
        if used_by and not force:
            raise HTTPException(409, detail={
                "code": "source_in_use",
                "message": f"节点来源“{row['name']}”仍被 {len(used_by)} 个策略组引用",
                "source": {"id": row["id"], "name": row["name"]},
                "references": used_by,
            })
        detached, warnings = (refs.detach_source(conn, row["name"])
                              if used_by else ([], []))
        _delete_one(conn, row, user["username"], detached)
    return {"ok": True, "detached_groups": detached, "warnings": warnings}


@router.patch("/batch")
def batch_update_sources(body: BatchInterval, user=CurrentUser):
    """批量修改抓取/测速间隔；抓取间隔同时写入后续构建产物供客户端更新。"""
    if body.interval is None and body.test_interval is None:
        raise HTTPException(400, "请至少提供一个间隔")
    ids = list(dict.fromkeys(body.ids))
    with db.tx() as conn:
        rows = [r for r in (
            db.one(conn, "SELECT id, name FROM sources WHERE id=?", (i,)) for i in ids
        ) if r]
        fields = []
        args: list = []
        if body.interval is not None:
            fields.append("interval=?")
            args.append(body.interval)
        if body.test_interval is not None:
            fields.append("test_interval=?")
            args.append(body.test_interval)
        fields.append("updated_at=?")
        if rows:
            conn.executemany(
                f"UPDATE sources SET {', '.join(fields)} WHERE id=?",
                [(*args, db.now(), r["id"]) for r in rows],
            )
            security.audit(conn, user["username"], "批量修改来源间隔", "source",
                           ",".join(str(r["id"]) for r in rows),
                           {"interval": body.interval,
                            "test_interval": body.test_interval,
                            "names": [r["name"] for r in rows]})
        missing = [i for i in ids if i not in {r["id"] for r in rows}]
    return {"ok": True, "updated": len(rows), "missing": missing,
            "interval": body.interval, "test_interval": body.test_interval}


@router.post("/batch/delete")
def batch_delete_sources(body: BatchIds, user=CurrentUser):
    """批量删除：逐个校验策略组引用。

    默认被引用的保留并返回引用明细；force=True 时自动解绑引用后一并删除。
    """
    deleted: list[int] = []
    blocked: list[dict] = []
    detached: dict[str, list[str]] = {}
    warnings: list[str] = []
    with db.tx() as conn:
        for source_id in dict.fromkeys(body.ids):
            row = db.one(conn, "SELECT * FROM sources WHERE id=?", (source_id,))
            if not row:
                blocked.append({"id": source_id, "name": f"#{source_id}",
                                "reason": "节点来源不存在（可能已被删除）"})
                continue
            used_by = _group_refs(conn, row["name"])
            if used_by and not body.force:
                blocked.append({"id": source_id, "name": row["name"],
                                "reason": _reference_reason(used_by),
                                "references": used_by})
                continue
            groups, warns = (refs.detach_source(conn, row["name"])
                              if used_by else ([], []))
            if groups:
                detached[row["name"]] = groups
            warnings.extend(warns)
            _delete_one(conn, row, user["username"], groups)
            deleted.append(source_id)
    return {"ok": True, "deleted": deleted, "blocked": blocked,
            "detached_groups": detached, "warnings": warnings}


@router.post("/{source_id}/reveal")
def reveal_source(source_id: int, user=CurrentUser):
    """解密并返回订阅地址原文，用于复制；操作记入审计。"""
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        url = security.decrypt_text(row["url_enc"])
        security.audit(conn, user["username"], "查看节点来源订阅地址", "source",
                       source_id, {"name": row["name"]})
    return {"id": source_id, "url": url}


@router.post("/{source_id}/refresh")
def refresh_source(source_id: int, user=CurrentUser):
    try:
        row = updater.refresh_source(source_id, user["username"])
    except updater.NotFound as exc:
        raise HTTPException(404, str(exc))
    except fetcher.FetchError as exc:
        raise HTTPException(502, f"抓取失败：{exc}（已保留最近一次成功快照）")
    return _public(row)


@router.post("/{source_id}/test")
def test_source(source_id: int, user=CurrentUser):
    """用本地 Mihomo 核心逐个测试节点连通性；结果供过滤与展示。

    结果只反映从本服务器所在网络出发的连通性，不代表客户端侧一定可用。
    """
    try:
        row = updater.test_source(source_id, user["username"])
    except updater.NotFound as exc:
        raise HTTPException(404, str(exc))
    except updater.InvalidOperation as exc:
        raise HTTPException(400, str(exc))
    except tester.TestError as exc:
        raise HTTPException(400, str(exc))
    return _public(row)
