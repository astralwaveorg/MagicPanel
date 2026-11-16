"""编译语义门禁；错误返回稳定 path/code/reason。"""
from .. import config


GOOGLE_ENDPOINTS = frozenset({'www.google.com', 'mail.google.com', 'www.youtube.com',
                              'gemini.google.com'})


def is_google_endpoint(host: str) -> bool:
    return (host or '').lower().rstrip('.') in GOOGLE_ENDPOINTS


def validate_semantics(snapshot: dict, *, engine: str, capabilities: dict) -> list[dict]:
    errors = []
    max_interval = config.MAX_CHECK_INTERVAL
    for index, group in enumerate(snapshot.get('groups', [])):
        interval = int(group.get('interval', 0))
        if interval < 0 or interval > max_interval:
            errors.append({'code': 'interval_range', 'path': f'groups[{index}].interval',
                           'reason': '0..604800'})
        if engine == 'mihomo' and group.get('type') == 'relay':
            errors.append({'code': 'relay_unsupported', 'path': f'groups[{index}].type',
                           'reason': 'mihomo'})
    for index, provider in enumerate(snapshot.get('rule_providers', [])):
        if provider.get('format') == 'mrs' and provider.get('behavior') not in ('domain', 'ipcidr'):
            errors.append({'code': 'mrs_behavior_invalid',
                           'path': f'rule_providers[{index}].behavior',
                           'reason': str(provider.get('behavior'))})
    return errors


def validate_google_graph(graph: dict, plan: dict) -> list[dict]:
    google_id = str(plan.get('google_group_id'))
    groups = {str(group['id']): group for group in graph.get('groups', [])}
    errors = []

    def walk(group_id: str, path: list[str], visiting: set[str]) -> bool:
        if group_id in visiting:
            errors.append({'code': 'google_cycle', 'path': ' -> '.join(path + [group_id]),
                           'reason': 'cycle'})
            return True
        group = groups.get(group_id)
        if group is None:
            errors.append({'code': 'google_group_missing', 'path': ' -> '.join(path),
                           'reason': group_id})
            return True
        if not group.get('members'):
            errors.append({'code': 'google_empty_pool', 'path': f'groups[{group_id}]',
                           'reason': 'empty'})
            return True
        hit_leaf = False
        for index, member in enumerate(group['members']):
            member_path = f'groups[{group_id}].members[{index}]'
            if member.get('kind') == 'builtin' and member.get('ref') in {'DIRECT', 'COMPATIBLE'}:
                errors.append({'code': 'google_direct_leaf', 'path': member_path,
                               'reason': member.get('ref')})
                hit_leaf = True
            elif member.get('kind') == 'group':
                hit_leaf |= walk(str(member.get('ref')), path + [group_id],
                                 visiting | {group_id})
        return hit_leaf

    if google_id in groups:
        walk(google_id, [], set())
    else:
        errors.append({'code': 'google_group_missing', 'path': 'groups', 'reason': google_id})
    return errors
