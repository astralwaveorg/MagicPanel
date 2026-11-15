"""稳定节点目录；写入沿用调用方事务，材料只供受控内部调用。"""
import json
import hashlib
import hmac
import uuid
from collections import Counter

from .. import db, security
from ..schemas.nodes import split_parameters
from . import local_nodes, node_identity, resource_store, source_nodes


def _transaction(conn):
    if not conn.in_transaction:
        raise ValueError('catalog_transaction_required')


def _entry(row):
    return {**{k: row[k] for k in ('node_uid', 'origin_kind', 'source_id', 'local_node_id',
                                  'raw_name', 'display_name', 'emit_name')},
            'revision': row['current_revision'], 'enabled': bool(row['enabled']),
            'meta': json.loads(row['meta_json'])}


def list_active_nodes(conn):
    return [_entry(row) for row in conn.execute(
        'SELECT * FROM node_catalog WHERE retired=0 ORDER BY ordinal')]


def get_revision(conn, node_uid: str, revision: int):
    row = conn.execute('SELECT public_config_json,created_at FROM node_revisions '
                       'WHERE node_uid=? AND revision=?', (node_uid, revision)).fetchone()
    if row is None:
        return None
    return {'node_uid': node_uid, 'revision': revision, 'created_at': row['created_at'],
            **json.loads(row['public_config_json'])}


def load_probe_material(conn, node_uid: str, revision: int):
    row = conn.execute('SELECT material_blob_id FROM node_revisions WHERE node_uid=? AND revision=?',
                       (node_uid, revision)).fetchone()
    if row is None:
        raise ValueError('catalog_revision_missing')
    material = json.loads(resource_store.get_private(conn, row['material_blob_id']))
    material['name'] = 'mp-' + node_uid
    return material


def _public(material):
    params = {k: v for k, v in material.items() if k not in {'type', 'server', 'port'}}
    public, secrets = split_parameters(material['type'], params)
    fields = sorted(k for k, v in secrets.items() if v not in ('', None, {}, []))
    return {'protocol': material['type'], 'server': material['server'], 'port': material['port'],
            'public_params': public, 'configured_secret_fields': fields, 'has_credentials': bool(fields)}


def _issue(conn, report, code, origin, candidates):
    issue = {'code': code, 'origin': origin, 'candidate_uids': sorted(candidates)}
    conn.execute('INSERT OR IGNORE INTO catalog_issues(code,origin,candidate_uids) VALUES(?,?,?)',
                 (code, origin, json.dumps(issue['candidate_uids'])))
    report['issues'].append(issue)


def _report():
    return {k: [] for k in ('created', 'changed', 'renamed', 'retired', 'issues')}


def _finish(conn, report):
    if any(report[k] for k in ('created', 'changed', 'renamed', 'retired')):
        conn.execute('UPDATE catalog_state SET revision=revision+1 WHERE id=1')
    report['catalog_revision'] = conn.execute('SELECT revision FROM catalog_state WHERE id=1').fetchone()[0]
    return report


def _save(conn, old, proxy, fp, *, origin_key, kind, source_id=None, local_id=None,
          emit_name, enabled, report):
    now = db.now()
    raw = str(proxy.get('name', ''))
    if old is None:
        uid = uuid.uuid4().hex
        ordinal = conn.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM node_catalog').fetchone()[0]
        conn.execute('INSERT INTO node_catalog(node_uid,origin_key,origin_kind,source_id,local_node_id,'
                     'ordinal,raw_name,display_name,emit_name,enabled,first_seen,last_seen) '
                     'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                     (uid, origin_key, kind, source_id, local_id, ordinal, raw, raw, emit_name, enabled, now, now))
        old = conn.execute('SELECT * FROM node_catalog WHERE node_uid=?', (uid,)).fetchone()
        report['created'].append(uid)
    uid = old['node_uid']
    previous = conn.execute('SELECT * FROM node_revisions WHERE node_uid=? AND revision=?',
                            (uid, old['current_revision'])).fetchone()
    revision = old['current_revision']
    if previous is None or previous['material_hmac'] != fp['material_hmac']:
        material = node_identity.canonical_material(proxy)
        blob = resource_store.put_private(conn, 'node-material', json.dumps(material, sort_keys=True,
                                              ensure_ascii=False, separators=(',', ':')).encode())
        revision += 1
        conn.execute('INSERT INTO node_revisions VALUES(?,?,?,?,?,?,?,?)',
                     (uid, revision, blob['blob_id'], fp['identity_hmac'], fp['material_hmac'],
                      fp['key_version'], json.dumps(_public(material), ensure_ascii=False), now))
        if uid not in report['created']:
            report['changed'].append(uid)
    if raw != old['raw_name']:
        report['renamed'].append(uid)
    for name_kind, name in (('raw', raw), ('display', old['display_name']), ('emit', old['emit_name'])):
        conn.execute('INSERT OR IGNORE INTO node_aliases VALUES(?,?,?,?)', (uid, name_kind, name, revision))
    if (old['retired'] or old['enabled'] != enabled) and uid not in report['changed']:
        report['changed'].append(uid)
    conn.execute('UPDATE node_catalog SET raw_name=?,current_revision=?,enabled=?,retired=0,last_seen=? '
                 'WHERE node_uid=?', (raw, revision, enabled, now, uid))
    return uid


def _retire_missing(conn, old, used, report):
    for row in old:
        if row['node_uid'] not in used and not row['retired']:
            conn.execute('UPDATE node_catalog SET retired=1 WHERE node_uid=?', (row['node_uid'],))
            report['retired'].append(row['node_uid'])


def _match_trusted(conn, upstream, old, matched, used, ambiguous, report, source_id):
    counts = Counter(upstream)
    for i, digest in enumerate(upstream):
        candidates = [r for r in old if digest and r['upstream_id_hmac'] == digest]
        if not digest or counts[digest] > 1 or len(candidates) > 1:
            ambiguous[i] = {r['node_uid'] for r in (candidates or old)}
            _issue(conn, report, 'upstream_id_invalid' if not digest else 'reference_ambiguous',
                   'source:' + str(source_id), ambiguous[i])
        elif len(candidates) == 1:
            matched[i] = candidates[0]
            used.add(candidates[0]['node_uid'])


def _match_fingerprints(conn, nodes, fingerprints, old, matched, used, ambiguous, report, source_id, trusted_key):
    # 完整材料优先于凭据轮换；两者均要求一对一。
    for field in ('material_hmac', 'identity_hmac'):
        pending = [i for i in range(len(nodes)) if i not in matched and not (trusted_key and i in ambiguous)]
        counts = Counter(fingerprints[i][field] for i in pending)
        for i in pending:
            candidates = [r for r in old if r['node_uid'] not in used and r[field] == fingerprints[i][field]]
            if len(candidates) == 1 and counts[fingerprints[i][field]] == 1:
                matched[i] = candidates[0]
                used.add(candidates[0]['node_uid'])
            elif candidates:
                ambiguous[i] = {r['node_uid'] for r in candidates}
                _issue(conn, report, 'reference_ambiguous', 'source:' + str(source_id),
                       [r['node_uid'] for r in candidates])


def reconcile_source(conn, source_id: int, nodes: list[dict]):
    _transaction(conn)
    source = conn.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone()
    if source is None:
        raise ValueError('catalog_source_missing')
    key = node_identity.derive_catalog_key(security.load_master_material())
    fingerprints = [node_identity.fingerprints(p, source_id=source_id, key=key) for p in nodes]
    trusted_key = source['trusted_upstream_id_key']
    upstream = []
    for proxy in nodes:
        value = proxy.get(trusted_key) if trusted_key else None
        valid = type(value) in (str, int) and len(str(value)) <= 256 and str(value) != ''
        upstream.append(hmac.new(key, json.dumps([source_id, trusted_key, value], separators=(',', ':')).encode(),
                                 hashlib.sha256).hexdigest() if valid else None)
    old = list(conn.execute('SELECT c.*,r.material_hmac,r.identity_hmac FROM node_catalog c '
                           'JOIN node_revisions r ON c.node_uid=r.node_uid AND c.current_revision=r.revision '
                           'WHERE c.source_id=? ORDER BY c.ordinal', (source_id,)))
    report = _report()
    matched, used, ambiguous = {}, set(), {}
    if trusted_key:
        _match_trusted(conn, upstream, old, matched, used, ambiguous, report, source_id)
    _match_fingerprints(conn, nodes, fingerprints, old, matched, used, ambiguous, report, source_id, trusted_key)
    for i, proxy in enumerate(nodes):
        if i not in matched and i in ambiguous:
            used.update(ambiguous[i])
            continue
        prior = matched.get(i)
        uid = _save(conn, prior, proxy, fingerprints[i],
                    origin_key=prior['origin_key'] if prior else 'source:' + str(source_id) + ':' + uuid.uuid4().hex,
                    kind='source', source_id=source_id, emit_name=str(proxy['name']) + source['suffix'],
                    enabled=int(source['enabled']), report=report)
        if upstream[i]:
            conn.execute('UPDATE node_catalog SET upstream_id_hmac=? WHERE node_uid=?', (upstream[i], uid))
        used.add(uid)
    _retire_missing(conn, old, used, report)
    return _finish(conn, report)


def sync_local_node(conn, local_node_id: int):
    _transaction(conn)
    row = conn.execute('SELECT * FROM local_nodes WHERE id=?', (local_node_id,)).fetchone()
    prior = conn.execute('SELECT * FROM node_catalog WHERE origin_key=?', ('local:' + str(local_node_id),)).fetchone()
    report = _report()
    if row is None:
        if prior and not prior['retired']:
            conn.execute('UPDATE node_catalog SET retired=1 WHERE node_uid=?', (prior['node_uid'],))
            report['retired'].append(prior['node_uid'])
        return _finish(conn, report)
    node = dict(row)
    node['params'] = json.loads(security.decrypt_text(row['params_enc']) if row['params_enc'] else '{}')
    node['extra_yaml'] = security.decrypt_text(row['extra_yaml_enc']) if row['extra_yaml_enc'] else ''
    proxy = local_nodes.render_proxy(node, 'mihomo')
    emit_name = proxy['name']
    proxy['name'] = row['name']
    fp = node_identity.fingerprints(proxy, source_id=None,
         key=node_identity.derive_catalog_key(security.load_master_material()))
    _save(conn, prior, proxy, fp, origin_key='local:' + str(local_node_id), kind='local',
          local_id=local_node_id, emit_name=emit_name, enabled=int(row['enabled']), report=report)
    return _finish(conn, report)


def retire_source(conn, source_id):
    _transaction(conn)
    report = _report()
    for row in conn.execute('SELECT node_uid FROM node_catalog WHERE source_id=? AND retired=0', (source_id,)):
        report['retired'].append(row['node_uid'])
    conn.execute('UPDATE node_catalog SET retired=1 WHERE source_id=?', (source_id,))
    return _finish(conn, report)


def backfill(conn):
    if conn.execute("SELECT 1 FROM schema_version WHERE key='v2_catalog'").fetchone():
        return
    for row in conn.execute('SELECT * FROM sources ORDER BY id').fetchall():
        if row['snapshot_enc']:
            reconcile_source(conn, row['id'], source_nodes.extract(security.decrypt_text(row['snapshot_enc']).encode()))
    for row in conn.execute('SELECT id FROM local_nodes ORDER BY sort,id').fetchall():
        sync_local_node(conn, row['id'])
    report = _report()
    for row in conn.execute('SELECT emit_name FROM node_catalog GROUP BY emit_name HAVING COUNT(*)>1'):
        candidates = [r[0] for r in conn.execute('SELECT node_uid FROM node_catalog WHERE emit_name=?', (row[0],))]
        _issue(conn, report, 'reference_ambiguous', 'legacy_emit_name', candidates)
    conn.execute("INSERT INTO schema_version(key,value) VALUES('v2_catalog','1')")


def sync_source_enabled(conn, source_id):
    _transaction(conn)
    report = _report()
    source = conn.execute('SELECT enabled FROM sources WHERE id=?', (source_id,)).fetchone()
    if source is None:
        raise ValueError('catalog_source_missing')
    report['changed'] = [r[0] for r in conn.execute(
        'SELECT node_uid FROM node_catalog WHERE source_id=? AND retired=0 AND enabled!=?',
        (source_id, source['enabled']))]
    conn.execute('UPDATE node_catalog SET enabled=? WHERE source_id=? AND retired=0',
                 (source['enabled'], source_id))
    return _finish(conn, report)
