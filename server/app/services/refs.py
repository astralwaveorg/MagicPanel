"""引用关系维护：删除前查引用、删除时自动解绑。

节点来源按**名称**被策略组引用（`proxy_groups.use_sources`），
本地节点按 **id** 被引用（`proxy_groups.local_nodes`）。
删除对象时如果还有策略组在用，默认拦住并把引用明细报给前端；
用户二次确认后，由这里自动把引用摘掉再删。
"""
import json

from .. import db


def _groups(conn) -> list:
    return db.all_(
        conn, "SELECT id, name, type, proxies, use_sources, local_nodes "
              "FROM proxy_groups ORDER BY name")


def source_refs(conn, name: str) -> list[dict]:
    """引用该节点来源的策略组。"""
    refs = []
    for g in _groups(conn):
        if name in json.loads(g["use_sources"] or "[]"):
            refs.append({"id": g["id"], "name": g["name"], "type": g["type"]})
    return refs


def local_node_refs(conn, node_id: int) -> list[dict]:
    """引用该本地节点的策略组。"""
    refs = []
    for g in _groups(conn):
        if node_id in json.loads(g["local_nodes"] or "[]"):
            refs.append({"id": g["id"], "name": g["name"], "type": g["type"]})
    return refs


def _warnings(group: dict, use_sources: list[str],
              local_nodes: list[int],
              proxies: list[str] | None = None) -> list[str]:
    """解绑后这个策略组可能出现的问题（构建时会直接报错，提前告诉用户）。"""
    out: list[str] = []
    if proxies is None:
        proxies = json.loads(group["proxies"] or "[]")
    local_count = len(local_nodes)
    if not proxies and not use_sources and not local_count:
        out.append(f"策略组“{group['name']}”将变为空（既无成员也无节点来源）")
    if group["type"] == "relay" and len(proxies) + local_count < 2:
        out.append(f"relay 策略组“{group['name']}”将只剩 {len(proxies) + local_count} 个成员，"
                   "relay 至少需要两个可用成员")
    return out


def detach_source(conn, name: str) -> tuple[list[str], list[str]]:
    """把节点来源从引用它的策略组里摘掉。

    返回 (被改动的策略组名, 警告文案)。
    """
    changed: list[str] = []
    warnings: list[str] = []
    for g in _groups(conn):
        used = json.loads(g["use_sources"] or "[]")
        if name not in used:
            continue
        rest = [s for s in used if s != name]
        conn.execute(
            "UPDATE proxy_groups SET use_sources=?, updated_at=? WHERE id=?",
            (json.dumps(rest, ensure_ascii=False), db.now(), g["id"]),
        )
        changed.append(g["name"])
        warnings.extend(_warnings(g, rest,
                                  json.loads(g["local_nodes"] or "[]")))
    return changed, warnings


def detach_local_node(conn, node_id: int) -> tuple[list[str], list[str]]:
    """把本地节点从引用它的策略组里摘掉。

    返回 (被改动的策略组名, 警告文案)。
    """
    changed: list[str] = []
    warnings: list[str] = []
    for g in _groups(conn):
        ids = json.loads(g["local_nodes"] or "[]")
        if node_id not in ids:
            continue
        rest = [i for i in ids if i != node_id]
        conn.execute(
            "UPDATE proxy_groups SET local_nodes=?, updated_at=? WHERE id=?",
            (json.dumps(rest, ensure_ascii=False), db.now(), g["id"]),
        )
        changed.append(g["name"])
        warnings.extend(_warnings(g, json.loads(g["use_sources"] or "[]"), rest))
    return changed, warnings


def rule_provider_refs(conn, name: str) -> list[dict]:
    """引用该规则来源的分流规则（含已停用规则）。"""
    rows = db.all_(
        conn,
        "SELECT id, enabled, target, note FROM rules "
        "WHERE type='RULE-SET' AND value=? ORDER BY sort, id",
        (name,),
    )
    return [
        {"id": r["id"], "enabled": bool(r["enabled"]), "target": r["target"],
         "note": r["note"] or ""}
        for r in rows
    ]


def detach_rule_provider(conn, name: str) -> list[dict]:
    """删除引用该规则来源的分流规则。

    规则集没了，引用它的 RULE-SET 规则就没有意义（构建时也会直接报错），
    所以这里连规则一起删掉。
    """
    rows = rule_provider_refs(conn, name)
    for r in rows:
        conn.execute("DELETE FROM rules WHERE id=?", (r["id"],))
    return rows


# ---- 策略组 ----

def group_members(conn, name: str) -> list[dict]:
    """把该策略组当作成员的其它策略组。"""
    out = []
    for g in _groups(conn):
        if name in json.loads(g["proxies"] or "[]"):
            out.append({"id": g["id"], "name": g["name"], "type": "策略组",
                        "group_type": g["type"]})
    return out


def rules_targeting(conn, name: str) -> list[dict]:
    """指向该策略组的分流规则。"""
    rows = db.all_(
        conn,
        "SELECT id, type, value, target, enabled FROM rules WHERE target=? "
        "ORDER BY sort, id",
        (name,),
    )
    return [
        {"id": r["id"], "enabled": bool(r["enabled"]), "type": r["type"],
         "value": r["value"]}
        for r in rows
    ]


def detach_group(conn, name: str) -> tuple[list[str], list[dict], list[str]]:
    """解绑策略组：其它组里的成员引用摘掉，指向它的分流规则删掉。

    返回 (被改动的策略组名, 被删除的规则, 警告文案)。
    """
    changed: list[str] = []
    warnings: list[str] = []
    for g in _groups(conn):
        proxies = json.loads(g["proxies"] or "[]")
        if name not in proxies:
            continue
        rest = [p for p in proxies if p != name]
        conn.execute(
            "UPDATE proxy_groups SET proxies=?, updated_at=? WHERE id=?",
            (json.dumps(rest, ensure_ascii=False), db.now(), g["id"]),
        )
        changed.append(g["name"])
        warnings.extend(_warnings(
            g, json.loads(g["use_sources"] or "[]"),
            json.loads(g["local_nodes"] or "[]"), proxies=rest))
    removed = rules_targeting(conn, name)
    for r in removed:
        conn.execute("DELETE FROM rules WHERE id=?", (r["id"],))
    return changed, removed, warnings


# ---- 引擎平台 ----

def target_devices(conn, target_id: int) -> list[dict]:
    """使用该引擎平台的设备。"""
    rows = db.all_(
        conn, "SELECT id, name, platform FROM devices WHERE target_id=? ORDER BY id",
        (target_id,),
    )
    return [{"id": r["id"], "name": r["name"], "type": "设备",
             "platform": r["platform"]} for r in rows]


def rename_source(conn, old: str, new: str) -> list[str]:
    """来源改名：把策略组里的引用一起改成新名字。"""
    changed: list[str] = []
    for g in _groups(conn):
        used = json.loads(g["use_sources"] or "[]")
        if old not in used:
            continue
        rest = [new if u == old else u for u in used]
        conn.execute(
            "UPDATE proxy_groups SET use_sources=?, updated_at=? WHERE id=?",
            (json.dumps(rest, ensure_ascii=False), db.now(), g["id"]),
        )
        changed.append(g["name"])
    return changed


def rename_rule_provider(conn, old: str, new: str) -> list[dict]:
    """规则来源改名：把引用它的 RULE-SET 规则一起改成新名字。"""
    rows = rule_provider_refs(conn, old)
    for r in rows:
        conn.execute("UPDATE rules SET value=?, updated_at=? WHERE id=?",
                     (new, db.now(), r["id"]))
    return rows
