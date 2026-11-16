"""语义摘要；排序显式、浮点 NaN 拒绝。"""
import hashlib
import json


def digest(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


def fingerprints(*, eligibility: dict, plan: dict, build_input: dict) -> dict:
    """分层指纹：资格变化不等于计划变化，计划变化不等于构建输入变化。"""
    return {'eligibility_sha': digest(eligibility), 'plan_sha': digest(plan),
            'build_input_sha': digest(build_input)}
