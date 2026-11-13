"""分流方案：策略组与分流规则的多套管理。

一个方案 = 一套完整、独立的策略组 + 分流规则副本；默认方案（id=0）
是迁移播种的系统方案，行为与历史版本完全一致。方案之间互不影响，
节点（本地节点 / 节点来源）、规则来源、基础配置等仍全局共享。

守卫口径与约束 35（AGENTS.md）一致：停用 ≠ 删除；删除或改名被当前
生产产物引用的方案时返回 409（产物文件名里带着方案名，客户端拿着
`?variant=` 地址会持续来取）。
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..deps import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["variants"])

# 复制方案时组/规则携带的全部列（不含 id 与 variant_id，复制时重写）
_GROUP_COLUMNS = (
    "name", "type", "sort", "hidden", "filter", "use_sources", "local_nodes",
    "proxies", "url", "interval", "timeout", "tolerance", "lazy", "strategy",
    "local_first", "targets", "devices",
)
_RULE_COLUMNS = (
    "sort", "type", "value", "target", "enabled", "note", "no_resolve",
    "no_track", "pre_matching", "targets", "devices",
)


class VariantBody(BaseModel):
    name: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=256)
    # 新建时可整体复制某个方案的组与规则作为起点
    copy_from: int | None = None
    # 复制时清空所有组的节点来源引用（「只用本地节点」类方案用）
    use_sources_empty: bool = False


class VariantPatch(BaseModel):
    name: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "方案名称不能为空")
    if len(name) > 32:
        raise HTTPException(400, "方案名称最长 32 个字符")
    bad = sorted(set(name) & config.VARIANT_NAME_FORBIDDEN)
    if bad:
        raise HTTPException(400, f"方案名称不能包含字符：{' '.join(bad)}")
    if any(ord(c) < 32 for c in name):
        raise HTTPException(400, "方案名称不能包含控制字符")
    return name


def _get_variant(conn, vid: int):
    row = db.one(conn, "SELECT * FROM variants WHERE id=?", (vid,))
    if not row:
        raise HTTPException(404, "方案不存在")
    return row


def _variant_public(row) -> dict:
    data = db.row_to_dict(row)
    data["enabled"] = bool(row["enabled"])
    data["is_system"] = bool(row["is_system"])
    return data


def _live_build_results(conn) -> dict:
    """当前生产 / 测试构建的 results 并集（键 = 产物名）。

    测试环境的设备同样可能拿着 `?variant=` 地址在拉取，
    所以删除 / 改名守卫两个环境都查。
    """
    out: dict = {}
    for status in ("PRODUCTION", "TESTING"):
        row = db.one(conn, "SELECT results FROM builds WHERE status=? LIMIT 1",
                     (status,))
        if not row:
            continue
        try:
            data = json.loads(row["results"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            out.update(data)
    return out


def _variant_artifact_refs(conn, name: str) -> list[str]:
    """当前生产产物里属于该方案的产物名。"""
    suffix = f"@{name}"
    return [key for key in _live_build_results(conn)
            if isinstance(key, str) and key.endswith(suffix)]


def _copy_variant_rows(conn, src: int, dst: int,
                       use_sources_empty: bool) -> tuple[int, int]:
    """复制方案的组与规则；sort 按方案的分段偏移（方案 N 占 N*10000 段）。"""
    offset = dst * config.VARIANT_SORT_STRIDE
    stamp = db.now()
    group_count = 0
    for g in db.all_(conn, "SELECT * FROM proxy_groups WHERE variant_id=? "
                           "ORDER BY sort, id", (src,)):
        use_sources = json.loads(g["use_sources"] or "[]")
        if use_sources_empty:
            use_sources = []
        conn.execute(
            "INSERT INTO proxy_groups(variant_id, name, type, sort, hidden, filter, "
            "use_sources, local_nodes, proxies, url, interval, timeout, tolerance, "
            "lazy, strategy, local_first, targets, devices, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dst, g["name"], g["type"], g["sort"] + offset, g["hidden"], g["filter"],
             json.dumps(use_sources, ensure_ascii=False), g["local_nodes"],
             g["proxies"], g["url"], g["interval"], g["timeout"], g["tolerance"],
             g["lazy"], g["strategy"], g["local_first"], g["targets"], g["devices"],
             stamp, stamp),
        )
        group_count += 1
    rule_count = 0
    for r in db.all_(conn, "SELECT * FROM rules WHERE variant_id=? "
                           "ORDER BY sort, id", (src,)):
        conn.execute(
            "INSERT INTO rules(variant_id, sort, type, value, target, enabled, note, "
            "no_resolve, no_track, pre_matching, targets, devices, created_at, "
            "updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dst, r["sort"] + offset, r["type"], r["value"], r["target"],
             r["enabled"], r["note"], r["no_resolve"], r["no_track"],
             r["pre_matching"], r["targets"], r["devices"], stamp, stamp),
        )
        rule_count += 1
    return group_count, rule_count


@router.get("/variants")
def list_variants(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn,
            "SELECT v.*, "
            "(SELECT COUNT(*) FROM proxy_groups g WHERE g.variant_id=v.id) AS groups_count, "
            "(SELECT COUNT(*) FROM rules r WHERE r.variant_id=v.id) AS rules_count "
            "FROM variants v ORDER BY v.sort, v.id")
    return [_variant_public(r) for r in rows]


@router.post("/variants", status_code=201)
def create_variant(body: VariantBody, user=CurrentUser):
    name = _check_name(body.name)
    try:
        with db.tx() as conn:
            if db.one(conn, "SELECT id FROM variants WHERE name=?", (name,)):
                raise HTTPException(409, "同名方案已存在")
            source = None
            if body.copy_from is not None:
                source = _get_variant(conn, int(body.copy_from))
            sort = (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s "
                                 "FROM variants WHERE id != 0"))["s"]
            stamp = db.now()
            cur = conn.execute(
                "INSERT INTO variants(name, note, enabled, is_system, sort, "
                "created_at, updated_at) VALUES(?,?,1,0,?,?,?)",
                (name, body.note, sort, stamp, stamp),
            )
            vid = cur.lastrowid
            copied = (0, 0)
            if source is not None:
                copied = _copy_variant_rows(conn, source["id"], vid,
                                            body.use_sources_empty)
            security.audit(conn, user["username"], "新增分流方案", "variant", vid,
                           {"name": name, "copy_from": source["name"] if source else "",
                            "copied_groups": copied[0], "copied_rules": copied[1]})
            row = _get_variant(conn, vid)
    except db.UniqueViolation:
        raise HTTPException(409, "同名方案已存在")
    return _variant_public(row)


@router.put("/variants/{vid}")
def update_variant(vid: int, body: VariantPatch, user=CurrentUser):
    with db.tx() as conn:
        row = _get_variant(conn, vid)
        name = row["name"]
        if body.name is not None and body.name.strip() != row["name"]:
            if row["is_system"]:
                raise HTTPException(400, "默认方案不能改名")
            name = _check_name(body.name)
            if db.one(conn, "SELECT id FROM variants WHERE name=? AND id!=?",
                      (name, vid)):
                raise HTTPException(409, "同名方案已存在")
            if refs := _variant_artifact_refs(conn, row["name"]):
                raise HTTPException(409, detail={
                    "code": "variant_in_use",
                    "message": f"方案“{row['name']}”的产物仍被当前生产版本引用，"
                               "请先发布新版本再改名",
                    "references": [{"artifact": a, "type": "构建产物"} for a in refs],
                })
        enabled = row["enabled"]
        if body.enabled is not None:
            if row["is_system"] and not body.enabled:
                raise HTTPException(400, "默认方案不能停用")
            enabled = int(body.enabled)
        note = body.note if body.note is not None else row["note"]
        conn.execute("UPDATE variants SET name=?, note=?, enabled=?, updated_at=? "
                     "WHERE id=?", (name, note, enabled, db.now(), vid))
        security.audit(conn, user["username"], "更新分流方案", "variant", vid,
                       {"name": name, "enabled": bool(enabled)})
        row = _get_variant(conn, vid)
    return _variant_public(row)


@router.delete("/variants/{vid}")
def delete_variant(vid: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_variant(conn, vid)
        if row["is_system"]:
            raise HTTPException(400, "默认方案不能删除")
        if refs := _variant_artifact_refs(conn, row["name"]):
            raise HTTPException(409, detail={
                "code": "variant_in_use",
                "message": f"方案“{row['name']}”的产物仍被当前生产版本引用，"
                           "请先发布新版本再删除",
                "references": [{"artifact": a, "type": "构建产物"} for a in refs],
            })
        conn.execute("DELETE FROM proxy_groups WHERE variant_id=?", (vid,))
        conn.execute("DELETE FROM rules WHERE variant_id=?", (vid,))
        conn.execute("DELETE FROM variants WHERE id=?", (vid,))
        security.audit(conn, user["username"], "删除分流方案", "variant", vid,
                       {"name": row["name"]})
    return {"ok": True}


@router.post("/variants/reorder")
def reorder_variants(ids: list[int], user=CurrentUser):
    """方案列表整体拖拽（列表小、不分页，按提交顺序全量重排）。"""
    with db.tx() as conn:
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "排序列表里有重复项")
        known = {r["id"] for r in db.all_(conn, "SELECT id FROM variants")}
        if any(i not in known for i in ids):
            raise HTTPException(400, "排序列表包含不存在的方案")
        for index, vid in enumerate(ids):
            conn.execute("UPDATE variants SET sort=?, updated_at=? WHERE id=?",
                         (index, db.now(), vid))
        security.audit(conn, user["username"], "调整分流方案顺序", "variant", "")
    return {"ok": True}
