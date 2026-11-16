"""内部节点材料与身份摘要，不生成或替换节点 UID。"""
import hashlib
import hmac
import ipaddress
import json
import math
import re

from ..schemas.nodes import is_secret_key
from ..security import derive_subkey


KEY_VERSION = 1


def _json_copy(value):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [_json_copy(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _json_copy(item) for key, item in value.items()}
    raise ValueError


def _server(value):
    if type(value) is not str or not value or value != value.strip() or '%' in value:
        raise ValueError
    host = value
    if host.startswith('[') and host.endswith(']'):
        return str(ipaddress.IPv6Address(host[1:-1]))
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    host = host.encode('idna').decode('ascii').lower().removesuffix('.')
    if (len(host) > 253 or not host or
            any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                for label in host.split('.'))):
        raise ValueError
    # ASCII ACE 标签编码时会被直接放行，解码往返才能验证其 IDNA 语义。
    if host.encode('ascii').decode('idna').encode('idna').decode('ascii') != host:
        raise ValueError
    return host


def _serialize(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def canonical_material(proxy: dict) -> dict:
    """移除明确展示元数据，其余连接材料完整保留。返回值仅供内部使用。"""
    try:
        if type(proxy) is not dict:
            raise ValueError
        material = _json_copy(proxy)
        material.pop('name', None)
        material.pop('x-magicpanel', None)
        material['server'] = _server(material.get('server'))
        protocol = material.get('type')
        if type(protocol) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', protocol):
            raise ValueError
        material['type'] = protocol.lower()
        port = material.get('port')
        # Hysteria2 允许 port-hopping：订阅只给 ports range，客户端据此随机选口。
        # 目录身份用首个可用端口作为稳定投影，原始 ports 仍完整保留在材料中。
        if port is None and material['type'] == 'hysteria2':
            match = re.fullmatch(r'([0-9]{1,5})(?:-([0-9]{1,5}))?', str(material.get('ports', '')))
            if match:
                low, high = int(match.group(1)), int(match.group(2) or match.group(1))
                if 1 <= low <= 65535 and 1 <= high <= 65535 and low <= high:
                    port = low
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError
        material['port'] = port
        _serialize(material)
        return material
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('catalog_material_invalid') from None


def derive_catalog_key(master: bytes, version: int = 1) -> bytes:
    return derive_subkey(master, purpose='node-identity', version=version)


def _without_auth(value):
    if isinstance(value, dict):
        return {key: _without_auth(item) for key, item in value.items()
                if not is_secret_key(key)}
    if isinstance(value, list):
        return [_without_auth(item) for item in value]
    return value


def fingerprints(proxy: dict, *, source_id: int | None, key: bytes) -> dict:
    """身份可对应多个账号；调用方不得对 identity_hmac 建唯一约束。"""
    try:
        if not isinstance(key, bytes) or not key:
            raise ValueError
        if source_id is not None and (type(source_id) is not int or source_id < 1):
            raise ValueError
        material = canonical_material(proxy)
        identity = {'source_id': source_id, 'material': _without_auth(material)}
        return {
            'identity_hmac': hmac.new(key, _serialize(identity), hashlib.sha256).hexdigest(),
            'material_hmac': hmac.new(key, _serialize(material), hashlib.sha256).hexdigest(),
            'key_version': KEY_VERSION,
        }
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('catalog_material_invalid') from None
