"""DNS 规则意图规范化和受控 AGH 输出。"""
import hashlib
import json


class IntentError(ValueError):
    pass


def normalize_domain(value: str) -> str:
    value = (value or '').rstrip('.').lower()
    if not value or '*' in value or '/' in value:
        raise ValueError('invalid_dns_domain')
    if len(value.split('.')) < 2:
        raise ValueError('invalid_dns_domain')
    return value.encode('idna').decode('ascii')


def normalize_intent(entries: list[dict], *, version: str) -> dict:
    output = []
    for index, entry in enumerate(entries):
        kind = entry.get('kind')
        domain = normalize_domain(entry.get('domain', ''))
        resolver = entry.get('resolver')
        priority = entry.get('priority')
        if kind not in ('exact', 'suffix') or not resolver or type(priority) is not int:
            raise IntentError('dns_intent_invalid')
        output.append({'kind': kind, 'domain': domain, 'resolver': resolver,
                       'priority': priority,
                       'business': entry.get('business', ''),
                       'reason': entry.get('reason', ''),
                       'source_revision': entry.get('source_revision', '')})
    return {'version': version, 'entries': sorted(output, key=lambda item: (
        item['domain'], item['kind'], item['priority'], item['resolver']))}


def compile_agh(intent: dict, *, capabilities: dict) -> dict:
    if intent.get('version') != '1':
        raise IntentError('dns_intent_version_invalid')
    rules = []
    for entry in intent['entries']:
        if entry['kind'] == 'exact' and not capabilities.get('exact'):
            raise IntentError('exact_not_supported')
        if entry['kind'] == 'suffix' and not capabilities.get('suffix'):
            raise IntentError('suffix_not_supported')
        rules.append({'domain': entry['domain'], 'resolver': entry['resolver'],
                      'kind': entry['kind'], 'priority': entry['priority']})
    return {'adapter': 'agh', 'adapter_version': '1', 'rules': rules}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()
