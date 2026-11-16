"""路由解释只使用已有事实；解析/ASN 缺失标 unknown，不主动反查。"""
import fnmatch


def _matches(rule: dict, query: dict) -> bool | None:
    host = (query.get('host') or '').lower()
    kind = rule.get('type')
    value = rule.get('value') or ''
    if kind == 'DOMAIN':
        return host == value.lower()
    if kind == 'DOMAIN-SUFFIX':
        return host == value.lower() or host.endswith('.' + value.lower())
    if kind == 'DOMAIN-KEYWORD':
        return value.lower() in host
    if kind in ('DOMAIN-WILDCARD', 'DOMAIN-REGEX', 'GEOSITE'):
        return None
    if kind == 'IP-ASN':
        asn = query.get('dst_asn')
        return str(value.lstrip('AS').lower()) == str(asn).lower() if asn is not None else None
    if kind in ('IP-CIDR', 'IP-CIDR6', 'GEOIP', 'IP- cidr'):
        return None if not query.get('dst_ip') else None
    if kind in ('DST-PORT', 'SRC-PORT'):
        try:
            ports = {int(item) for item in str(value).replace('/', '-').split('-') if item.isdigit()}
            if '-' in value and len(ports) == 2:
                port = int(query.get('dst_port', -1))
                low, high = min(ports), max(ports)
                return low <= port <= high
            return int(query.get('dst_port', -1)) in ports
        except (TypeError, ValueError):
            return False
    if kind == 'MATCH':
        return True
    return None


def explain_route(snapshot: dict, query: dict, facts: dict) -> dict:
    merged = {**query, **facts}
    stages = []
    matched_rule = None
    limitations = []
    for rule in snapshot.get('rules', []):
        if not rule.get('enabled', True):
            continue
        verdict = _matches(rule, merged)
        state = 'match' if verdict is True else ('unknown' if verdict is None else 'miss')
        stages.append({'rule_id': rule.get('id'), 'type': rule.get('type'), 'state': state})
        if verdict is True:
            matched_rule = rule
            break
        if verdict is None:
            if rule.get('type') == 'IP-ASN':
                limitations.append('dst_asn unavailable; prior IP-ASN cannot be resolved without DNS')
            else:
                limitations.append(f"{rule.get('type')} cannot be evaluated from supplied facts")
            break
    return {'matched_rule': matched_rule, 'stages': stages,
            'limitations': limitations, 'facts': facts}
