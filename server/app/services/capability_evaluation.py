"""离线能力评估；只消费观测事实，不读时钟和网络。"""
from datetime import timedelta

from .fingerprints import digest


def evaluate(nodes: list[dict], observations: list[dict], *, evaluation_at,
             previous: dict | None = None) -> dict:
    by_node = {node['node_uid']: node for node in nodes}
    accepted = []
    for observation in observations:
        node = by_node.get(observation.get('node_uid'))
        if not node or observation.get('revision') != node.get('revision'):
            continue
        if not observation.get('path_qualified') or observation.get('result_state') != 'observed-ok':
            continue
        try:
            valid_until = __import__('datetime').datetime.fromisoformat(observation['valid_until'])
        except (KeyError, TypeError, ValueError):
            continue
        if valid_until <= evaluation_at:
            continue
        # 周资格沿用 7 天 fresh / 14 天 stale；这不能替代当前健康或 Google 耗尽证据。
        try:
            measured = __import__('datetime').datetime.fromisoformat(observation['measured_at'])
            age_days = max(0, (evaluation_at - measured).total_seconds() / 86400)
        except (KeyError, TypeError, ValueError):
            age_days = None
        accepted.append({
            'node_uid': observation['node_uid'], 'revision': observation['revision'],
            'scope': observation['scope'], 'observer_id': observation['observer_id'],
            'fresh': age_days is not None and age_days < 7,
            'stale': age_days is not None and 7 <= age_days < 14,
            'age_days': age_days,
        })
    # delay/带宽等性能噪声不进入资格语义；NodeKey 变化必须改变摘要。
    semantic = sorted(({'node_uid': item['node_uid'], 'revision': item['revision'],
                        'scope': item['scope'], 'observer_id': item['observer_id']}
                       for item in accepted), key=lambda item: (item['node_uid'], item['scope'],
                                                                item['observer_id']))
    return {'evaluation_at': evaluation_at.isoformat(), 'eligible': accepted,
            'eligibility_sha': digest({'nodes': semantic, 'schema': 'v1'})}
