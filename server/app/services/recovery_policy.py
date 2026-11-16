"""auto_stable_v1 唯一数字合同；服务层只消费这里，不复制阈值。"""
import math


def defaults() -> dict:
    return {
        'mode': 'auto_stable_v1',
        'schedule': {
            'weekly': {'weekday': 0, 'hour': 4, 'minute': 0},
            'daily_region': {'hour': 8, 'minute': 0},
            'sentinel_seconds': 300,
        },
        'detection': {
            'region_samples': 3,
            'region_pass_ratio': 0.5,
            'region_confirm_delay_seconds': 600,
            'region_expand_limit_hours': 24,
            'global_min_regions_factor': 0.5,
            'global_min_regions_floor': 2,
            'global_expand_limit_hours': 72,
            'hard_failure_confirmations': 2,
            'hard_failure_interval_seconds': 30,
            'untrusted_states': frozenset({'unknown', 'stale', 'skipped', 'rate-limited'}),
        },
        'recovery': {
            'backup_candidates': 2,
            'requests_per_candidate': 2,
            'wall_clock_seconds': 30,
            'hold_seconds': 1800,
            'switch_limit': 3,
            'switch_window_seconds': 600,
            'google_upgrade_confirmations': 2,
            'google_upgrade_interval_seconds': 600,
            'google_evidence_valid_hours': 24,
        },
        'google': {'order': ['US', 'SG', 'JP']},
        'budgets': {
            'shared': {'requests': 30000, 'bytes': 2_500_000_000},
            'deep': {'requests': 8000, 'bytes': 768 * 1024 * 1024},
            'recovery_expand': {'requests': 8000, 'bytes': 768 * 1024 * 1024},
            'daily_region': {'requests': 512, 'bytes': 16 * 1024 * 1024},
            'sentinel': {'requests': 10000, 'bytes': 96 * 1024 * 1024},
            'event': {'requests': 512, 'bytes': 32 * 1024 * 1024},
            'media_quality': {'requests': 64, 'bytes': 64 * 1024 * 1024},
            'per_device_estimate': {'requests': 10000, 'bytes': 96 * 1024 * 1024},
        },
    }


def region_action(samples: list[dict], *, control_ok: bool, policy: dict) -> str:
    """地区抽样只投可判定票；unknown/限流不能把节点判死。"""
    if not control_ok:
        return 'measurement_degraded'
    untrusted = policy['detection']['untrusted_states']
    threshold = policy['detection']['region_pass_ratio']
    votes = [item.get('state') for item in samples if item.get('state') not in untrusted]
    passed = sum(state == 'observed-ok' for state in votes)
    failed = len(votes) - passed
    if not votes or failed == len(votes):
        return 'measurement_degraded'
    if passed > len(votes) * threshold:
        return 'keep'
    return 'confirm_region'


def global_region_limit(region_count: int, policy: dict) -> int:
    return max(policy['detection']['global_min_regions_floor'],
               math.ceil(region_count * policy['detection']['global_min_regions_factor']))
