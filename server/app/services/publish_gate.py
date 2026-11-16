"""发布票准备；消费由 releases 状态机在同一事务完成。"""
import json

from . import releases


def prepare_ticket(conn, build_id: int, *, env: str, now) -> dict:
    build = releases.get_build(conn, build_id) if hasattr(releases, 'get_build') else db_get(conn, build_id)
    current = releases.current(conn, env)
    if current and current['id'] == build_id:
        label = '测试版本' if env == 'testing' else '生产版本'
        raise releases.ReleaseError(f'该构建已是当前{label}')
    if not build:
        raise releases.ReleaseError('构建不存在')
    if build['verify_status'] != 'success':
        raise releases.ReleaseError('该构建未通过校验，不能发布')
    return {
        'build_id': int(build_id), 'env': str(env), 'manifest_sha': build['policy_sha'],
        'input_revisions': {'testing': releases.revision(conn, 'testing'),
                            'production': releases.revision(conn, 'production')},
        'expected_release_revision': releases.revision(conn, env),
        'quality_sha': build['policy_sha'], 'issued_at': now.isoformat(),
    }


def db_get(conn, build_id):
    from .. import db
    return db.one(conn, 'SELECT * FROM builds WHERE id=?', (build_id,))


def consume_ticket(conn, ticket: dict, *, expected_release_revision: int,
                   idempotency_key: str, actor_id: int, now) -> dict:
    """供状态机复用；实际校验和 revision 增量在 releases._switch 中完成。"""
    if expected_release_revision != ticket['expected_release_revision']:
        raise releases.ReleaseError('release_revision_changed')
    return {'ticket': ticket, 'idempotency_key': idempotency_key,
            'payload_sha': json.dumps({'build': ticket['build_id'], 'quality': ticket['quality_sha']},
                                      sort_keys=True, separators=(',', ':'))}
