"""Apply the November routing policy to its known baseline; no subscription or credential writes.

Run against an isolated MAGICPANEL_DATA_DIR first. The live operation requires the
verified baseline SHA and parks auto-publish until the new artifact is promoted.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.request import urlopen

import yaml

from app import config, db, security
from app.routers.builds import create_build, current_policy
from app.services import node_catalog, node_refs, policy_mutations, releases

US = '🇺🇸 US自建'
JP = '🇯🇵 JP自建'
SG = '🇸🇬 SG自建'
SG_AIR = '🇸🇬 新加坡自动'
US_AIR = '🇺🇸 美国自动'
AIR = '♻️ 自动选择'
DIRECT = '🎯 全球直连'
FAIL = '🔰 故障转移'
SG_MEDIA = '🇸🇬 SG 媒体'
COLD = '🇺🇸 低配备用'
DISNEY = '🏰 Disney+'
REDDIT = '🔴 Reddit'
COMMON_FILE = 'rule/magic-proxy.yaml'
COMMON_URL = 'https://raw.githubusercontent.com/astralwaveorg/magic-sets/main/' + COMMON_FILE
REDDIT_URL = 'https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Clash/Reddit/Reddit.yaml'
DEFAULT_URL = 'https://www.gstatic.com/generate_204'
BASIC = [US, JP, SG, AIR]
MEDIA = [SG, JP, US, AIR]
MANUAL = [DIRECT, US, JP, SG, AIR]
# Group ordering also controls the default choice of a newly provisioned selector.
GROUPS = {
    FAIL: ('fallback', [US, JP, SG, AIR]),
    '🔍 谷歌服务': ('fallback', [36, 18, 13]),
    '▶️ YouTube': ('fallback', [18, 36, 13]),
    '🤖 ChatGPT': ('fallback', [18, 36, 13]),
    '🤖 Claude': ('fallback', [36, 18, 13]),
    '✨ Gemini': ('fallback', [36, 18, 13]),
    '🤖 国际 AI': ('fallback', [36, 18, 13]),
    '🎬 Netflix': ('fallback', [28, 37, 18, 36, JP, SG_AIR]),
    REDDIT: ('fallback', [36, 18, 32, 33, 28, 37, US_AIR]),
    DISNEY: ('select', [SG_MEDIA, 18, '🇹🇼 台湾自动', '🇭🇰 香港自动']),
    SG_MEDIA: ('fallback', [SG, SG_AIR]),
    '📨 Telegram': ('fallback', BASIC),
    '📟 开发运维': ('fallback', [*BASIC, DIRECT]),
    '🎥 Emby': ('fallback', [JP, SG, US, AIR, DIRECT]),
    '🚇 路由回家': ('select', ['DIRECT', 11, 29]),
    '🌍 国外域名': ('select', [FAIL]),
    '💬 即时通讯': ('fallback', BASIC),
    '📹 Zoom': ('fallback', [*BASIC, DIRECT]),
    '🫧 社交媒体': ('fallback', BASIC),
    '🎶 TikTok': ('fallback', MEDIA),
    '📞 Talkatone': ('fallback', [36, 18, 13, US_AIR]),
    '💳 PayPal': ('select', [DIRECT, 36, 18]),
    '🪙 加密货币': ('select', [DIRECT, 36, 18]),
    '📺 国际媒体': ('fallback', MEDIA),
    '📺 Bahamut': ('select', ['🇹🇼 台湾自动']),
    '🎮 游戏平台': ('select', MANUAL),
    'Ⓜ️ 微软服务': ('select', MANUAL),
    '🍎 苹果服务': ('select', MANUAL),
    '📚 学术资源': ('fallback', [*BASIC, DIRECT]),
    '🛒 国外电商': ('fallback', BASIC),
    '⏬ PT站点': ('select', MANUAL),
    '⚡ 测速工具': ('select', [DIRECT, US, JP, SG, COLD, '🇭🇰 香港自动', US_AIR, '🇯🇵 日本自动', SG_AIR, '🇹🇼 台湾自动', '🇰🇷 韩国自动', '🇬🇧 英国自动', '🇩🇪 德国自动', '🌍 其他自动', '🏠 家宽自动', AIR]),
    '🔀 非标端口': ('select', [DIRECT, FAIL]),
    DIRECT: ('select', ['DIRECT']),
    US: ('fallback', [36, 18, 35, 13]),
    JP: ('fallback', [32, 30, 33, 31, 34]),
    SG: ('fallback', [28, 37]),
    COLD: ('url-test', [39, 38]),
}
NODES = {
    18: ('🇺🇸 美国自建 01', '66Cloud · Hy2'),
    13: ('🇺🇸 美国自建 02', '66Cloud · VLESS'),
    35: ('🇺🇸 美国自建 03', 'SadIDC · Hy2'),
    36: ('🇺🇸 美国自建 04', 'SadIDC→66Cloud · Hy2'),
    32: ('🇯🇵 日本自建 01', 'VPS.TAXI · Hy2'),
    34: ('🇯🇵 日本自建 02', 'VPS.TAXI · Hy2 备用端口'),
    30: ('🇯🇵 日本自建 03', 'Legend · Hy2'),
    31: ('🇯🇵 日本自建 04', 'Legend · Shadowsocks'),
    33: ('🇯🇵 日本自建 05', 'VPS.TAXI · VLESS'),
    28: ('🇸🇬 新加坡自建 01', 'ISIF · Hy2'),
    37: ('🇸🇬 新加坡自建 02', 'ISIF · VLESS'),
}
AIR_GROUPS = {
    '🇭🇰 香港自动', US_AIR, '🇯🇵 日本自动', SG_AIR, '🇹🇼 台湾自动',
    '🇰🇷 韩国自动', '🇬🇧 英国自动', '🇩🇪 德国自动', '🌍 其他自动', '🏠 家宽自动', AIR,
}
# Keep relative order within each tier, including process and management rules.
EARLY_RULES = set(range(2000, 2025)) | set(range(2086, 2091)) | {2096, 2098}
DIRECT_DOWNLOAD = set(range(2029, 2033)) | {2091, 2092, 2070}
EXPLICIT_SERVICE = {
    2094, 2095, 2097, 2033, 2034, 2035, 2036, 2038, 2039, 2041, 2042, 2043, 2044, 2045,
    2047, 2049, 2052, 2053, 2054, 2057, 2058, 2059, 2060, 2061, 2062, 2063, 2064,
    2065, 2066, 2071, 2073, 2075, 2076, 2077, 2078,
}


def rule_rank(row):
    i = row['id']
    if i in EARLY_RULES:
        # Specific home routes precede general private CIDRs.
        return 0, 1 if i == 2024 else 0
    if i in DIRECT_DOWNLOAD:
        return 1, 0
    if i in EXPLICIT_SERVICE:
        return 2, {2095: 0, 2094: 1, 2045: 2, 2078: 3}.get(i, 4)
    if i == 2093:
        return 3, 0
    if i in {2025, 2026, 2099}:
        return 4, 0
    if i == 2027:
        return 5, 0
    if i == 2028:
        return 6, 1
    if i in {2074, 2079, 2080, 2081, 2082, 2083, 2084, 2085}:
        return 7, 0
    return 6, 0


def local(conn, id):
    row = conn.execute("SELECT * FROM local_nodes WHERE id=?", (id,)).fetchone()
    if row is None:
        raise SystemExit(f'local baseline missing: {id}')
    return row


def sha():
    with closing(db.connect()) as conn:
        return current_policy(conn)[1]


def apply(expected, backup, expected_after):
    with urlopen(REDDIT_URL, timeout=15) as response:
        data = response.read(65_537)
    payload = yaml.safe_load(data)
    entries = payload.get('payload', []) if isinstance(payload, dict) else []
    if not entries or len(data) > 65_536 or any(not isinstance(x, str) or not x.startswith('DOMAIN-SUFFIX,') for x in entries):
        raise SystemExit('Unrecognized Reddit classical rule source.')
    if not {'DOMAIN-SUFFIX,reddit.com', 'DOMAIN-SUFFIX,redd.it', 'DOMAIN-SUFFIX,redditstatic.com'} <= set(entries):
        raise SystemExit('Reddit classical rules are missing required domains.')
    content = data.decode('utf-8')
    with urlopen(COMMON_URL, timeout=15) as response:
        common = response.read(65_537)
    common_doc = yaml.safe_load(common)
    common_entries = common_doc.get('payload', []) if isinstance(common_doc, dict) else []
    if (not common_entries or len(common) > 65_536
            or any(not isinstance(x, str) or not x.startswith(('DOMAIN,', 'DOMAIN-SUFFIX,', 'IP-CIDR,'))
                   for x in common_entries)):
        raise SystemExit('Unrecognized common proxy rule source.')
    common = common.decode('utf-8')
    with db.tx() as conn:
        if current_policy(conn)[1] != expected:
            raise SystemExit('Policy modified since the isolated baseline; no writes performed.')
        existing = {r['name']: dict(r) for r in conn.execute('SELECT * FROM proxy_groups WHERE variant_id=0')}
        if set(existing) != (set(GROUPS) - {COLD, DISNEY, REDDIT}) | AIR_GROUPS:
            raise SystemExit('Default group set differs from the agreed baseline.')
        for id, old_name in ((38, '🇺🇸 美国自建 05'), (39, '🇺🇸 美国自建 06')):
            if local(conn, id)['name'] != old_name:
                raise SystemExit(f'Cold node baseline mismatch: {id}')
        for id, (old, _) in NODES.items():
            if local(conn, id)['name'] != old:
                raise SystemExit(f'Local node baseline mismatch: {id}')
        if backup:
            if db.get_setting(conn, 'auto_publish_enabled') != '1':
                raise SystemExit('Auto-publish state differs from the agreed baseline.')
            if backup.exists():
                raise SystemExit('Live backup already exists.')
            backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with closing(db.connect()) as reader, closing(sqlite3.connect(backup)) as copy:
                reader.backup(copy)
                if copy.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise SystemExit('Backup did not pass quick_check.')
            db.set_setting(conn, 'auto_publish_enabled', '0')

        for id, (old, desc) in NODES.items():
            projection = conn.execute('SELECT node_uid,emit_name FROM node_catalog WHERE local_node_id=? AND retired=0', (id,)).fetchone()
            conn.execute('UPDATE local_nodes SET name=?,updated_at=? WHERE id=?', (f'{old} · {desc}', db.now(), id))
            node_catalog.sync_local_node(conn, id)
            policy_mutations.refresh_node_projection(conn, projection['emit_name'], projection['node_uid'])

        for name, source, hidden in ((COLD, US, 1), (DISNEY, SG_MEDIA, 0), (REDDIT, SG_MEDIA, 0)):
            template = {**existing[source], 'name': name, 'hidden': hidden,
                        'created_at': db.now(), 'updated_at': db.now()}
            del template['id']
            fields = ','.join(template)
            marks = ','.join('?' for _ in template)
            new_id = conn.execute(f'INSERT INTO proxy_groups({fields}) VALUES({marks})', tuple(template.values())).lastrowid
            existing[name] = {**template, 'id': new_id}
        group_refs = {name: {'kind': 'group', 'ref': str(group['id'])} for name, group in existing.items()}
        _, catalog = node_refs.context(conn)
        local_refs = {n['local_node_id']: {'kind': 'node', 'ref': n['node_uid']} for n in catalog if n['local_node_id'] is not None}

        def ref(value):
            if value == 'DIRECT':
                return {'kind': 'builtin', 'ref': 'DIRECT'}
            if isinstance(value, int):
                return local_refs[value]
            return group_refs[value]

        for i, (name, (kind, members)) in enumerate(GROUPS.items()):
            id = existing[name]['id']
            conn.execute("""UPDATE proxy_groups SET sort=?,type=?,filter='',use_sources='[]',
                url=?,interval=?,updated_at=? WHERE id=?""",
                (i, kind, 'https://www.reddit.com/' if name == REDDIT else DEFAULT_URL, 300, db.now(), id))
            node_refs.canonical_group(conn, id, [ref(m) for m in members])
        for i, name in enumerate(sorted(AIR_GROUPS, key=lambda n: existing[n]['sort']), start=len(GROUPS)):
            row = existing[name]
            if row['use_sources'] != '["*"]' or json.loads(row['members_v2']):
                raise SystemExit(f'Airport group uses an unexpected source: {name}')
            conn.execute('UPDATE proxy_groups SET sort=?,updated_at=? WHERE id=?', (i, db.now(), row['id']))

        rules = conn.execute('SELECT id,sort FROM rules WHERE variant_id=0 ORDER BY sort,id').fetchall()
        if len(rules) != 96 or rules[-1]['id'] != 2085:
            raise SystemExit('Default rule set differs from the agreed baseline.')
        now = db.now()
        conn.execute('''INSERT INTO rule_providers
            (name,behavior,format,kind,url,interval,client_interval,last_status,last_fetched_at,
             rule_count,sha256,content,created_at,updated_at)
            VALUES ('Reddit','classical','yaml','remote',?,28800,28800,'ok',?,?,?,?,?,?)''',
            (REDDIT_URL, now, len(entries), security.sha256_text(content), content, now, now))
        conn.execute('''INSERT INTO rule_providers
            (name,behavior,format,kind,repo_path,interval,client_interval,last_status,last_fetched_at,
             rule_count,sha256,content,created_at,updated_at)
            VALUES ('magic-proxy','classical','yaml','repo',?,28800,28800,'ok',?,?,?,?,?,?)''',
            (COMMON_FILE, now, len(common_entries), security.sha256_text(common), common, now, now))
        old_ip = db.one(conn, 'SELECT value FROM rules WHERE id=2028')
        if not old_ip or old_ip['value'] != 'Custom_Proxy_Classical_IP':
            raise SystemExit('Common proxy baseline mismatch.')
        conn.execute("UPDATE rules SET value='magic-proxy',updated_at=? WHERE id=2028", (now,))
        reddit_rule = conn.execute('''INSERT INTO rules
            (variant_id,sort,type,value,target,targets,devices,created_at,updated_at)
            VALUES (0,0,'RULE-SET','Reddit',?,?,?,?,?)''',
            (REDDIT, '["*"]', '["*"]', now, now)).lastrowid
        node_refs.canonical_rule(conn, reddit_rule, group_refs[REDDIT])
        ranks = [(rule_rank(r), r['id']) for r in rules]
        ranks.append(((2, 4), reddit_rule))
        for sort, (_, id) in enumerate(sorted(ranks, key=lambda r: r[0])):
            conn.execute('UPDATE rules SET sort=? WHERE id=?', (sort, id))
        disney = db.one(conn, 'SELECT value FROM rules WHERE id=2059')
        if not disney or disney['value'] != 'disney':
            raise SystemExit('Disney rule baseline mismatch.')
        node_refs.canonical_rule(conn, 2059, group_refs[DISNEY])
        if expected_after and current_policy(conn)[1] != expected_after:
            raise SystemExit('Rendered policy differs from the tested candidate; transaction rolled back.')
    print('Default policy updated: 97 rules, 49 groups; the two cold node rows were retained.')


def release(target, id, expected, old):
    with db.tx() as conn:
        build = db.one(conn, 'SELECT * FROM builds WHERE id=?', (id,))
        prod = db.one(conn, 'SELECT id FROM builds WHERE status=?', (releases.BuildStatus.PRODUCTION.value,))
        if not build or build['policy_sha'] != expected or current_policy(conn)[1] != expected:
            raise SystemExit('Artifact or live policy no longer matches the verified policy.')
        if not prod or prod['id'] != old:
            raise SystemExit('Production was switched by another operator.')
        env = releases.Env.TESTING if target == 'testing' else releases.Env.PRODUCTION
        fn = releases.publish_to_testing if target == 'testing' else releases.publish_to_production
        fn(conn, build, 'routing-rollout', '杭州分流与自建故障转移',
           expected_revision=releases.revision(conn, env))
        if target == 'production':
            db.set_setting(conn, 'auto_publish_enabled', '1')
    print(f'{target}: build {id}')


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='phase', required=True)
    sub.add_parser('sha')
    ap = sub.add_parser('apply')
    ap.add_argument('baseline')
    ap.add_argument('--live-backup', type=Path)
    ap.add_argument('--expected-after')
    sub.add_parser('build')
    for target in ('testing', 'production'):
        bp = sub.add_parser(target)
        bp.add_argument('id', type=int)
        bp.add_argument('expected')
        bp.add_argument('previous', type=int)
    args = p.parse_args()
    if args.phase == 'sha':
        print(sha())
    elif args.phase == 'apply':
        if config.DATA_DIR == Path('/app/data') and not (args.live_backup and args.expected_after):
            raise SystemExit('Live apply requires a backup path and the tested candidate digest.')
        apply(args.baseline, args.live_backup, args.expected_after)
    elif args.phase == 'build':
        build, verified = create_build('routing-rollout', '杭州分流与自建故障转移')
        with closing(db.connect()) as conn:
            row = db.one(conn, 'SELECT policy_sha,results FROM builds WHERE id=?', (build,))
            results = json.loads(row['results'])
            print(json.dumps({'build': build, 'status': verified, 'sha': row['policy_sha'],
                              'artifacts': sorted(results)}, ensure_ascii=False))
        if verified != 'success':
            raise SystemExit(1)
    else:
        release(args.phase, args.id, args.expected, args.previous)


if __name__ == '__main__':
    main()
