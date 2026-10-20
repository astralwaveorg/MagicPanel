"""功能模块：脚本、复写、面板等按引擎归类的配置片段。

内容为 YAML 映射片段，构建时按引擎合并进目标配置：
字典递归合并、列表追加、标量覆盖，目标扩展（extra_yaml）最后应用。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import yaml

from .. import db, security
from ..deps import CurrentUser
from ..services import base_config as base_config_service

PROTECTED_KEYS = base_config_service.PROTECTED_KEYS

router = APIRouter(prefix="/api/v1/snippets", tags=["snippets"])

CATEGORIES = {"script", "rewrite", "panel", "dns", "general"}
ENGINES = {"stash", "mihomo", "all"}


class SnippetBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    category: str = "general"
    engine: str = "all"
    content: str = Field(min_length=1, max_length=100_000)
    enabled: bool = True
    sort: int = 0
    note: str = Field(default="", max_length=256)


def _check(body: SnippetBody) -> None:
    if body.category not in CATEGORIES:
        raise HTTPException(400, "分类仅支持：script / rewrite / panel / dns / general")
    if body.engine not in ENGINES:
        raise HTTPException(400, "适用引擎仅支持：stash / mihomo / all")
    try:
        fragment = yaml.safe_load(body.content)
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"内容不是合法 YAML：{exc}")
    if not isinstance(fragment, dict) or not fragment:
        raise HTTPException(400, "内容必须是非空的 YAML 映射（键值结构）")
    # 功能模块的列表是"追加"语义，写结构键会造出重名节点/组、
    # 或把规则追加到兜底规则之后（永不生效）。
    for key, reason in PROTECTED_KEYS.items():
        if key in fragment:
            raise HTTPException(400, f"功能模块不能包含“{key}”：{reason}")


def _get(conn, sid: int):
    row = db.one(conn, "SELECT * FROM snippets WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "功能模块不存在")
    return row


@router.get("")
def list_snippets(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM snippets ORDER BY sort, id")
    return [db.row_to_dict(r) for r in rows]


@router.post("", status_code=201)
def create_snippet(body: SnippetBody, user=CurrentUser):
    _check(body)
    with db.tx() as conn:
        if db.one(conn, "SELECT id FROM snippets WHERE name=?", (body.name,)):
            raise HTTPException(409, "同名功能模块已存在")
        now = db.now()
        cur = conn.execute(
            "INSERT INTO snippets(name, category, engine, content, enabled, sort, "
            "note, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (body.name, body.category, body.engine, body.content,
             int(body.enabled), body.sort, body.note, now, now),
        )
        security.audit(conn, user["username"], "新增功能模块", "snippet",
                       cur.lastrowid, {"name": body.name, "category": body.category})
        row = _get(conn, cur.lastrowid)
    return db.row_to_dict(row)


@router.put("/{sid}")
def update_snippet(sid: int, body: SnippetBody, user=CurrentUser):
    _check(body)
    with db.tx() as conn:
        _get(conn, sid)
        clash = db.one(
            conn, "SELECT id FROM snippets WHERE name=? AND id!=?", (body.name, sid)
        )
        if clash:
            raise HTTPException(409, "同名功能模块已存在")
        conn.execute(
            "UPDATE snippets SET name=?, category=?, engine=?, content=?, enabled=?, "
            "sort=?, note=?, updated_at=? WHERE id=?",
            (body.name, body.category, body.engine, body.content, int(body.enabled),
             body.sort, body.note, db.now(), sid),
        )
        security.audit(conn, user["username"], "更新功能模块", "snippet", sid,
                       {"name": body.name, "category": body.category})
        row = _get(conn, sid)
    return db.row_to_dict(row)


@router.delete("/{sid}")
def delete_snippet(sid: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get(conn, sid)
        conn.execute("DELETE FROM snippets WHERE id=?", (sid,))
        security.audit(conn, user["username"], "删除功能模块", "snippet", sid,
                       {"name": row["name"]})
    return {"ok": True}
