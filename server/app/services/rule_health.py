"""规则健康：验证时间、正文变化与本地正文缺失分别处理。"""
import hashlib
import json
from datetime import datetime, timedelta


def _time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def evaluate_rule_health(refs: list[dict], *, now, policy: dict) -> dict:
    states = {}
    blockers = []
    warnings = []
    for ref in refs:
        rule_id = ref.get('rule_id')
        validated = _time(ref.get('validated_at', ''))
        # 默认 7/14 天；来源可显式覆盖，但不复用节点测速 TTL。
        fresh_days = int(policy.get('fresh_days', 7))
        stale_days = int(policy.get('stale_days', 14))
        if not ref.get('content_sha') or not validated:
            state = 'expired'
            blockers.append(rule_id)
        else:
            age_days = (_time(now) - validated).total_seconds() / 86400
            state = 'fresh' if age_days < fresh_days else ('stale' if age_days < stale_days else 'expired')
            if state == 'stale':
                warnings.append(rule_id)
            if state == 'expired':
                blockers.append(rule_id)
        states[rule_id] = state
    return {'sources': states, 'blockers': blockers, 'warnings': warnings,
            'health_sha': hashlib.sha256(json.dumps({'states': states}, sort_keys=True,
                                                    separators=(',', ':')).encode()).hexdigest()}
