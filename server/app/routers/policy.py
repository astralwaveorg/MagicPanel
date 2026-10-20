"""策略组与分流规则。"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..deps import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["policy"])


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = "select"
    hidden: bool = False
    filter: str = Field(default="", max_length=512)
    use_sources: list[str] = Field(default_factory=list)
    local_nodes: list[int] = Field(default_factory=list)
    proxies: list[str] = Field(default_factory=list)
    url: str = Field(default="https://www.gstatic.com/generate_204", max_length=256)
    interval: int = Field(default=600, ge=30, le=86400)
    timeout: int = Field(default=8000, ge=100, le=60000)
    tolerance: int = Field(default=150, ge=0, le=5000)
    lazy: bool = True
    strategy: str = Field(default="", max_length=32)
    targets: list[str] = Field(default_factory=list)  # 适用引擎平台，空 = 全部


class RuleBody(BaseModel):
    type: str
    value: str = Field(default="", max_length=512)
    target: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    note: str = Field(default="", max_length=256)
    no_resolve: bool = False
    targets: list[str] = Field(default_factory=list)  # 适用引擎平台，空 = 全部


def _group_public(row) -> dict:
    data = db.row_to_dict(row)
    data["hidden"] = bool(row["hidden"])
    data["lazy"] = bool(row["lazy"])
    data["use_sources"] = json.loads(row["use_sources"] or "[]")
    data["local_nodes"] = json.loads(row["local_nodes"] or "[]")
    data["proxies"] = json.loads(row["proxies"] or "[]")
    data["targets"] = json.loads(row["targets"] or "[]")
    return data


def _rule_public(row) -> dict:
    data = db.row_to_dict(row)
    data["enabled"] = bool(row["enabled"])
    data["no_resolve"] = bool(row["no_resolve"])
    data["targets"] = json.loads(row["targets"] or "[]")
    return data


def _check_group(body: GroupBody) -> None:
    if body.type not in config.GROUP_TYPES:
        raise HTTPException(400, f"策略组类型仅支持：{'、'.join(sorted(config.GROUP_TYPES))}")
    if body.strategy:
        if body.type != "load-balance":
            raise HTTPException(400, "分配策略仅用于 load-balance 类型")
        if body.strategy not in config.LB_STRATEGIES:
            raise HTTPException(400, f"分配策略仅支持：{'、'.join(sorted(config.LB_STRATEGIES))}")
    if body.type == "relay":
        # 链式转发顺序必须固定，不能用节点来源或过滤动态生成
        if body.use_sources or body.filter:
            raise HTTPException(400, "relay 为链式转发，仅支持固定成员，不能用节点来源或过滤")
        if len(body.proxies) + len(body.local_nodes) < 2:
            raise HTTPException(400, "relay 至少需要两个成员组成转发链")
    if body.filter:
        try:
            re.compile(body.filter)
        except re.error as exc:
            raise HTTPException(400, f"过滤正则无效：{exc}")


def _check_local_ids(conn, ids: list[int]) -> list[int]:
    unique = list(dict.fromkeys(ids))
    existing = {r["id"] for r in db.all_(conn, "SELECT id FROM local_nodes")}
    missing = [i for i in unique if i not in existing]
    if missing:
        raise HTTPException(400, f"本地节点不存在：{'、'.join(f'#{i}' for i in missing)}")
    return unique


def _get_group(conn, gid: int):
    row = db.one(conn, "SELECT * FROM proxy_groups WHERE id=?", (gid,))
    if not row:
        raise HTTPException(404, "策略组不存在")
    return row


@router.get("/groups/page")
def list_groups_paged(limit: int = 50, offset: int = 0, keyword: str = "",
                      user=CurrentUser):
    """策略组分页列表（keyword 匹配名称）。"""
    with db.connect() as conn:
        where, args = "", []
        if keyword:
            where = "WHERE name LIKE ?"
            args = [f"%{keyword}%"]
        data = db.paged(conn, "proxy_groups", where, args, "sort, id", limit, offset)
    data["items"] = [_group_public(r) for r in data["items"]]
    return data


@router.get("/groups")
def list_groups(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM proxy_groups ORDER BY sort, id")
    return [_group_public(r) for r in rows]


@router.post("/groups", status_code=201)
def create_group(body: GroupBody, user=CurrentUser):
    _check_group(body)
    try:
        with db.tx() as conn:
            if db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (body.name,)):
                raise HTTPException(409, "同名策略组已存在")
            _check_group_refs(conn, body)
            local_ids = _check_local_ids(conn, body.local_nodes)
            sort = (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM proxy_groups"))["s"]
            now = db.now()
            cur = db.insert_unique(conn,
                "INSERT INTO proxy_groups(name, type, sort, hidden, filter, use_sources, "
                "local_nodes, proxies, url, interval, timeout, tolerance, lazy, strategy, "
                "targets, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (body.name, body.type, sort, int(body.hidden), body.filter,
                 json.dumps(body.use_sources, ensure_ascii=False),
                 json.dumps(local_ids, ensure_ascii=False),
                 json.dumps(body.proxies, ensure_ascii=False),
                 body.url, body.interval, body.timeout, body.tolerance,
                 int(body.lazy), body.strategy,
                 json.dumps(body.targets, ensure_ascii=False), now, now),
            )
            security.audit(conn, user["username"], "新增策略组", "group", cur.lastrowid,
                           {"name": body.name})
            row = _get_group(conn, cur.lastrowid)
    except db.UniqueViolation:
        raise HTTPException(409, "同名策略组已存在")

    return _group_public(row)


@router.put("/groups/{gid}")
def update_group(gid: int, body: GroupBody, user=CurrentUser):
    _check_group(body)
    with db.tx() as conn:
        current = _get_group(conn, gid)
        clash = db.one(
            conn, "SELECT id FROM proxy_groups WHERE name=? AND id!=?", (body.name, gid)
        )
        if clash:
            raise HTTPException(409, "同名策略组已存在")
        _check_group_refs(conn, body)
        local_ids = _check_local_ids(conn, body.local_nodes)
        # 改名时同步改写引用（规则目标 + 其它组的成员列表），
        # 否则引用会指向不存在的组，构建全线失败且无法发布。
        if current["name"] != body.name:
            _remap_group_refs(conn, current["name"], body.name)
        conn.execute(
            "UPDATE proxy_groups SET name=?, type=?, hidden=?, filter=?, use_sources=?, "
            "local_nodes=?, proxies=?, url=?, interval=?, timeout=?, tolerance=?, "
            "lazy=?, strategy=?, targets=?, updated_at=? WHERE id=?",
            (body.name, body.type, int(body.hidden), body.filter,
             json.dumps(body.use_sources, ensure_ascii=False),
             json.dumps(local_ids, ensure_ascii=False),
             json.dumps(body.proxies, ensure_ascii=False),
             body.url, body.interval, body.timeout, body.tolerance, int(body.lazy),
             body.strategy, json.dumps(body.targets, ensure_ascii=False),
             db.now(), gid),
        )
        security.audit(conn, user["username"], "更新策略组", "group", gid,
                       {"name": body.name})
        row = _get_group(conn, gid)
    return _group_public(row)


@router.delete("/groups/{gid}")
def delete_group(gid: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_group(conn, gid)
        refs = [
            g["name"] for g in db.all_(conn, "SELECT name, proxies FROM proxy_groups")
            if row["name"] in json.loads(g["proxies"] or "[]")
        ]
        if refs:
            raise HTTPException(400, f"策略组仍被引用：{'、'.join(refs)}")
        used = db.one(
            conn, "SELECT COUNT(*) AS c FROM rules WHERE target=?", (row["name"],)
        )["c"]
        if used:
            raise HTTPException(400, f"仍有 {used} 条分流规则指向该策略组")
        conn.execute("DELETE FROM proxy_groups WHERE id=?", (gid,))
        security.audit(conn, user["username"], "删除策略组", "group", gid,
                       {"name": row["name"]})
    return {"ok": True}


@router.post("/groups/reorder")
def reorder_groups(ids: list[int], user=CurrentUser):
    """列表已分页：按提交的这些 id 重排（它们之间按新顺序，其余记录不动）。"""
    with db.tx() as conn:
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "排序列表里有重复项")
        known = {r["id"] for r in db.all_(conn, "SELECT id FROM proxy_groups")}
        if any(i not in known for i in ids):
            raise HTTPException(400, "排序列表包含不存在的记录")
        if not db.reorder_subset(conn, "proxy_groups", ids):
            raise HTTPException(400, "排序未生效")
        security.audit(conn, user["username"], "调整策略组顺序", "group", "")
    return {"ok": True}


# ---- 分流规则 ----

def _get_rule(conn, rid: int):
    row = db.one(conn, "SELECT * FROM rules WHERE id=?", (rid,))
    if not row:
        raise HTTPException(404, "分流规则不存在")
    return row


def _check_rule(body: RuleBody) -> None:
    if body.type not in config.RULE_TYPES:
        raise HTTPException(400, f"不支持的规则类型：{body.type}")
    if body.type not in ("MATCH", "FINAL") and not body.value:
        raise HTTPException(400, "该规则类型需要填写匹配值")
    if body.no_resolve and body.type not in config.NO_RESOLVE_TYPES:
        raise HTTPException(400, "no-resolve 仅适用于 IP 类规则（IP-CIDR / GEOIP / RULE-SET 等）")


def _remap_group_refs(conn, old_name: str, new_name: str) -> int:
    """策略组改名后，同步更新规则目标与其它组的成员列表。"""
    changed = 0
    for row in db.all_(conn, "SELECT id, target FROM rules WHERE target=?", (old_name,)):
        conn.execute("UPDATE rules SET target=? WHERE id=?", (new_name, row["id"]))
        changed += 1
    for row in db.all_(conn, "SELECT id, proxies FROM proxy_groups WHERE proxies IS NOT NULL"):
        try:
            members = json.loads(row["proxies"] or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(members, list) or old_name not in members:
            continue
        members = [new_name if m == old_name else m for m in members]
        conn.execute("UPDATE proxy_groups SET proxies=? WHERE id=?",
                     (json.dumps(members, ensure_ascii=False), row["id"]))
        changed += 1
    return changed


def _check_target_names(conn, names: list[str]) -> None:
    """写时校验"适用引擎平台"必须真实存在。

    这一项必须硬校验：平台名写错时，策略组与规则会被**所有产物静默剔除**，
    界面与构建日志都看不出任何异常。
    策略组之间的相互引用不在这里校验——建组顺序本来就是任意的，
    引用写错由构建期给出明确报错（"引用了不存在的策略组"）。
    """
    for name in names or []:
        row = db.one(conn, "SELECT id FROM targets WHERE name=?", (name,))
        if not row:
            raise HTTPException(400, f"引擎平台“{name}”不存在")


def _check_rule_refs(conn, body: RuleBody) -> None:
    _check_target_names(conn, body.targets)


def _check_group_refs(conn, body: GroupBody) -> None:
    _check_target_names(conn, body.targets)


@router.get("/rules/page")
def list_rules_paged(limit: int = 50, offset: int = 0, keyword: str = "",
                     user=CurrentUser):
    """分流规则分页列表（keyword 匹配匹配值或目标）。"""
    with db.connect() as conn:
        where, args = "", []
        if keyword:
            where = "WHERE value LIKE ? OR target LIKE ?"
            args = [f"%{keyword}%", f"%{keyword}%"]
        data = db.paged(conn, "rules", where, args, "sort, id", limit, offset)
    data["items"] = [_rule_public(r) for r in data["items"]]
    return data


@router.get("/rules")
def list_rules(user=CurrentUser):
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM rules ORDER BY sort, id")
    return [_rule_public(r) for r in rows]


@router.post("/rules", status_code=201)
def create_rule(body: RuleBody, user=CurrentUser):
    _check_rule(body)
    try:
        with db.tx() as conn:
            _check_rule_refs(conn, body)
            sort = (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM rules"))["s"]
            now = db.now()
            cur = db.insert_unique(conn,
                "INSERT INTO rules(sort, type, value, target, enabled, note, no_resolve, "
                "targets, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sort, body.type, body.value, body.target, int(body.enabled),
                 body.note, int(body.no_resolve),
                 json.dumps(body.targets, ensure_ascii=False), now, now),
            )
            security.audit(conn, user["username"], "新增分流规则", "rule", cur.lastrowid,
                           {"rule": f"{body.type},{body.value},{body.target}"})
            row = _get_rule(conn, cur.lastrowid)
    except db.UniqueViolation:
        raise HTTPException(409, "同名规则已存在")

    return _rule_public(row)


@router.put("/rules/{rid}")
def update_rule(rid: int, body: RuleBody, user=CurrentUser):
    _check_rule(body)
    with db.tx() as conn:
        _check_rule_refs(conn, body)
        _get_rule(conn, rid)
        conn.execute(
            "UPDATE rules SET type=?, value=?, target=?, enabled=?, note=?, "
            "no_resolve=?, targets=?, updated_at=? WHERE id=?",
            (body.type, body.value, body.target, int(body.enabled), body.note,
             int(body.no_resolve), json.dumps(body.targets, ensure_ascii=False),
             db.now(), rid),
        )
        security.audit(conn, user["username"], "更新分流规则", "rule", rid,
                       {"rule": f"{body.type},{body.value},{body.target}"})
        row = _get_rule(conn, rid)
    return _rule_public(row)


@router.delete("/rules/{rid}")
def delete_rule(rid: int, user=CurrentUser):
    with db.tx() as conn:
        row = _get_rule(conn, rid)
        conn.execute("DELETE FROM rules WHERE id=?", (rid,))
        security.audit(conn, user["username"], "删除分流规则", "rule", rid,
                       {"rule": f"{row['type']},{row['value']},{row['target']}"})
    return {"ok": True}


@router.post("/rules/reorder")
def reorder_rules(ids: list[int], user=CurrentUser):
    """列表已分页：按提交的这些 id 重排（它们之间按新顺序，其余记录不动）。"""
    with db.tx() as conn:
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "排序列表里有重复项")
        known = {r["id"] for r in db.all_(conn, "SELECT id FROM rules")}
        if any(i not in known for i in ids):
            raise HTTPException(400, "排序列表包含不存在的记录")
        if not db.reorder_subset(conn, "rules", ids):
            raise HTTPException(400, "排序未生效")
        security.audit(conn, user["username"], "调整分流规则顺序", "rule", "")
    return {"ok": True}
