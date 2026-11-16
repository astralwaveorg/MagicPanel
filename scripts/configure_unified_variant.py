#!/usr/bin/env python
"""把生产分流收敛到默认方案；旧停用方案链接由 feed 回退兼容。

默认方案保留机场用于普通代理/流媒体容量，同时让 AI/Google 优先干净机房；
旧“自建美日”方案数据保留以便回滚，但停用后不再进新构建和门户入口。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'server') not in sys.path:
    sys.path.insert(0, str(ROOT / 'server'))

from app import db, security  # noqa: E402
from app.routers import builds  # noqa: E402
from app.services import node_refs, releases  # noqa: E402

# 成员顺序就是客户端里的候选顺序。Google/AI 严格 US -> SG -> JP；
# TikTok 先日本/新加坡，避免美国出口成为默认；普通代理仍保留机场容量。
GROUP_MEMBERS = {
    '🔍 谷歌服务': [
        '🇺🇸 美国NTT自动', '🇺🇸 美国机房', '🇺🇸 美国自动',
        '🇸🇬 新加坡自动', '🇯🇵 日本机房', '🇯🇵 日本自动',
    ],
    '🧠 人工智能': [
        '🇺🇸 美国NTT自动', '🇺🇸 美国机房', '🇺🇸 美国自动',
        '🇸🇬 新加坡自动', '🇯🇵 日本机房', '🇯🇵 日本自动',
    ],
    '🇯🇵日本': ['🇯🇵 日本自动', '🇯🇵 日本机房'],
    '🎵 TikTok': [
        '🇯🇵 日本自动', '🇸🇬 新加坡自动', '🇺🇸 美国NTT自动',
        '🇯🇵日本', '🇸🇬 新加坡', '🇺🇸美国', '🚀 默认代理',
    ],
    '💻 开发工具': [
        '🇺🇸 美国NTT落地', '🇺🇸 美国NTT自动', '🇺🇸 美国机房',
        '🇯🇵 日本机房', '🇸🇬 新加坡', '🚀 默认代理',
    ],
    '👥 海外社交': [
        '🇺🇸 美国NTT落地', '🇺🇸 美国NTT自动', '🇺🇸 美国机房',
        '🇯🇵 日本机房', '🇸🇬 新加坡', '🚀 默认代理',
    ],
}


def _load(conn, name: str):
    row = db.one(conn, 'SELECT id,proxies FROM proxy_groups '
                       'WHERE variant_id=0 AND name=?', (name,))
    if row is None:
        raise SystemExit(f'missing canonical group: {name}')
    return row, json.loads(row['proxies'] or '[]')


def _canonicalize(conn, group_id: int, desired: list[str]) -> None:
    groups, nodes = node_refs.context(conn)
    refs = node_refs.legacy_refs(desired, variant_id=0, groups=groups,
                                 nodes=nodes)
    node_refs.canonical_group(conn, group_id, refs)


def apply_changes(conn) -> list[dict]:
    changes = []
    for name, desired in GROUP_MEMBERS.items():
        row, current = _load(conn, name)
        groups, nodes = node_refs.context(conn)
        stale_members = None
        members = node_refs.decoded(
            db.one(conn, 'SELECT members_v2 FROM proxy_groups WHERE id=?',
                   (row['id'],))['members_v2'], [])
        if members:
            try:
                stale_members = node_refs.resolve_refs(
                    members, variant_id=0, groups=groups, nodes=nodes)
            except ValueError:
                stale_members = ['<invalid>']
        if current != desired or stale_members != desired:
            _canonicalize(conn, row['id'], desired)
            security.audit(conn, 'codex-unified-variant', '收敛默认策略组类型引用',
                           'proxy_group', row['id'],
                           {'name': name, 'before_count': len(current),
                            'after_count': len(desired)})
            changes.append({'group': name, 'before_count': len(current),
                            'after_count': len(desired),
                            'canonicalized': stale_members != desired})
    variant = db.one(conn, 'SELECT id,enabled,note FROM variants WHERE id=1')
    if variant is None:
        raise SystemExit('legacy variant missing; rollback snapshot required')
    if variant['enabled']:
        conn.execute('UPDATE variants SET enabled=0,note=?,updated_at=? '
                     'WHERE id=1',
                     ('兼容窗已停用；旧链接由feed回退默认方案', db.now()))
        security.audit(conn, 'codex-unified-variant', '停用旧分流方案入口',
                       'variant', 1, {'kept_for_rollback': True})
        changes.append({'variant': '自建美日', 'enabled': False})
    return changes


def publish_changes() -> None:
    snapshot, policy_sha = builds.current_policy(db.connect())
    if not snapshot['targets']:
        raise SystemExit('no targets')
    build_id, status = builds.create_build(
        'codex-unified-variant', note='收敛默认方案并停用旧方案入口',
        snapshot=snapshot, policy_sha=policy_sha)
    with db.tx(immediate=True) as conn:
        build = db.one(conn, 'SELECT * FROM builds WHERE id=?', (build_id,))
        expected = {
            'testing': releases.revision(conn, releases.Env.TESTING),
            'production': releases.revision(conn, releases.Env.PRODUCTION),
        }
        idempotency = {
            'testing': f'unified-variant-{build_id}-testing',
            'production': f'unified-variant-{build_id}-production',
        }
        result = releases.publish_build(
            conn, build, 'codex-unified-variant',
            '收敛默认方案并保留旧链接兼容', releases.Env.PRODUCTION,
            expected_revisions=expected, idempotency_keys=idempotency)
    print(json.dumps({'build_id': build_id, 'build_status': status,
                      'release': result}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.publish and not args.apply:
        parser.error('--publish requires --apply')
    with db.tx(immediate=True) as conn:
        changes = apply_changes(conn)
    print(json.dumps({'changes': changes}, ensure_ascii=False))
    if args.publish:
        publish_changes()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
