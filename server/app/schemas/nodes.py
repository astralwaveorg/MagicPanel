"""节点参数的唯一保密策略；未知字段默认保密。"""
from copy import deepcopy

SECRET_KEYS = frozenset({'password', 'uuid', 'auth', 'psk', 'private-key', 'private_key', 'username', 'token', 'obfs_password', 'obfs-password', 'protocol_param', 'protocol-param', 'authorization', 'proxy-authorization', 'cookie', 'set-cookie'})


def is_secret_key(key: str) -> bool:
    return key.lower().replace('_', '-') in {k.replace('_', '-') for k in SECRET_KEYS}


def contains_secret(value) -> bool:
    if isinstance(value, dict):
        return any(is_secret_key(k) or contains_secret(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_secret(v) for v in value)
    return False


def public_parameter_fields(protocol: str) -> frozenset[str]:
    from ..services.local_nodes import PROTOCOLS
    if protocol == "custom":
        return frozenset()
    return frozenset(f['key'] for f in PROTOCOLS.get(protocol, {}).get('fields', []) if f['type'] != 'password' and not is_secret_key(f['key']))


def split_parameters(protocol: str, params: dict) -> tuple[dict, dict]:
    allowed = public_parameter_fields(protocol)
    public, secrets = {}, {}
    for key, value in params.items():
        target = public if protocol != 'custom' and key in allowed and not isinstance(value, (dict, list)) else secrets
        target[key] = deepcopy(value)
    return public, secrets


def parameter_fields(protocol: str) -> frozenset[str]:
    from ..services.local_nodes import PROTOCOLS
    return frozenset(f['key'] for f in PROTOCOLS.get(protocol, {}).get('fields', []))
