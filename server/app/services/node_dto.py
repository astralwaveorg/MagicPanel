"""安全节点读取与显式凭据 patch 合同。"""
from copy import deepcopy
import json

from .. import security
from ..schemas.nodes import split_parameters, parameter_fields

PATCH_FIELDS = {'public_params', 'secret_set', 'secret_clear', 'extra_yaml', 'clear_extra_yaml'}


def _merge_mapping(current: dict, patch: dict) -> dict:
    result = deepcopy(current)
    for key, value in patch.items():
        result[key] = _merge_mapping(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else deepcopy(value)
    return result


def merge_configuration(current: dict, patch: dict) -> dict:
    if set(patch) - PATCH_FIELDS:
        raise ValueError('未知配置字段')
    result = deepcopy(current)
    public = patch.get('public_params', {})
    setting = patch.get('secret_set', {})
    clearing = patch.get('secret_clear', [])
    if not isinstance(public, dict) or not isinstance(setting, dict) or not isinstance(clearing, list) or any(not isinstance(k, str) for k in clearing):
        raise ValueError('配置 patch 类型错误')
    if set(setting) & set(clearing):
        raise ValueError('秘密字段不能同时设置与清空')
    if patch.get('clear_extra_yaml') and 'extra_yaml' in patch:
        raise ValueError('高级 YAML 不能同时设置与清空')
    result['public_params'] = _merge_mapping(result.get('public_params', {}), public)
    result['secrets'] = _merge_mapping(result.get('secrets', {}), setting)
    for key in clearing:
        result['secrets'].pop(key, None)
    if patch.get('clear_extra_yaml'):
        result['extra_yaml'] = ''
    elif 'extra_yaml' in patch:
        if not isinstance(patch['extra_yaml'], str):
            raise ValueError('高级 YAML 必须为文本')
        result['extra_yaml'] = patch['extra_yaml']
    return result


def configuration(protocol: str, params: dict, extra_yaml: str = '') -> dict:
    public, secrets = split_parameters(protocol, params)
    return {'public_params': public, 'secrets': secrets, 'extra_yaml': extra_yaml}


def reveal_configuration(row) -> dict:
    return {'params': json.loads(security.decrypt_text(row['params_enc']) if row['params_enc'] else '{}'),
            'extra_yaml': security.decrypt_text(row['extra_yaml_enc']) if row['extra_yaml_enc'] else ''}


def node_summary(row) -> dict:
    from .local_nodes import display_name
    data = {key: row[key] for key in ('id', 'name', 'node_type', 'protocol', 'server', 'port', 'sort', 'created_at', 'updated_at')}
    data.update(enabled=bool(row['enabled']), display_name=display_name(row['name'], row['node_type'] or ''), test_status=row['test_status'] or '', test_delay=row['test_delay'] or 0, tested_at=row['tested_at'] or '')
    config = reveal_configuration(row)
    public, secrets = split_parameters(row['protocol'], config['params'])
    fields = sorted(k for k, v in secrets.items() if v not in ('', None, {}, []))
    data.update(public_params=public, has_credentials=bool(fields), configured_secret_fields=fields, has_extra_yaml=bool(config['extra_yaml']))
    return data


def validate_patch(protocol: str, patch: dict) -> None:
    fields = parameter_fields(protocol)
    if protocol != 'custom' and (set(patch.get('public_params', {})) | set(patch.get('secret_set', {})) | set(patch.get('secret_clear', []))) - fields:
        raise ValueError('未知协议参数字段')
    public, secret = split_parameters(protocol, patch.get('public_params', {}))
    if secret:
        raise ValueError('秘密参数必须使用 secret_set')
    if split_parameters(protocol, patch.get('secret_set', {}))[0]:
        raise ValueError('公开参数必须使用 public_params')
