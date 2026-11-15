"""引用关系维护：删除前查引用、删除时自动解绑。

节点来源按**名称**被策略组引用（`proxy_groups.use_sources`），
节点以 UID、组以同方案 ID 引用；旧名称和本地 ID 仅由兼容入口适配。
删除对象时如果还有策略组在用，默认拦住并把引用明细报给前端；
用户二次确认后，由这里自动把引用摘掉再删。
"""
import json
import re
import urllib.parse

from .. import db
from . import node_refs
from .local_nodes import display_name


def _groups(conn, variant_id: int | None = None) -> list:
    """策略组列表；variant_id 为 None 时跨全部方案（来源/节点删除用）。"""
    if variant_id is None:
        return db.all_(
            conn, "SELECT * FROM proxy_groups ORDER BY name")
    return db.all_(
        conn, "SELECT * FROM proxy_groups WHERE variant_id=? ORDER BY name",
        (variant_id,))


def source_refs(conn, name: str) -> list[dict]:
    """引用该节点来源的策略组。"""
    refs = []
    for g in _groups(conn):
        if name in json.loads(g["use_sources"] or "[]"):
            refs.append({"id": g["id"], "name": g["name"], "type": g["type"]})
    return refs


def local_node_refs(conn, node_id: int) -> list[dict]:
    node = db.one(conn, "SELECT * FROM local_nodes WHERE id=?", (node_id,))
    catalog = db.one(conn, "SELECT node_uid,emit_name FROM node_catalog WHERE local_node_id=?", (node_id,))
    uid = catalog['node_uid'] if catalog else None
    name = catalog['emit_name'] if catalog else (display_name(node['name'],node['node_type']) if node else '')
    out = []
    for g in _groups(conn):
        typed = node_refs.decoded(g['members_v2'], []) if g['members_format'] == 'typed-v2' else []
        if (any(r == {'kind':'node','ref':uid} for r in typed) or
                (g['members_format'] != 'typed-v2' and
                 (node_id in json.loads(g['local_nodes'] or '[]') or name in json.loads(g['proxies'] or '[]')))):
            out.append({'id':g['id'],'name':g['name'],'type':g['type'],'variant_id':g['variant_id']})
    return out


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


def detach_node(conn, node_uid: str) -> dict:
    catalog = db.one(conn, "SELECT * FROM node_catalog WHERE node_uid=?", (node_uid,))
    if not catalog:
        raise ValueError('node_missing')
    changed, warnings = [], []
    for g in _groups(conn):
        if g['members_format'] == 'typed-v2':
            members = node_refs.decoded(g['members_v2'], [])
            rest = [r for r in members if r != {'kind':'node','ref':node_uid}]
            if rest == members:
                continue
            names = [n for n in json.loads(g['proxies'] or '[]') if n != catalog['emit_name']]
            conn.execute('UPDATE proxy_groups SET members_v2=?,proxies=?,updated_at=? WHERE id=?',
                (json.dumps(rest),json.dumps(names,ensure_ascii=False),db.now(),g['id']))
        else:
            ids = json.loads(g['local_nodes'] or '[]')
            names = json.loads(g['proxies'] or '[]')
            rest_ids = [i for i in ids if i != catalog['local_node_id']]
            rest_names = [n for n in names if n != catalog['emit_name']]
            if ids == rest_ids and names == rest_names:
                continue
            conn.execute('UPDATE proxy_groups SET local_nodes=?,proxies=?,updated_at=? WHERE id=?',
                (json.dumps(rest_ids),json.dumps(rest_names,ensure_ascii=False),db.now(),g['id']))
        changed.append(g['name'])
        current = dict(db.one(conn,'SELECT * FROM proxy_groups WHERE id=?',(g['id'],)))
        warnings.extend(_warnings(current,json.loads(current['use_sources'] or '[]'),
                                   json.loads(current['local_nodes'] or '[]')))
    return {'detached_groups':changed,'warnings':warnings}


def detach_local_node(conn, node_id: int) -> tuple[list[str], list[str]]:
    catalog = db.one(conn, "SELECT node_uid FROM node_catalog WHERE local_node_id=?", (node_id,))
    if catalog:
        result = detach_node(conn,catalog['node_uid'])
        return result['detached_groups'], result['warnings']
    return [], []


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

def group_members(conn, name: str, variant_id: int | None = None) -> list[dict]:
    """把该策略组当作成员的其它策略组（方案内）。"""
    out = []
    for g in _groups(conn, variant_id):
        target = db.one(conn, "SELECT id FROM proxy_groups WHERE name=? AND variant_id=?", (name,g['variant_id']))
        typed = node_refs.decoded(g['members_v2'], [])
        if ((g['members_format'] == 'typed-v2' and target and {'kind':'group','ref':str(target['id'])} in typed)
                or (g['members_format'] != 'typed-v2' and name in json.loads(g['proxies'] or '[]'))):
            out.append({"id": g["id"], "name": g["name"], "type": "策略组",
                        "group_type": g["type"]})
    return out


def rules_targeting(conn, name: str, variant_id: int | None = None) -> list[dict]:
    result = []
    for row in db.all_(conn,'SELECT * FROM rules ORDER BY sort,id'):
        if variant_id is not None and row['variant_id'] != variant_id:
            continue
        target = db.one(conn,'SELECT id FROM proxy_groups WHERE name=? AND variant_id=?',(name,row['variant_id']))
        ref = node_refs.decoded(row['target_ref_v2'],None)
        matches = ref == {'kind':'group','ref':str(target['id'])} if ref is not None and target else ref is None and row['target'] == name
        if matches:
            result.append({'id':row['id'],'enabled':bool(row['enabled']),'type':row['type'],'value':row['value']})
    return result


def detach_group(conn, name: str, variant_id: int | None = None
                 ) -> tuple[list[str], list[dict], list[str]]:
    """解绑策略组：同方案其它组里的成员引用摘掉，指向它的分流规则删掉。

    返回 (被改动的策略组名, 被删除的规则, 警告文案)。
    """
    changed: list[str] = []
    warnings: list[str] = []
    for g in _groups(conn, variant_id):
        proxies = json.loads(g["proxies"] or "[]")
        target = db.one(conn, 'SELECT id FROM proxy_groups WHERE name=? AND variant_id=?', (name,g['variant_id']))
        members = node_refs.decoded(g['members_v2'], [])
        typed_match = bool(target and {'kind':'group','ref':str(target['id'])} in members)
        if (g['members_format'] == 'typed-v2' and not typed_match) or (g['members_format'] != 'typed-v2' and name not in proxies):
            continue
        rest = [p for p in proxies if p != name]
        if g['members_format'] == 'typed-v2':
            conn.execute('UPDATE proxy_groups SET members_v2=? WHERE id=?',
                (json.dumps([r for r in members if r != {'kind':'group','ref':str(target['id'])}]),g['id']))
        conn.execute(
            "UPDATE proxy_groups SET proxies=?, updated_at=? WHERE id=?",
            (json.dumps(rest, ensure_ascii=False), db.now(), g["id"]),
        )
        changed.append(g["name"])
        warnings.extend(_warnings(
            g, json.loads(g["use_sources"] or "[]"),
            json.loads(g["local_nodes"] or "[]"), proxies=rest))
    removed = rules_targeting(conn, name, variant_id)
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


# ---- 当前生产产物的引用 ----

def _live_build_id(conn) -> int | None:
    """当前生效的生产构建 id（产物不可变，发布只移动指针）。"""
    row = db.one(conn, "SELECT id FROM builds WHERE status='PRODUCTION' LIMIT 1")
    return int(row["id"]) if row else None


def release_resource_refs(conn, kind: str, name: str) -> list[dict]:
    """当前生产产物里是否还引用着某个下发资源。

    kind 取 "rule"（规则来源）或 "provider"（节点来源）。产物一旦发布就不可变，
    客户端手上的配置里写着这个资源的下发地址，它就会持续来取；此时把资源
    内容删掉或改名，正在使用旧产物的设备会直接 404，订阅更新随即失败。
    """
    from .. import config

    build_id = _live_build_id(conn)
    if not build_id:
        return []
    directory = config.BUILDS_DIR / str(build_id)
    if not directory.is_dir():
        return []
    pattern = re.compile(r"/res/" + re.escape(kind) + r"/([^'\"\s}]+)")
    out: list[dict] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in pattern.finditer(text):
            if urllib.parse.unquote(m.group(1)) == name:
                out.append({"artifact": path.name, "build_id": build_id})
                break
    return out


def rename_group(conn, group_id: int, new_name: str, *, variant_id: int) -> dict:
    group = db.one(conn, 'SELECT * FROM proxy_groups WHERE id=?', (group_id,))
    if not group or group['variant_id'] != variant_id:
        raise ValueError('group_cross_variant')
    old = group['name']
    conn.execute('UPDATE proxy_groups SET name=?,updated_at=? WHERE id=?',(new_name,db.now(),group_id))
    for row in _groups(conn,variant_id):
        names = [new_name if n == old else n for n in json.loads(row['proxies'] or '[]')]
        conn.execute('UPDATE proxy_groups SET proxies=? WHERE id=?',(json.dumps(names,ensure_ascii=False),row['id']))
    for rule in db.all_(conn,'SELECT * FROM rules WHERE variant_id=?',(variant_id,)):
        ref = node_refs.decoded(rule['target_ref_v2'],None)
        if ref == {'kind':'group','ref':str(group_id)} or (ref is None and rule['target'] == old):
            conn.execute('UPDATE rules SET target=? WHERE id=?',(new_name,rule['id']))
    return dict(db.one(conn,'SELECT * FROM proxy_groups WHERE id=?',(group_id,)))


def refresh_node_projection(conn, old_name: str, node_uid: str) -> None:
    node = db.one(conn,'SELECT * FROM node_catalog WHERE node_uid=?',(node_uid,))
    if node and node['local_node_id'] is not None:
        local = db.one(conn,'SELECT name,node_type FROM local_nodes WHERE id=?',(node['local_node_id'],))
        desired = display_name(local['name'],local['node_type'])
        if desired != node['emit_name']:
            if db.one(conn,'SELECT node_uid FROM node_catalog WHERE emit_name=? AND node_uid!=? AND retired=0',(desired,node_uid)):
                raise ValueError('reference_ambiguous')
            conn.execute('INSERT OR IGNORE INTO node_aliases VALUES(?,?,?,?)',
                         (node_uid,'emit',desired,node['current_revision']))
            conn.execute('UPDATE node_catalog SET emit_name=?,display_name=? WHERE node_uid=?',
                         (desired,local['name'],node_uid))
            conn.execute('UPDATE catalog_state SET revision=revision+1 WHERE id=1')
            node = db.one(conn,'SELECT * FROM node_catalog WHERE node_uid=?',(node_uid,))
    for group in _groups(conn):
        if group['members_format'] == 'typed-v2':
            members = node_refs.decoded(group['members_v2'],[])
            if {'kind':'node','ref':node_uid} in members:
                # Disabled nodes retain their identity; validation blocks new builds.
                groups,nodes = node_refs.context(conn)
                for item in nodes:
                    item['enabled'] = True
                names = node_refs.resolve_refs(members,variant_id=group['variant_id'],groups=groups,nodes=nodes)
                conn.execute('UPDATE proxy_groups SET proxies=? WHERE id=?',(json.dumps(names,ensure_ascii=False),group['id']))
        else:
            names = json.loads(group['proxies'] or '[]')
            if old_name in names:
                conn.execute('UPDATE proxy_groups SET proxies=? WHERE id=?',
                    (json.dumps([node['emit_name'] if n == old_name else n for n in names],ensure_ascii=False),group['id']))
