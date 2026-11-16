"""只允许已实现的运行档案；不接受额外 YAML 覆盖层。"""
from copy import deepcopy

GOOGLE_CONSTRAINT = {
    'country_tiers': ['US', 'SG', 'JP'],
    'advance_requires': 'all_confirmed_failed',
    'allow_direct': False,
    'unknown_is_failure': False,
}

_LEGACY = {
    'id': 'legacy-v1', 'version': 1, 'baseline_id': 'legacy-v1',
    'engines': ['stash', 'mihomo'],
    'platforms': ['', 'ios', 'macos', 'tvos', 'windows', 'android', 'linux'],
    'dns_owner': 'engine_default', 'listener_owner': 'engine_default',
    'business_constraints_enforced': False,
    'google_constraint': GOOGLE_CONSTRAINT,
    'recovery_policy': None, 'execution_capabilities': [],
}


def get_profile(profile_id: str, *, engine: str, platform: str = '') -> dict:
    if (profile_id != 'legacy-v1' or engine not in _LEGACY['engines']
            or platform not in _LEGACY['platforms']):
        raise ValueError('runtime_profile_invalid')
    return deepcopy(_LEGACY)


def effective_profile(target: dict, device: dict | None = None) -> dict:
    if not isinstance(target, dict):
        target = dict(target)
    if device is not None and not isinstance(device, dict):
        device = dict(device)
    selected = target.get('default_runtime_profile', 'legacy-v1')
    if device and device.get('runtime_profile') is not None:
        selected = device['runtime_profile']
    return get_profile(selected, engine=target['engine'], platform=target.get('platform') or '')
