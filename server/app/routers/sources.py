"""节点来源：订阅地址加密存储，列表与详情只返回脱敏形式。"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import CurrentUser
from ..services import fetcher, tester

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


class SourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str | None = Field(default=None, max_length=1024)  # 更新时留空表示不变
    enabled: bool = True
    filter: str = Field(default="", max_length=512)
    ua: str = Field(default="Stash", max_length=128)
    interval: int = Field(default=21600, ge=600, le=604800)
    allow_private: bool = False
    filter_unavailable: bool = False


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
        "allow_private": bool(row["allow_private"]),
        "filter_unavailable": bool(row["filter_unavailable"]),
        "tested_at": row["tested_at"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "last_fetched_at": row["last_fetched_at"],
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
            "allow_private, filter_unavailable, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (body.name, security.encrypt_text(body.url), int(body.enabled),
             body.filter, body.ua, body.interval, int(body.allow_private),
             int(body.filter_unavailable), now, now),
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
        url_enc = row["url_enc"]
        if body.url:
            url_enc = security.encrypt_text(body.url)
        conn.execute(
            "UPDATE sources SET name=?, url_enc=?, enabled=?, filter=?, ua=?, "
            "interval=?, allow_private=?, filter_unavailable=?, updated_at=? "
            "WHERE id=?",
            (body.name, url_enc, int(body.enabled), body.filter, body.ua,
             body.interval, int(body.allow_private), int(body.filter_unavailable),
             db.now(), source_id),
        )
        security.audit(conn, user["username"], "更新节点来源", "source", source_id,
                       {"name": body.name, "url_changed": bool(body.url)})
        row = _get_or_404(conn, source_id)
    return _public(row)


@router.delete("/{source_id}")
def delete_source(source_id: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        used = [
            g["name"] for g in db.all_(conn, "SELECT name, use_sources FROM proxy_groups")
            if row["name"] in json.loads(g["use_sources"] or "[]")
        ]
        if used:
            raise HTTPException(
                400, f"节点来源仍被策略组引用：{'、'.join(used)}，请先调整策略组"
            )
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        security.audit(conn, user["username"], "删除节点来源", "source", source_id,
                       {"name": row["name"]})
    return {"ok": True}


@router.post("/{source_id}/refresh")
def refresh_source(source_id: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        url = security.decrypt_text(row["url_enc"])
        now = db.now()
        try:
            body = fetcher.fetch(url, ua=row["ua"], allow_private=bool(row["allow_private"]))
            nodes = fetcher.parse_nodes(body)
        except fetcher.FetchError as exc:
            conn.execute(
                "UPDATE sources SET last_status='failed', last_error=?, "
                "fail_count=fail_count+1, updated_at=? WHERE id=?",
                (str(exc), now, source_id),
            )
            security.audit(conn, user["username"], "刷新节点来源失败", "source",
                           source_id, {"error": str(exc)})
            raise HTTPException(502, f"抓取失败：{exc}（已保留最近一次成功快照）")
        # 新快照的节点集合可能变化，旧的测速结果不再可信
        conn.execute(
            "UPDATE sources SET last_status='ok', last_error='', last_fetched_at=?, "
            "node_count=?, sha256=?, fail_count=0, snapshot_enc=?, nodes_meta=?, "
            "test_results='{}', tested_at=NULL, updated_at=? WHERE id=?",
            (now, len(nodes), security.sha256_text(body.decode("utf-8", "replace")),
             security.encrypt_text(body.decode("utf-8", "replace")),
             json.dumps(nodes, ensure_ascii=False), now, source_id),
        )
        security.audit(conn, user["username"], "刷新节点来源", "source", source_id,
                       {"name": row["name"], "node_count": len(nodes)})
        row = _get_or_404(conn, source_id)
    return _public(row)


@router.post("/{source_id}/test")
def test_source(source_id: int, user=CurrentUser):
    """用本地 Mihomo 核心逐个测试节点连通性；结果供过滤与展示。

    结果只反映从本服务器所在网络出发的连通性，不代表客户端侧一定可用。
    """
    with db.tx() as conn:
        row = _get_or_404(conn, source_id)
        if not row["snapshot_enc"]:
            raise HTTPException(400, "还没有节点快照，请先抓取来源")
        snapshot = security.decrypt_text(row["snapshot_enc"])
        try:
            outcome = tester.test_nodes(snapshot)
        except tester.TestError as exc:
            raise HTTPException(400, str(exc))
        conn.execute(
            "UPDATE sources SET test_results=?, tested_at=?, updated_at=? WHERE id=?",
            (json.dumps(outcome["results"], ensure_ascii=False), db.now(), db.now(),
             source_id),
        )
        security.audit(conn, user["username"], "测试节点连通性", "source", source_id,
                       {"name": row["name"], "total": outcome["total"],
                        "ok": outcome["ok"], "failed": outcome["failed"]})
        row = _get_or_404(conn, source_id)
    return _public(row)
