"""探测预算与来源公平轮转；不读取数据库。"""
from .recovery_policy import defaults


def _quantity(value: dict, key: str) -> int:
    number = value.get(key, 0)
    if type(number) is not int or number < 0:
        raise ValueError('probe_budget_invalid')
    return number


def shared_remaining(policy: dict, usage: dict, reserved: dict) -> dict:
    """子预算受连续7天共享池限制；已用与未结算预约都占额。"""
    shared = policy['shared']
    used_r = sum(_quantity(item, 'requests') for item in usage.values())
    used_b = sum(_quantity(item, 'bytes') for item in usage.values())
    reserved_r = sum(_quantity(item, 'requests') for item in reserved.values())
    reserved_b = sum(_quantity(item, 'bytes') for item in reserved.values())
    result = {}
    for kind in ('deep', 'recovery_expand', 'daily_region', 'sentinel', 'event',
                 'media_quality', 'per_device_estimate'):
        limit = policy.get(kind)
        if not limit:
            continue
        result[kind] = {
            'requests': max(0, min(_quantity(limit, 'requests') - _quantity(usage.get(kind, {}), 'requests') - _quantity(reserved.get(kind, {}), 'requests'),
                                   shared['requests'] - used_r - reserved_r)),
            'bytes': max(0, min(_quantity(limit, 'bytes') - _quantity(usage.get(kind, {}), 'bytes') - _quantity(reserved.get(kind, {}), 'bytes'),
                                shared['bytes'] - used_b - reserved_b)),
        }
    result['shared'] = {'requests': max(0, shared['requests'] - used_r - reserved_r),
                        'bytes': max(0, shared['bytes'] - used_b - reserved_b)}
    return result


def round_robin(buckets: dict[str, list[str]]) -> list[str]:
    """按 bucket 名稳定轮转，本地与每个来源都不被连续刷屏。"""
    queues = {key: list(values) for key, values in sorted(buckets.items())}
    ordered = []
    while any(queues.values()):
        for key in queues:
            if queues[key]:
                ordered.append(f'{key}:{queues[key].pop(0)}')
    return ordered
