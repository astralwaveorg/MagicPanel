"""有序成员引用的唯一解析入口；纯函数不读取数据库。"""
import json
from .. import config


class ReferenceResolutionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def check_format(group):
    value = group.get('members_format','legacy')
    if value not in ('legacy','typed-v2'):
        raise ReferenceResolutionError('members_format_invalid')
    return value


def decoded(value, default):
    return json.loads(value) if isinstance(value, str) else (default if value is None else value)


def resolve_refs(refs: list[dict], *, variant_id: int, groups: list[dict], nodes: list[dict]) -> list[str]:
    groups = [dict(g) for g in groups]
    nodes = [dict(n) for n in nodes]
    for group in groups:
        check_format(group)
    by_id = {str(g['id']): g for g in groups if 'id' in g}
    by_uid = {n['node_uid']: n for n in nodes}

    def check(ref, visiting):
        if not isinstance(ref, dict) or set(ref) != {'kind', 'ref'} or not isinstance(ref['ref'], str):
            raise ReferenceResolutionError('reference_invalid')
        kind, key = ref['kind'], ref['ref']
        if kind == 'builtin':
            if key not in config.BUILTIN_TARGETS:
                raise ReferenceResolutionError('reference_invalid')
            return key
        if kind == 'node':
            node = by_uid.get(key)
            if node is None:
                raise ReferenceResolutionError('node_missing')
            if not node.get('enabled', True) or node.get('retired', False):
                raise ReferenceResolutionError('node_disabled')
            return node['emit_name']
        if kind != 'group' or not key.isdecimal() or str(int(key)) != key:
            raise ReferenceResolutionError('reference_invalid')
        group = by_id.get(key)
        if group is None:
            raise ReferenceResolutionError('group_missing')
        if group.get('variant_id', 0) != variant_id:
            raise ReferenceResolutionError('group_cross_variant')
        if key in visiting:
            raise ReferenceResolutionError('reference_cycle')
        members = decoded(group.get('members_v2'), [])
        if group.get('members_format') == 'legacy':
            members = legacy_refs(decoded(group.get('proxies'),[]), variant_id=variant_id,
                                  groups=groups,nodes=nodes,
                                  local_ids=decoded(group.get('local_nodes'),[]),
                                  local_first=bool(group.get('local_first')))
        if not isinstance(members,list):
            raise ReferenceResolutionError('reference_invalid')
        for member in members:
            check(member, visiting | {key})
        return group['name']

    if not isinstance(refs, list):
        raise ReferenceResolutionError('reference_invalid')
    names, owners = [], {}
    for ref in refs:
        name = check(ref,set())
        identity = (ref['kind'],ref['ref'])
        if name in owners and owners[name] != identity:
            raise ReferenceResolutionError('reference_ambiguous')
        if name not in owners:
            names.append(name)
            owners[name] = identity
    return names


def legacy_refs(names, *, variant_id, groups, nodes, local_ids=(), local_first=False):
    """旧名称必须唯一匹配，失败时不返回部分转换结果。"""
    index = {}
    for kind, entries, name_key, ref_key in (
        ('group', [dict(g) for g in groups if g.get('variant_id', 0) == variant_id], 'name', 'id'),
        ('node', nodes, 'emit_name', 'node_uid'),
    ):
        for entry in entries:
            index.setdefault(entry[name_key], []).append({'kind':kind, 'ref':str(entry[ref_key])})
    for name in config.BUILTIN_TARGETS:
        index.setdefault(name, []).append({'kind':'builtin','ref':name})
    refs = []
    for name in names:
        choices = index.get(name, [])
        if len(choices) != 1:
            raise ReferenceResolutionError('reference_ambiguous' if choices else 'reference_missing')
        refs.append(choices[0])
    local = []
    for local_id in local_ids:
        choices = [n for n in nodes if n.get('local_node_id') == local_id]
        if len(choices) != 1:
            raise ReferenceResolutionError('reference_missing')
        local.append({'kind':'node','ref':choices[0]['node_uid']})
    refs = local + refs if local_first else refs + local
    return list({(r['kind'],r['ref']):r for r in refs}.values())


def context(conn):
    from .node_catalog import list_active_nodes
    groups = [dict(g) for g in conn.execute('SELECT * FROM proxy_groups')]
    for group in groups:
        check_format(group)
    return groups, list_active_nodes(conn)


def project_group(conn, row):
    group = dict(row)
    check_format(group)
    if group.get('members_format') == 'typed-v2':
        groups, nodes = context(conn)
        group['proxies'] = json.dumps(resolve_refs(decoded(group['members_v2'], []),
            variant_id=group['variant_id'], groups=groups, nodes=nodes), ensure_ascii=False)
        group['local_nodes'] = '[]'
    return group


def canonical_group(conn, gid, refs=None):
    groups, nodes = context(conn)
    group = next(g for g in groups if g['id'] == gid)
    if refs is None:
        refs = legacy_refs(decoded(group['proxies'], []), variant_id=group['variant_id'],
            groups=groups, nodes=nodes, local_ids=decoded(group['local_nodes'], []),
            local_first=bool(group['local_first']))
    if not isinstance(refs,list):
        raise ReferenceResolutionError('reference_invalid')
    candidate = {**group, 'members_v2':refs, 'members_format':'typed-v2'}
    names = resolve_refs(refs, variant_id=group['variant_id'],
                 groups=[candidate if g['id'] == gid else g for g in groups], nodes=nodes)
    refs = list({(r['kind'],r['ref']):r for r in refs}.values())
    conn.execute("UPDATE proxy_groups SET members_v2=?,members_format='typed-v2',proxies=?,local_nodes='[]' WHERE id=?",
                 (json.dumps(refs, ensure_ascii=False), json.dumps(names, ensure_ascii=False), gid))
    return refs


def canonical_rule(conn, rid, ref=None):
    row = dict(conn.execute('SELECT * FROM rules WHERE id=?', (rid,)).fetchone())
    groups, nodes = context(conn)
    if ref is None:
        ref = legacy_refs([row['target']], variant_id=row['variant_id'], groups=groups, nodes=nodes)[0]
    if isinstance(ref,dict) and ref.get('kind') == 'node':
        raise ReferenceResolutionError('reference_invalid')
    name = resolve_rule_target(ref, variant_id=row['variant_id'], groups=groups, nodes=nodes)
    conn.execute("UPDATE rules SET target_ref_v2=?,target=? WHERE id=?", (json.dumps(ref),name,rid))
    return ref


def migrate_refs(conn):
    for table, column, definition in (
        ('proxy_groups','members_v2',"TEXT NOT NULL DEFAULT '[]'"),
        ('proxy_groups','members_format',"TEXT NOT NULL DEFAULT 'legacy'"),
        ('rules','target_ref_v2',"TEXT NOT NULL DEFAULT 'null'"),
    ):
        if column not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    for group in conn.execute('SELECT members_format FROM proxy_groups'):
        check_format(dict(group))
    for group in list(conn.execute("SELECT id FROM proxy_groups WHERE members_format='legacy'")):
        try:
            canonical_group(conn, group['id'])
        except ValueError as exc:
            conn.execute('INSERT OR IGNORE INTO catalog_issues(code,origin,candidate_uids) VALUES(?,?,?)',
                         (str(exc),f"group:{group['id']}",'[]'))
    for rule in list(conn.execute("SELECT id FROM rules WHERE target_ref_v2='null'")):
        try:
            canonical_rule(conn, rule['id'])
        except ValueError:
            pass
    conn.execute("INSERT OR IGNORE INTO schema_version(key,value) VALUES('v2_typed_refs','1')")


def resolve_snapshot(snapshot, *, variant_id=None):
    """仅消费冻结快照；旧快照保持既有名称适配路径。"""
    from copy import deepcopy
    result = deepcopy(snapshot)
    groups = result.get('groups', [])
    nodes = result.get('node_catalog', [])
    for group in groups:
        if variant_id is not None and group.get('variant_id',0) != variant_id:
            continue
        check_format(group)
        if group.get('members_format') == 'typed-v2':
            group['proxies'] = resolve_refs(decoded(group.get('members_v2'), []),
                variant_id=group.get('variant_id',0),groups=groups,nodes=nodes)
            group['local_nodes'] = []
    for rule in result.get('rules', []):
        if variant_id is not None and rule.get('variant_id',0) != variant_id:
            continue
        ref = decoded(rule.get('target_ref_v2'), None)
        if ref is not None:
            rule['target'] = resolve_rule_target(ref,variant_id=rule.get('variant_id',0),groups=groups,nodes=nodes)
        else:
            target = next((g for g in groups if g.get('variant_id',0) == rule.get('variant_id',0) and g['name'] == rule.get('target')),None)
            if target and target.get('hidden'):
                raise ReferenceResolutionError('reference_hidden')
    return result


def resolve_rule_target(ref, *, variant_id, groups, nodes):
    name = resolve_refs([ref],variant_id=variant_id,groups=groups,nodes=nodes)[0]
    if ref['kind'] == 'node':
        raise ReferenceResolutionError('reference_invalid')
    if ref['kind'] == 'group':
        group = next(g for g in groups if str(g['id']) == ref['ref'])
        if group.get('hidden'):
            raise ReferenceResolutionError('reference_hidden')
    return name


def patch_group_refs(conn, row, *, names=None, local_ids=None, local_first=None):
    """分别替换策略成员和本地节点，保留其他引用及其相对顺序。"""
    group = dict(row)
    groups, nodes = context(conn)
    options = dict(variant_id=group['variant_id'], groups=groups, nodes=nodes)
    refs = (decoded(group['members_v2'], []) if check_format(group) == 'typed-v2'
            else legacy_refs(decoded(group['proxies'], []), **options,
                             local_ids=decoded(group['local_nodes'], []),
                             local_first=bool(group['local_first'])))
    local_uids = {n['node_uid'] for n in nodes if n['origin_kind'] == 'local'}

    def category(ref):
        if ref['kind'] != 'node':
            return 'policy'
        return 'local' if ref['ref'] in local_uids else 'source'

    replacements = {}
    if names is not None:
        replacements['policy'] = legacy_refs(names, **options)
    if local_ids is not None:
        replacements['local'] = legacy_refs([], **options, local_ids=local_ids)

    # 逐个填回同类的原位置，新增成员接在该类的末尾。
    last = {category(ref): i for i, ref in enumerate(refs)}
    offsets = dict.fromkeys(replacements, 0)
    result = []
    for i, ref in enumerate(refs):
        kind = category(ref)
        if kind not in replacements:
            result.append(ref)
            continue
        offset = offsets[kind]
        stop = len(replacements[kind]) if i == last[kind] else offset + 1
        result.extend(replacements[kind][offset:stop])
        offsets[kind] = stop
    for kind, entries in replacements.items():
        if kind not in last:
            if kind == 'local' and (group['local_first'] if local_first is None else local_first):
                result[:0] = entries
            else:
                result.extend(entries)
    if local_first is not None:
        local = [ref for ref in result if category(ref) == 'local']
        rest = [ref for ref in result if category(ref) != 'local']
        result = local + rest if local_first else rest + local
    return result
