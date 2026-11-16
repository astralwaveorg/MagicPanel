"""规则正文严格验证；count 不是资格。"""
import hashlib
import json

import yaml


class RuleContentError(ValueError):
    pass


# MetaCubeX 的 .mrs 是 zstd 压缩的二进制规则集，文件头是 zstd 帧 magic，
# 不是 "MRS" 文本头。按文本头判断会把所有 mrs 规则集判成非法。
MRS_MAGIC = bytes.fromhex('28b52ffd')


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def validate_rule_content(body: bytes, *, fmt: str, behavior: str,
                          engine_caps: dict) -> dict:
    body = bytes(body)
    fmt = fmt.lower()
    if not body or len(body) > 64 * 1024 * 1024:
        raise RuleContentError('rule_body_invalid')
    lowered = body[:512].lower()
    if b'<html' in lowered or b'<!doctype html' in lowered:
        raise RuleContentError('html_rejected')
    if fmt not in ('yaml', 'text', 'mrs'):
        raise RuleContentError('rule_format_invalid')
    if fmt == 'mrs':
        if behavior not in ('domain', 'ipcidr'):
            raise RuleContentError('mrs_behavior_invalid')
        if not body.startswith(MRS_MAGIC):
            raise RuleContentError('mrs_magic_invalid')
        count = 0
        semantic = {'format': fmt, 'behavior': behavior, 'magic': body[:4].hex()}
    elif fmt == 'yaml':
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            raise RuleContentError('yaml_parse_invalid') from exc
        if not isinstance(doc, dict) or not isinstance(doc.get('payload'), list):
            raise RuleContentError('yaml_structure_invalid')
        if any(not isinstance(item, (str, dict)) for item in doc['payload']):
            raise RuleContentError('yaml_structure_invalid')
        count = len(doc['payload'])
        semantic = {'format': fmt, 'behavior': behavior, 'payload': doc['payload']}
    else:
        lines = [line for line in body.decode('utf-8').splitlines() if line.strip()]
        count = len(lines)
        semantic = {'format': fmt, 'behavior': behavior, 'lines': lines}
    return {'body_sha': _sha(body), 'semantic_sha': hashlib.sha256(json.dumps(
        semantic, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'count': count, 'format': fmt, 'behavior': behavior,
        'validator_version': 'v1'}
