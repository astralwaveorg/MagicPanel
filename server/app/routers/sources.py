"""节点来源：订阅地址加密存储，列表与详情只返回脱敏形式。"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import CurrentUser
from ..services import fetcher, tester, updater

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


class SourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str | None = Field(default=None, max_length=1024)  # 更新时留空表示不变
    enabled: bool = True
    filter: str = Field(default="", max_length=512)
    ua: str = Field(default="Stash", max_length=128)
    interval: int = Field(default=21600, ge=600, le=604800)
    test_interval: int = Field(default=21600, ge=0, le=604800)
    client_interval: int = Field(default=0, ge=0, le=604800)
    auto_fetch: bool = True
    auto_test: bool = True
    allow_private: bool = False
    filter_unavailable: bool = False


class BatchIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


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


def _public(row, with_meta: bool = True) -> dict:
    url = security.decrypt_text(row["url_enc"])
    data = {
        "id": row["id"],
        "name": row["name"],
        "url_masked": security.mask_url(url),
        "enabled": bool(row["enabled"]),
        "filter": row["filter"],
        "ua": row["ua"],
        "interval": row["interval"],
        "test_interval": row["test_interval"],
        "client_interval": row["client_interval"],
        "auto_fetch": bool(row["auto_fetch"]),
        "auto_test": bool(row["auto_test"]),
        "allow_private": bool(row["allow_private"]),
        "filter_unavailable": bool(row["filter_unavailable"]),
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


def _group_refs(conn, name: str) -> list[str]:
    """按名称找出引用该来源的策略组（构建按名称固化引用）。"""
    return [
        g["name"] for g in db.all_(
            conn, "SELECT name, use_sources FROM proxy_groups ORDER BY name")
        if name in json.loads(g["use_sources"] or "[]")
    ]


def _reference_reason(refs: list[str]) -> str:
    return f"仍被策略组引用：{'、'.join(refs)}，请先调整策略组"


def _delete_one(conn, row, operator: str) -> None:
    conn.execute("DELETE FROM sources WHERE id=?", (row["id"],))
    security.audit(conn, operator, "删除节点来源", "source", row["id"],
                   {"name": row["name"]})


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
    with db.tx() as conn:
        if db.one(conn, "SELECT id FROM sources WHERE name=?", (body.name,)):
            raise HTTPException(409, "同名节点来源已存在")
        now = db.now()
        cur = conn.execute(
            "INSERT INTO sources(name, url_enc, enabled, filter, ua, interval, "
            "client_interval, test_interval, auto_fetch, auto_test, allow_private, "
            "filter_unavailable, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.name, security.encrypt_text(body.url), int(body.enabled),
             body.filter, body.ua, body.interval, body.client_interval,
             body.test_interval, int(body.auto_fetch), int(body.auto_test),
             int(body.allow_private), int(body.filter_unavailable), now, now),
        )
        security.audit(conn, user["username"], "新增节点来源", "source", cur.lastrowid,
                       {"name": body.name})
        row = _get_or_404(conn, cur.lastrowid)
    return _public(row)


@router.put("/{source_id}")
def update_source(source_id: int, body: SourceBody, user=CurrentUser):
    _check_filter(body.filter)
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        clash = db.one(
            conn, "SELECT id FROM sources WHERE name=? AND id!=?", (body.name, source_id)
        )
        if clash:
            raise HTTPException(409, "同名节点来源已存在")
        if body.name != row["name"]:
            refs = _group_refs(conn, row["name"])
            if refs:
                raise HTTPException(
                    400,
                    f"节点来源“{row['name']}”{_reference_reason(refs)}；"
                    "重命名会使这些引用失效，请先调整策略组或保持名称不变",
                )
        url_enc = row["url_enc"]
        if body.url:
            url_enc = security.encrypt_text(body.url)
        conn.execute(
            "UPDATE sources SET name=?, url_enc=?, enabled=?, filter=?, ua=?, "
            "interval=?, client_interval=?, test_interval=?, auto_fetch=?, "
            "auto_test=?, allow_private=?, filter_unavailable=?, updated_at=? "
            "WHERE id=?",
            (body.name, url_enc, int(body.enabled), body.filter, body.ua,
             body.interval, body.client_interval, body.test_interval,
             int(body.auto_fetch), int(body.auto_test), int(body.allow_private),
             int(body.filter_unavailable), db.now(), source_id),
        )
        security.audit(conn, user["username"], "更新节点来源", "source", source_id,
                       {"name": body.name, "url_changed": bool(body.url)})
        row = _get_or_404(conn, source_id)
    return _public(row)


@router.delete("/{source_id}")
def delete_source(source_id: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        refs = _group_refs(conn, row["name"])
        if refs:
            raise HTTPException(400, f"节点来源“{row['name']}”{_reference_reason(refs)}")
        _delete_one(conn, row, user["username"])
    return {"ok": True}


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
    """批量删除：逐个校验策略组引用，被引用的保留并返回原因。"""
    deleted: list[int] = []
    blocked: list[dict] = []
    with db.tx() as conn:
        for source_id in dict.fromkeys(body.ids):
            row = db.one(conn, "SELECT * FROM sources WHERE id=?", (source_id,))
            if not row:
                blocked.append({"id": source_id, "name": f"#{source_id}",
                                "reason": "节点来源不存在（可能已被删除）"})
                continue
            refs = _group_refs(conn, row["name"])
            if refs:
                blocked.append({"id": source_id, "name": row["name"],
                                "reason": _reference_reason(refs)})
                continue
            _delete_one(conn, row, user["username"])
            deleted.append(source_id)
    return {"ok": True, "deleted": deleted, "blocked": blocked}


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
