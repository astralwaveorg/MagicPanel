"""策略组与分流规则。"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db, security
from ..deps import CurrentUser
from ..services import refs

router = APIRouter(prefix="/api/v1", tags=["policy"])


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = "select"
    hidden: bool = False
    filter: str = Field(default="", max_length=512)
    # 默认"包含所有"：不传就是全部（以后新增的来源自动包含）
    use_sources: list[str] = Field(default_factory=lambda: [config.ALL_SCOPE])
    local_nodes: list[int] = Field(default_factory=list)
    proxies: list[str] = Field(default_factory=list)
    url: str = Field(default="https://www.gstatic.com/generate_204", max_length=256)
    interval: int = Field(default=600, ge=30, le=86400)
    timeout: int = Field(default=8000, ge=100, le=60000)
    tolerance: int = Field(default=150, ge=0, le=5000)
    lazy: bool = True
    strategy: str = Field(default="", max_length=32)
    # 适用引擎平台 / 适用设备：默认"包含所有"，显式传空数组 = 不适用任何
    targets: list[str] = Field(default_factory=lambda: [config.ALL_SCOPE])
    devices: list[str] = Field(default_factory=lambda: [config.ALL_SCOPE])
    local_first: bool = False   # 本地单节点排在组成员最前


class RuleBody(BaseModel):
    type: str
    value: str = Field(default="", max_length=512)
    target: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    note: str = Field(default="", max_length=256)
    no_resolve: bool = False
    # 适用引擎平台 / 适用设备：默认"包含所有"，显式传空数组 = 不适用任何
    targets: list[str] = Field(default_factory=lambda: [config.ALL_SCOPE])
    devices: list[str] = Field(default_factory=lambda: [config.ALL_SCOPE])


def _group_public(row) -> dict:
    data = db.row_to_dict(row)
    data["hidden"] = bool(row["hidden"])
    data["lazy"] = bool(row["lazy"])
    data["use_sources"] = json.loads(row["use_sources"] or "[]")
    data["local_nodes"] = json.loads(row["local_nodes"] or "[]")
    data["proxies"] = json.loads(row["proxies"] or "[]")
    data["targets"] = json.loads(row["targets"] or "[]")
    data["devices"] = json.loads(row["devices"] or "[]") if "devices" in row.keys() else []
    data["local_first"] = bool(row["local_first"]) if "local_first" in row.keys() else False
    return data


def _rule_public(row) -> dict:
    data = db.row_to_dict(row)
    data["enabled"] = bool(row["enabled"])
    data["no_resolve"] = bool(row["no_resolve"])
    data["targets"] = json.loads(row["targets"] or "[]")
    data["devices"] = json.loads(row["devices"] or "[]") if "devices" in row.keys() else []
    data["local_first"] = bool(row["local_first"]) if "local_first" in row.keys() else False
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
        # （"包含所有"是默认值，不算真的用了节点来源）
        uses = [u for u in (body.use_sources or []) if u != config.ALL_SCOPE]
        if uses or body.filter:
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
            body.use_sources = _collapse_if_complete(conn, body.use_sources, "sources")
            body.targets = _collapse_if_complete(conn, body.targets, "targets")
            body.devices = _collapse_if_complete(conn, body.devices, "devices")
            if body.type == "relay":
                body.use_sources = []
            local_ids = _check_local_ids(conn, body.local_nodes)
            sort = (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM proxy_groups"))["s"]
            now = db.now()
            cur = db.insert_unique(conn,
                "INSERT INTO proxy_groups(name, type, sort, hidden, filter, use_sources, "
                "local_nodes, proxies, url, interval, timeout, tolerance, lazy, strategy, "
                "targets, devices, local_first, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (body.name, body.type, sort, int(body.hidden), body.filter,
                 json.dumps(body.use_sources, ensure_ascii=False),
                 json.dumps(local_ids, ensure_ascii=False),
                 json.dumps(body.proxies, ensure_ascii=False),
                 body.url, body.interval, body.timeout, body.tolerance,
                 int(body.lazy), body.strategy,
                 json.dumps(body.targets, ensure_ascii=False),
                 json.dumps(body.devices, ensure_ascii=False), int(body.local_first),
                 now, now),
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
        body.use_sources = _collapse_if_complete(conn, body.use_sources, "sources")
        body.targets = _collapse_if_complete(conn, body.targets, "targets")
        body.devices = _collapse_if_complete(conn, body.devices, "devices")
        if body.type == "relay":
            body.use_sources = []
        local_ids = _check_local_ids(conn, body.local_nodes)
        # 改名时同步改写引用（规则目标 + 其它组的成员列表），
        # 否则引用会指向不存在的组，构建全线失败且无法发布。
        if current["name"] != body.name:
            _remap_group_refs(conn, current["name"], body.name)
        conn.execute(
            "UPDATE proxy_groups SET name=?, type=?, hidden=?, filter=?, use_sources=?, "
            "local_nodes=?, proxies=?, url=?, interval=?, timeout=?, tolerance=?, "
            "lazy=?, strategy=?, targets=?, devices=?, local_first=?, updated_at=? WHERE id=?",
            (body.name, body.type, int(body.hidden), body.filter,
             json.dumps(body.use_sources, ensure_ascii=False),
             json.dumps(local_ids, ensure_ascii=False),
             json.dumps(body.proxies, ensure_ascii=False),
             body.url, body.interval, body.timeout, body.tolerance, int(body.lazy),
             body.strategy, json.dumps(body.targets, ensure_ascii=False),
             json.dumps(body.devices, ensure_ascii=False),
             int(body.local_first), db.now(), gid),
        )
        security.audit(conn, user["username"], "更新策略组", "group", gid,
                       {"name": body.name})
        row = _get_group(conn, gid)
    return _group_public(row)


@router.delete("/groups/{gid}")
def delete_group(gid: int, force: bool = False, user=CurrentUser):
    """删除策略组。

    被其它策略组当作成员、或被分流规则指向时默认拒绝，并返回引用明细
    （前端据此弹二次确认）；带 force=1 时自动解绑：把成员引用摘掉，
    并删除指向它的分流规则。
    """
    with db.tx() as conn:
        row = _get_group(conn, gid)
        members = refs.group_members(conn, row["name"])
        rules = refs.rules_targeting(conn, row["name"])
        if (members or rules) and not force:
            detail = []
            if members:
                detail.append(f"被 {len(members)} 个策略组当作成员")
            if rules:
                detail.append(f"被 {len(rules)} 条分流规则指向")
            raise HTTPException(409, detail={
                "code": "group_in_use",
                "message": f"策略组“{row['name']}”{'、'.join(detail)}",
                "group": {"id": gid, "name": row["name"]},
                "references": (
                    [{"id": m["id"], "name": m["name"], "type": "策略组",
                      "extra": f"{m['group_type']} 组，把它当作成员"} for m in members]
                    + [{"id": r["id"], "name": f"#{r['id']}", "type": "分流规则",
                        "extra": f"{r['type']} {r['value']} → {row['name']}"
                                 + ("（已停用）" if not r["enabled"] else "")}
                       for r in rules]
                ),
            })
        changed, removed, warns = refs.detach_group(conn, row["name"])
        conn.execute("DELETE FROM proxy_groups WHERE id=?", (gid,))
        security.audit(conn, user["username"], "删除策略组", "group", gid,
                       {"name": row["name"], "detached_groups": changed,
                        "removed_rules": [r["id"] for r in removed]})
    return {"ok": True, "detached_groups": changed,
            "removed_rules": removed, "warnings": warns}


# ---- 批量操作 ----

class BatchIds(BaseModel):
    ids: list[int] = Field(default_factory=list)
    force: bool = False


class BatchGroupPatch(BaseModel):
    """批量修改策略组。字段为 null 表示不修改；空列表表示清空。"""
    ids: list[int] = Field(default_factory=list)
    proxies: list[str] | None = None
    targets: list[str] | None = None
    local_nodes: list[int] | None = None
    use_sources: list[str] | None = None
    filter: str | None = None
    hidden: bool | None = None
    local_first: bool | None = None


class BatchRulePatch(BaseModel):
    """批量修改分流规则。字段为 null 表示不修改；空列表表示清空。"""
    ids: list[int] = Field(default_factory=list)
    target: str | None = None
    targets: list[str] | None = None
    devices: list[str] | None = None
    enabled: bool | None = None
    note: str | None = None
    no_resolve: bool | None = None


@router.patch("/groups/batch")
def batch_update_groups(body: BatchGroupPatch, user=CurrentUser):
    """批量修改策略组的共性配置。

    - 只改提交了的字段（null = 不改，空列表 = 清空）；
    - relay 组不支持"节点来源"，这类组会被跳过并在 skipped 里说明；
    - 引用了不存在策略组的成员会被剔除，避免产物加载失败。
    """
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(400, "请先选择要修改的策略组")
    if body.proxies is None and body.targets is None and body.local_nodes is None \
            and body.use_sources is None and body.filter is None \
            and body.hidden is None and body.local_first is None:
        raise HTTPException(400, "请至少选择一个要修改的字段")
    updated = 0
    skipped: list[dict] = []
    missing: list[int] = []
    with db.tx() as conn:
        group_names = {r["name"] for r in db.all_(conn, "SELECT name FROM proxy_groups")}
        source_names = {r["name"] for r in db.all_(conn, "SELECT name FROM sources")}
        local_ids = {int(r["id"]) for r in db.all_(
            conn, "SELECT id FROM local_nodes WHERE enabled=1")}
        target_names = {r["name"] for r in db.all_(conn, "SELECT name FROM targets")}
        for gid in ids:
            row = db.one(conn, "SELECT * FROM proxy_groups WHERE id=?", (gid,))
            if not row:
                missing.append(gid)
                continue
            fields: list[str] = []
            args: list = []
            notes: list[str] = []
            if body.proxies is not None:
                # 剔除不存在的成员，并剔除指向自己的引用（自引用客户端加载会失败）
                keep = [p for p in body.proxies
                        if (p in group_names and p != row["name"])
                        or p in config.BUILTIN_TARGETS]
                dropped = len(body.proxies) - len(keep)
                if dropped:
                    notes.append(f"剔除了 {dropped} 个不存在或指向自己的成员引用")
                fields.append("proxies=?")
                args.append(json.dumps(keep, ensure_ascii=False))
            if body.targets is not None:
                keep = [t for t in body.targets if t in target_names]
                if len(keep) != len(body.targets):
                    notes.append("剔除了不存在的引擎平台")
                fields.append("targets=?")
                args.append(json.dumps(keep, ensure_ascii=False))
            if body.local_nodes is not None:
                keep = [i for i in body.local_nodes if i in local_ids]
                if len(keep) != len(body.local_nodes):
                    notes.append("剔除了不存在或已停用的本地节点")
                fields.append("local_nodes=?")
                args.append(json.dumps(keep, ensure_ascii=False))
            if body.use_sources is not None:
                if row["type"] == "relay":
                    skipped.append({"id": gid, "name": row["name"],
                                    "reason": "relay 组不支持节点来源，已跳过该字段"})
                else:
                    keep = [s for s in body.use_sources
                            if s == config.ALL_SCOPE or s in source_names]
                    if len(keep) != len(body.use_sources):
                        notes.append("剔除了不存在的节点来源")
                    fields.append("use_sources=?")
                    args.append(json.dumps(keep, ensure_ascii=False))
            if body.filter is not None:
                fields.append("filter=?")
                args.append(body.filter.strip())
            if body.hidden is not None:
                fields.append("hidden=?")
                args.append(int(body.hidden))
            if body.local_first is not None:
                fields.append("local_first=?")
                args.append(int(body.local_first))
            if not fields:
                continue
            fields.append("updated_at=?")
            conn.execute(
                f"UPDATE proxy_groups SET {', '.join(fields)} WHERE id=?",
                (*args, db.now(), gid))
            updated += 1
            if notes:
                skipped.append({"id": gid, "name": row["name"],
                                "reason": "；".join(notes)})
        security.audit(conn, user["username"], "批量修改策略组", "group",
                       ",".join(str(i) for i in ids),
                       {"proxies": body.proxies, "targets": body.targets,
                        "local_nodes": body.local_nodes,
                        "use_sources": body.use_sources, "filter": body.filter,
                        "hidden": body.hidden})
    return {"ok": True, "updated": updated, "missing": missing, "skipped": skipped}


@router.post("/groups/batch/delete")
def batch_delete_groups(body: BatchIds, user=CurrentUser):
    """批量删除策略组。

    默认被其它组或规则引用的保留并返回引用明细；
    force=True 时自动解绑（摘掉成员引用、删除指向它的规则）后一并删除。
    """
    deleted: list[int] = []
    blocked: list[dict] = []
    removed_rules: list[dict] = []
    warnings: list[str] = []
    with db.tx() as conn:
        for gid in dict.fromkeys(body.ids):
            row = db.one(conn, "SELECT * FROM proxy_groups WHERE id=?", (gid,))
            if not row:
                blocked.append({"id": gid, "name": f"#{gid}",
                                "reason": "策略组不存在（可能已被删除）"})
                continue
            members = [m for m in refs.group_members(conn, row["name"])]
            rules = refs.rules_targeting(conn, row["name"])
            if (members or rules) and not body.force:
                blocked.append({
                    "id": gid, "name": row["name"],
                    "reason": "仍被引用"
                               + (f"（{len(members)} 个策略组把它当成员）" if members else "")
                               + (f"（{len(rules)} 条分流规则指向）" if rules else ""),
                    "references": (
                        [{"id": m["id"], "name": m["name"], "type": "策略组",
                          "extra": f"{m['group_type']} 组，把它当作成员"} for m in members]
                        + [{"id": r["id"], "name": f"#{r['id']}", "type": "分流规则",
                            "extra": f"{r['type']} {r['value']} → {row['name']}"}
                           for r in rules]
                    ),
                })
                continue
            changed, gone, warns = refs.detach_group(conn, row["name"])
            removed_rules.extend(gone)
            warnings.extend(warns)
            conn.execute("DELETE FROM proxy_groups WHERE id=?", (gid,))
            deleted.append(gid)
            security.audit(conn, user["username"], "批量删除策略组", "group", gid,
                           {"name": row["name"], "detached_groups": changed})
    return {"ok": True, "deleted": deleted, "blocked": blocked,
            "removed_rules": removed_rules, "warnings": warnings}


@router.patch("/rules/batch")
def batch_update_rules(body: BatchRulePatch, user=CurrentUser):
    """批量修改分流规则的共性配置（目标、适用平台、启用状态、备注、no-resolve）。"""
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(400, "请先选择要修改的分流规则")
    if body.target is None and body.targets is None and body.devices is None \
            and body.enabled is None and body.note is None and body.no_resolve is None:
        raise HTTPException(400, "请至少选择一个要修改的字段")
    updated = 0
    skipped: list[dict] = []
    missing: list[int] = []
    with db.tx() as conn:
        group_names = {r["name"] for r in db.all_(conn, "SELECT name FROM proxy_groups")}
        target_names = {r["name"] for r in db.all_(conn, "SELECT name FROM targets")}
        device_names = {r["name"] for r in db.all_(conn, "SELECT name FROM devices")}
        for rid in ids:
            row = db.one(conn, "SELECT * FROM rules WHERE id=?", (rid,))
            if not row:
                missing.append(rid)
                continue
            fields: list[str] = []
            args: list = []
            notes: list[str] = []
            if body.target is not None:
                if body.target not in group_names \
                        and body.target not in config.BUILTIN_TARGETS:
                    notes.append(f"目标“{body.target}”不存在，已跳过")
                else:
                    fields.append("target=?")
                    args.append(body.target)
            if body.targets is not None:
                keep = [t for t in body.targets if t in target_names]
                if len(keep) != len(body.targets):
                    notes.append("剔除了不存在的引擎平台")
                fields.append("targets=?")
                args.append(json.dumps(keep, ensure_ascii=False))
            if body.devices is not None:
                keep = [d for d in body.devices if d in device_names]
                if len(keep) != len(body.devices):
                    notes.append("剔除了不存在的设备")
                fields.append("devices=?")
                args.append(json.dumps(keep, ensure_ascii=False))
            if body.enabled is not None:
                fields.append("enabled=?")
                args.append(int(body.enabled))
            if body.note is not None:
                fields.append("note=?")
                args.append(body.note)
            if body.no_resolve is not None:
                fields.append("no_resolve=?")
                args.append(int(body.no_resolve))
            if not fields:
                if notes:
                    skipped.append({"id": rid,
                                    "name": f"{row['type']},{row['value'][:24]}",
                                    "reason": "；".join(notes)})
                continue
            fields.append("updated_at=?")
            conn.execute(
                f"UPDATE rules SET {', '.join(fields)} WHERE id=?",
                (*args, db.now(), rid))
            updated += 1
            if notes:
                skipped.append({"id": rid, "name": f"{row['type']},{row['value'][:24]}",
                                "reason": "；".join(notes)})
        security.audit(conn, user["username"], "批量修改分流规则", "rule",
                       ",".join(str(i) for i in ids),
                       {"target": body.target, "targets": body.targets,
                        "devices": body.devices,
                        "enabled": body.enabled, "note": body.note})
    return {"ok": True, "updated": updated, "missing": missing, "skipped": skipped}


@router.post("/rules/batch/delete")
def batch_delete_rules(body: BatchIds, user=CurrentUser):
    """批量删除分流规则：兜底规则（MATCH / FINAL）不删，删了设备就没有兜底了。"""
    deleted: list[int] = []
    blocked: list[dict] = []
    with db.tx() as conn:
        for rid in dict.fromkeys(body.ids):
            row = db.one(conn, "SELECT * FROM rules WHERE id=?", (rid,))
            if not row:
                blocked.append({"id": rid, "name": f"#{rid}",
                                "reason": "规则不存在（可能已被删除）"})
                continue
            if row["type"] in ("MATCH", "FINAL"):
                blocked.append({"id": rid,
                                "name": f"{row['type']},{row['value'][:24]}",
                                "reason": "兜底规则不能批量删除，请先新增另一条兜底规则"})
                continue
            conn.execute("DELETE FROM rules WHERE id=?", (rid,))
            deleted.append(rid)
            security.audit(conn, user["username"], "批量删除分流规则", "rule", rid,
                           {"rule": f"{row['type']},{row['value']}"})
    return {"ok": True, "deleted": deleted, "blocked": blocked}


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


def _check_device_names(conn, names: list[str]) -> None:
    """写时校验"适用设备"必须真实存在。

    设备名写错时，该条规则/策略组会被所有产物静默剔除——
    与引擎平台名写错的后果一样，必须在写入时挡下来。
    """
    for name in names or []:
        if name == config.ALL_SCOPE:
            continue
        row = db.one(conn, "SELECT id FROM devices WHERE name=?", (name,))
        if not row:
            raise HTTPException(400, f"设备不存在：{name}")


def _check_target_names(conn, names: list[str]) -> None:
    """写时校验"适用引擎平台"必须真实存在。

    这一项必须硬校验：平台名写错时，策略组与规则会被**所有产物静默剔除**，
    界面与构建日志都看不出任何异常。
    策略组之间的相互引用不在这里校验——建组顺序本来就是任意的，
    引用写错由构建期给出明确报错（"引用了不存在的策略组"）。
    """
    for name in names or []:
        if name == config.ALL_SCOPE:
            continue
        row = db.one(conn, "SELECT id FROM targets WHERE name=?", (name,))
        if not row:
            raise HTTPException(400, f"引擎平台“{name}”不存在")


def _check_rule_refs(conn, body: RuleBody) -> None:
    _check_target_names(conn, body.targets)
    _check_device_names(conn, body.devices)


# 兜底规则类型：命中即结束，其后的规则永远匹配不到
FALLBACK_TYPES = ("MATCH", "FINAL")


def _rule_insert_sort(conn, is_fallback: bool) -> int:
    """新规则的排序位。

    普通规则：插在兜底规则之前。客户端是"从上往下第一条命中即生效"，
    撞到兜底（MATCH/FINAL）就结束了，排在其后的规则永远匹配不到。

    兜底规则：追加到末尾。客户端只认第一条兜底，多一条不改变行为
    （编译器会给出"客户端只认第一条"的告警），追加最可预期。

    排序键是整数：兜底与其前驱之间有空位就占用空位；没有空位时，
    把兜底及之后的规则整体后移一位，空出来的位置就是新的排序位。
    """
    if is_fallback:
        return (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM rules"))["s"]
    fb = db.one(conn, "SELECT MIN(sort) AS s FROM rules "
                     "WHERE type IN ('MATCH','FINAL')")
    pos = fb["s"] if fb else None
    if pos is None:
        return (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM rules"))["s"]
    prev = db.one(conn, "SELECT MAX(sort) AS s FROM rules WHERE sort < ?", (pos,))
    if prev and prev["s"] is not None and pos - prev["s"] >= 2:
        return prev["s"] + 1
    # 整体后移：sort >= pos 的全部 +1，与原值集合不会撞车（整体后移是单射）
    conn.execute("UPDATE rules SET sort = sort + 1 WHERE sort >= ?", (pos,))
    return pos


def _fallbacks_last(ids: list[int], rows: dict) -> list[int]:
    """把兜底规则挪到这组顺序的最后，其余规则相对顺序不变。"""
    normal = [i for i in ids if rows[i]["type"] not in FALLBACK_TYPES]
    finals = [i for i in ids if rows[i]["type"] in FALLBACK_TYPES]
    return normal + finals


def _check_source_names(conn, names: list[str]) -> None:
    """写时校验"节点来源"必须真实存在。

    写错来源名时，产物里的 use: 会指向不存在的 proxy-provider，
    客户端静默拿不到这个来源的节点——界面与构建日志都看不出异常。
    """
    for name in names or []:
        if name == config.ALL_SCOPE:
            continue
        row = db.one(conn, "SELECT id FROM sources WHERE name=?", (name,))
        if not row:
            raise HTTPException(400, f"节点来源“{name}”不存在")


def _collapse_if_complete(conn, names: list[str], table: str) -> list[str]:
    """逐项选满 = 包含所有：把列全的列表归一为 ["*"]。

    这样以后新增的来源 / 平台 / 设备会自动包含进来，
    不必回头把列表改一遍。
    """
    if not names or config.ALL_SCOPE in names:
        return names
    existing = {r["name"] for r in db.all_(conn, f"SELECT name FROM {table}")}
    if existing and set(names) >= existing:
        return [config.ALL_SCOPE]
    return names


def _check_group_refs(conn, body: GroupBody) -> None:
    _check_target_names(conn, body.targets)
    _check_device_names(conn, body.devices)
    _check_source_names(conn, body.use_sources)


@router.get("/rules/page")
def list_rules_paged(limit: int = 50, offset: int = 0, keyword: str = "",
                     rtype: str = "", target: str = "", enabled: str = "",
                     scope: str = "", user=CurrentUser):
    """分流规则分页列表。

    keyword 匹配匹配值、目标、备注或类型；rtype/target/enabled 精确匹配；
    scope 限定适用范围：
      all      全部规则
      global   适用于所有平台与设备（targets 与 devices 都是「包含所有」）
      platform 限定了引擎平台
      device   限定了设备
    """
    with db.connect() as conn:
        where, args = [], []
        if keyword:
            like = f"%{keyword}%"
            where.append("(value LIKE ? OR target LIKE ? OR note LIKE ? OR type LIKE ?)")
            args += [like, like, like, like]
        if rtype:
            where.append("type = ?")
            args.append(rtype)
        if target:
            where.append("target = ?")
            args.append(target)
        if enabled in ("0", "1"):
            where.append("enabled = ?")
            args.append(1 if enabled == "1" else 0)
        if scope == "global":
            where.append("COALESCE(json_extract(targets, '$[0]'), '') = '*' "
                         "AND COALESCE(json_extract(devices, '$[0]'), '') = '*'")
        elif scope == "platform":
            where.append("COALESCE(json_extract(targets, '$[0]'), '') != '*'")
        elif scope == "device":
            where.append("COALESCE(json_extract(devices, '$[0]'), '') != '*'")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        data = db.paged(conn, "rules", clause, args, "sort, id", limit, offset)
        data["items"] = [_rule_public(r) for r in data["items"]]
        # 一并给出未筛选时的总数，界面好写"筛选出 N 条（共 M 条）"
        total_all = db.one(conn, "SELECT COUNT(*) AS c FROM rules")["c"]
    data["total_all"] = total_all
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
            body.targets = _collapse_if_complete(conn, body.targets, "targets")
            body.devices = _collapse_if_complete(conn, body.devices, "devices")
            sort = _rule_insert_sort(conn, body.type in FALLBACK_TYPES)
            now = db.now()
            cur = db.insert_unique(conn,
                "INSERT INTO rules(sort, type, value, target, enabled, note, no_resolve, "
                "targets, devices, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (sort, body.type, body.value, body.target, int(body.enabled),
                 body.note, int(body.no_resolve),
                 json.dumps(body.targets, ensure_ascii=False),
                 json.dumps(body.devices, ensure_ascii=False), now, now),
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
        body.targets = _collapse_if_complete(conn, body.targets, "targets")
        body.devices = _collapse_if_complete(conn, body.devices, "devices")
        _get_rule(conn, rid)
        conn.execute(
            "UPDATE rules SET type=?, value=?, target=?, enabled=?, note=?, "
            "no_resolve=?, targets=?, devices=?, updated_at=? WHERE id=?",
            (body.type, body.value, body.target, int(body.enabled), body.note,
             int(body.no_resolve), json.dumps(body.targets, ensure_ascii=False),
             json.dumps(body.devices, ensure_ascii=False),
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
        rows = {r["id"]: r for r in db.all_(conn, "SELECT id, type FROM rules")}
        if any(i not in rows for i in ids):
            raise HTTPException(400, "排序列表包含不存在的记录")
        # 拖拽也不能把规则排到兜底后面：兜底之后的规则永远匹配不到
        if not db.reorder_subset(conn, "rules", _fallbacks_last(ids, rows)):
            raise HTTPException(400, "排序未生效")
        security.audit(conn, user["username"], "调整分流规则顺序", "rule", "")
    return {"ok": True}
