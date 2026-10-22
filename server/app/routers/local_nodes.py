"""本地单节点：手动填写服务器与协议参数，直接写入产物顶层 proxies。"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import CurrentUser
from ..services import local_nodes
from ..services import refs
from ..services import tester

router = APIRouter(prefix="/api/v1/local-nodes", tags=["local-nodes"])


class LocalNodeBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    node_type: str = Field(default=local_nodes.DEFAULT_NODE_TYPE, max_length=16)
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
        "node_type": row["node_type"] or "",
        "display_name": local_nodes.display_name(
            row["name"], row["node_type"] or ""),
        "protocol": row["protocol"],
        "server": row["server"],
        "port": row["port"],
        "params": json.loads(_decrypt(row["params_enc"]) or "{}"),
        "extra_yaml": _decrypt(row["extra_yaml_enc"]),
        "enabled": bool(row["enabled"]),
        "sort": row["sort"],
        "test_status": row["test_status"] or "",
        "test_delay": row["test_delay"] or 0,
        "tested_at": row["tested_at"] or "",
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
    node_type = (body.node_type or "").strip()
    if node_type and node_type not in local_nodes.NODE_TYPES:
        raise HTTPException(
            400, f"节点类型仅支持：{'、'.join(local_nodes.NODE_TYPES)}")
    try:
        params = local_nodes.normalize_params(body.protocol, body.params)
        local_nodes.parse_extra(body.extra_yaml)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return params, body.extra_yaml


class EnabledBody(BaseModel):
    enabled: bool


@router.get("/schema")
def node_schema(user=CurrentUser):
    return {
        "protocols": local_nodes.protocol_schema(),
        "node_types": local_nodes.NODE_TYPES,
        "default_node_type": local_nodes.DEFAULT_NODE_TYPE,
    }


@router.get("")
def list_nodes(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM local_nodes ORDER BY sort, id")
    return [_public(r) for r in rows]


@router.post("", status_code=201)
def create_node(body: LocalNodeBody, user=CurrentUser):
    params, extra_yaml = _prepare(body)
    marked = local_nodes.display_name(body.name.strip(), body.node_type)
    with db.tx() as conn:
        if db.one(conn, "SELECT id FROM local_nodes WHERE name=?", (body.name.strip(),)):
            raise HTTPException(409, "同名本地节点已存在")
        if db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (marked,)):
            raise HTTPException(409, "本地节点名称与策略组重名，请换一个名称")
        now = db.now()
        sort = db.one(
            conn, "SELECT COALESCE(MAX(sort), 0) + 1 AS n FROM local_nodes")["n"]
        cur = conn.execute(
            "INSERT INTO local_nodes(name, node_type, protocol, server, port, "
            "params_enc, extra_yaml_enc, enabled, sort, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (body.name.strip(), (body.node_type or "").strip(), body.protocol,
             body.server.strip(), body.port,
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
    marked = local_nodes.display_name(body.name.strip(), body.node_type)
    with db.tx() as conn:
        row = _get_or_404(conn, node_id)
        clash = db.one(
            conn, "SELECT id FROM local_nodes WHERE name=? AND id!=?",
            (body.name.strip(), node_id),
        )
        if clash:
            raise HTTPException(409, "同名本地节点已存在")
        if db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (marked,)):
            raise HTTPException(409, "本地节点名称与策略组重名，请换一个名称")
        conn.execute(
            "UPDATE local_nodes SET name=?, node_type=?, protocol=?, server=?, "
            "port=?, params_enc=?, extra_yaml_enc=?, enabled=?, updated_at=? "
            "WHERE id=?",
            (body.name.strip(), (body.node_type or "").strip(), body.protocol,
             body.server.strip(), body.port,
             security.encrypt_text(json.dumps(params, ensure_ascii=False)),
             security.encrypt_text(extra_yaml), int(body.enabled), db.now(),
             node_id),
        )
        security.audit(conn, user["username"], "更新本地节点", "local_node", node_id,
                       {"name": body.name, "protocol": body.protocol})
        row = _get_or_404(conn, node_id)
    return _public(row)


@router.post("/{node_id}/test")
def test_node(node_id: int, user=CurrentUser):
    """测速：经该节点请求 generate_204，记录最近一次结果。

    与订阅来源的测速同机制（Mihomo 核心 + delay 接口），
    衡量的是从本服务器出发的连通性与延迟。
    """
    with db.connect() as conn:
        row = _get_or_404(conn, node_id)
    node = {
        # 这里给原始名称：render_proxy 自己会拼上「(类型)」
        "name": row["name"],
        "node_type": row["node_type"] or "",
        "protocol": row["protocol"],
        "server": row["server"],
        "port": row["port"],
        "params": json.loads(_decrypt(row["params_enc"]) or "{}"),
        "extra_yaml": _decrypt(row["extra_yaml_enc"]),
    }
    try:
        # 测速用 Mihomo 方言渲染（与批量测速的节点集合一致）
        proxy = local_nodes.render_proxy(node, "mihomo")
        result = tester.test_proxy(proxy)
    except tester.TestError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"测速失败：{exc}")
    now = db.now()
    with db.tx() as conn:
        conn.execute(
            "UPDATE local_nodes SET test_status=?, test_delay=?, tested_at=? "
            "WHERE id=?",
            ("ok" if result["ok"] else "failed",
             max(0, int(result["delay"])), now, node_id))
        security.audit(conn, user["username"], "本地节点测速", "local_node",
                       node_id, {"name": row["name"], "ok": result["ok"],
                                 "delay": result["delay"]})
    return {
        "id": node_id,
        "ok": result["ok"],
        "delay": max(0, int(result["delay"])) if result["ok"] else 0,
        "status": "ok" if result["ok"] else "failed",
        "tested_at": now,
    }


@router.patch("/{node_id}/enabled")
def set_node_enabled(node_id: int, body: EnabledBody, user=CurrentUser):
    """启停本地节点：只改启用状态，其它字段一个都不动。"""
    with db.tx() as conn:
        row = _get_or_404(conn, node_id)
        conn.execute("UPDATE local_nodes SET enabled=?, updated_at=? WHERE id=?",
                     (int(body.enabled), db.now(), node_id))
        security.audit(
            conn, user["username"],
            "启用本地节点" if body.enabled else "停用本地节点",
            "local_node", node_id, {"name": row["name"]})
        row = _get_or_404(conn, node_id)
    return _public(row)


@router.delete("/{node_id}")
def delete_node(node_id: int, force: bool = False, user=CurrentUser):
    """删除本地节点。

    仍被策略组引用时默认拒绝并返回引用明细（前端弹二次确认）；
    带 force=1 时自动把这些策略组里的引用摘掉再删除。
    """
    with db.tx() as conn:
        row = _get_or_404(conn, node_id)
        used_by = refs.local_node_refs(conn, node_id)
        if used_by and not force:
            raise HTTPException(409, detail={
                "code": "local_node_in_use",
                "message": f"本地节点“{row['name']}”仍被 {len(used_by)} 个策略组引用",
                "node": {"id": node_id, "name": row["name"]},
                "references": used_by,
            })
        detached, warnings = (refs.detach_local_node(conn, node_id)
                              if used_by else ([], []))
        conn.execute("DELETE FROM local_nodes WHERE id=?", (node_id,))
        security.audit(conn, user["username"], "删除本地节点", "local_node", node_id,
                       {"name": row["name"], "detached_groups": detached})
    return {"ok": True, "detached_groups": detached, "warnings": warnings}
