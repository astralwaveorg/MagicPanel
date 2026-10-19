"""本地单节点：手动填写服务器与协议参数，直接写入产物顶层 proxies。"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import CurrentUser
from ..services import local_nodes

router = APIRouter(prefix="/api/v1/local-nodes", tags=["local-nodes"])


class LocalNodeBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    protocol: str = Field(min_length=1, max_length=32)
    server: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    params: dict = Field(default_factory=dict)
    extra_yaml: str = Field(default="", max_length=20_000)
    enabled: bool = True


def _decrypt(value: str) -> str:
    return security.decrypt_text(value) if value else ""


def _public(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "marked_name": local_nodes.marked_name(row["name"]),
        "protocol": row["protocol"],
        "server": row["server"],
        "port": row["port"],
        "params": json.loads(_decrypt(row["params_enc"]) or "{}"),
        "extra_yaml": _decrypt(row["extra_yaml_enc"]),
        "enabled": bool(row["enabled"]),
        "sort": row["sort"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_or_404(conn, node_id: int):
    row = db.one(conn, "SELECT * FROM local_nodes WHERE id=?", (node_id,))
    if not row:
        raise HTTPException(404, "本地节点不存在")
    return row


def _prepare(body: LocalNodeBody) -> tuple[dict, str]:
    if not body.name.strip():
        raise HTTPException(400, "名称不能为空")
    if not body.server.strip():
        raise HTTPException(400, "服务器地址不能为空")
    try:
        params = local_nodes.normalize_params(body.protocol, body.params)
        local_nodes.parse_extra(body.extra_yaml)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return params, body.extra_yaml


@router.get("/schema")
def node_schema(user=CurrentUser):
    return {"protocols": local_nodes.protocol_schema(), "mark": local_nodes.MARK}


@router.get("")
def list_nodes(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM local_nodes ORDER BY sort, id")
    return [_public(r) for r in rows]


@router.post("", status_code=201)
def create_node(body: LocalNodeBody, user=CurrentUser):
    params, extra_yaml = _prepare(body)
    marked = local_nodes.marked_name(body.name.strip())
    with db.tx() as conn:
        if db.one(conn, "SELECT id FROM local_nodes WHERE name=?", (body.name.strip(),)):
            raise HTTPException(409, "同名本地节点已存在")
        if db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (marked,)):
            raise HTTPException(409, "本地节点标记名与策略组重名，请换一个名称")
        now = db.now()
        sort = db.one(
            conn, "SELECT COALESCE(MAX(sort), 0) + 1 AS n FROM local_nodes")["n"]
        cur = conn.execute(
            "INSERT INTO local_nodes(name, protocol, server, port, params_enc, "
            "extra_yaml_enc, enabled, sort, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (body.name.strip(), body.protocol, body.server.strip(), body.port,
             security.encrypt_text(json.dumps(params, ensure_ascii=False)),
             security.encrypt_text(extra_yaml),
             int(body.enabled), sort, now, now),
        )
        security.audit(conn, user["username"], "新增本地节点", "local_node",
                       cur.lastrowid, {"name": body.name, "protocol": body.protocol})
        row = _get_or_404(conn, cur.lastrowid)
    return _public(row)


@router.put("/{node_id}")
def update_node(node_id: int, body: LocalNodeBody, user=CurrentUser):
    params, extra_yaml = _prepare(body)
    marked = local_nodes.marked_name(body.name.strip())
    with db.tx() as conn:
        row = _get_or_404(conn, node_id)
        clash = db.one(
            conn, "SELECT id FROM local_nodes WHERE name=? AND id!=?",
            (body.name.strip(), node_id),
        )
        if clash:
            raise HTTPException(409, "同名本地节点已存在")
        if db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (marked,)):
            raise HTTPException(409, "本地节点标记名与策略组重名，请换一个名称")
        conn.execute(
            "UPDATE local_nodes SET name=?, protocol=?, server=?, port=?, "
            "params_enc=?, extra_yaml_enc=?, enabled=?, updated_at=? WHERE id=?",
            (body.name.strip(), body.protocol, body.server.strip(), body.port,
             security.encrypt_text(json.dumps(params, ensure_ascii=False)),
             security.encrypt_text(extra_yaml), int(body.enabled), db.now(),
             node_id),
        )
        security.audit(conn, user["username"], "更新本地节点", "local_node", node_id,
                       {"name": body.name, "protocol": body.protocol})
        row = _get_or_404(conn, node_id)
    return _public(row)


@router.delete("/{node_id}")
def delete_node(node_id: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_or_404(conn, node_id)
        used = [
            g["name"] for g in db.all_(conn, "SELECT name, local_nodes FROM proxy_groups")
            if node_id in json.loads(g["local_nodes"] or "[]")
        ]
        if used:
            raise HTTPException(
                400, f"本地节点仍被策略组引用：{'、'.join(used)}，请先调整策略组")
        conn.execute("DELETE FROM local_nodes WHERE id=?", (node_id,))
        security.audit(conn, user["username"], "删除本地节点", "local_node", node_id,
                       {"name": row["name"]})
    return {"ok": True}
