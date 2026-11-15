"""三层配置解析；合并语义只复用 base_config。"""
from copy import deepcopy
import hashlib
import json
import yaml

from . import base_config, runtime_profiles


def resolve_layers(*, engine: str, platform: str = '', device_id: int = 0,
                   docs: dict | None = None, runtime_profile: str = 'legacy-v1') -> dict:
    profile = runtime_profiles.get_profile(runtime_profile, engine=engine, platform=platform)
    try:
        if type(device_id) is not int or device_id < 0 or (device_id and not platform):
            raise ValueError
        if docs is not None and type(docs) is not dict:
            raise ValueError
        docs = docs or {}
        baseline = base_config.default_doc(engine)
        layers = base_config.scope_layers(engine, platform, device_id, docs)
        inherited = (baseline if not platform and not device_id
                     else base_config.cascade(layers[:-1])[0])
        effective, provenance = base_config.cascade(layers)
        overlay = docs.get((engine, platform, device_id)) or {}
        if type(overlay) is not dict:
            raise ValueError
        inputs = {'engine': engine, 'platform': platform, 'device_id': device_id,
                  'baseline': baseline, 'layers': layers, 'profile': profile}
        raw = json.dumps(inputs, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
        return {
            'engine': engine, 'platform': platform, 'device_id': device_id,
            'runtime_profile': profile['id'], 'profile_version': profile['version'],
            'inherited': deepcopy(inherited), 'overlay': deepcopy(overlay),
            'effective': effective, 'provenance': provenance,
            'input_sha256': hashlib.sha256(raw).hexdigest(),
        }
    except (TypeError, ValueError, KeyError, RecursionError, OverflowError):
        raise ValueError('config_resolution_invalid') from None


def apply_device_overlay(text: str, overlay_yaml: str) -> str:
    """设备级个性化：在目标产物之上叠加该设备自己的扩展 YAML。

    合并语义与「基础配置」的分层完全一致：字典递归、列表**追加**、标量覆盖。
    设备层是"个性化"语义：保存的是与上层的差异，列表只记新增项，
    因此这里用追加语义——下发结果 = 平台产物 + 这台设备新增的内容。

    结构键（节点 / 策略组 / 规则等）不允许被设备覆盖：
    列表是追加语义，写在兜底规则之后永不生效，还会让客户端加载失败。
    """
    overlay_yaml = (overlay_yaml or "").strip()
    if not overlay_yaml:
        return text
    overlay = yaml.safe_load(overlay_yaml) or {}
    if not isinstance(overlay, dict):
        return text
    for key in base_config.PROTECTED_KEYS:
        if key in overlay:
            raise ValueError(f"设备扩展不允许覆盖结构键：{key}")
    cfg = yaml.safe_load(text) or {}
    if not isinstance(cfg, dict):
        return text
    merged = base_config.merge_docs(
        cfg, overlay, base_config.LIST_APPEND)
    return yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=4096)
