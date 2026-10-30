"""规则顺序不变量：约束 21/33 的构建期强制。

整张规则表由界面排布，但有几组相对关系是路由正确性的地基（尾部直连块、
子集合早于父集合、代理兜底早于 cn/cn-ip、MATCH 最后）。这里用合成快照
直接测 validate_policy 的不变量检查：破坏任何一组都要在构建期报错，
而不是等用户发现某个国内服务走错了出口。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.compiler import validate  # noqa: E402

_ALL = {"targets": ["*"], "devices": ["*"], "enabled": True}
_PROVIDERS = [
    "ai-cn", "openai", "anthropic", "category-ai-chat-!cn",
    "apple-cn", "apple", "microsoft-cn", "microsoft",
    "games-cn", "games", "steam-cn", "cn", "cn-ip", "direct", "private-ip",
    "aws", "cloudflare", "proxy-bm7",
]


def _rset(value, target="DIRECT"):
    return {"type": "RULE-SET", "value": value, "target": target, **_ALL}


def _snapshot(rules):
    return {
        "sources": [],
        "groups": [],
        "rule_providers": [{"name": n, "enabled": True, "behavior": "domain"}
                           for n in _PROVIDERS],
        "local_nodes": [],
        "snippets": [],
        "rules": rules,
    }


def _compliant_rules():
    """与线上设计一致的顺序骨架（节选）：不变量检查必须放行。"""
    return [
        _rset("ai-cn"), _rset("apple-cn"), _rset("microsoft-cn"),
        _rset("games-cn"),
        {"type": "AND", "value": "((NETWORK,udp),(DST-PORT,443))",
         "target": "REJECT", **_ALL},
        {"type": "MATCH", "value": "", "target": "DIRECT", **_ALL},
    ]


def test_compliant_order_passes():
    errors, _ = validate.validate_policy(_snapshot(_compliant_rules()))
    assert not [e for e in errors if "约束 21" in e or "约束 33" in e], errors
    # AND 逻辑规则在通用白名单里，不再报"规则类型不支持"
    assert not [e for e in errors if "规则类型不支持" in e], errors


def test_child_after_parent_is_build_error():
    rules = [
        _rset("games"), _rset("games-cn"),          # 父集合跑到了子集合前面
        {"type": "MATCH", "value": "", "target": "DIRECT", **_ALL},
    ]
    errors, _ = validate.validate_policy(_snapshot(rules))
    assert any("games-cn" in e and "games" in e and "父集合" in e for e in errors), errors


def test_tail_block_disorder_is_build_error():
    rules = [
        _rset("cn-ip"), _rset("cn"),                # 顺序颠倒
        {"type": "MATCH", "value": "", "target": "DIRECT", **_ALL},
    ]
    errors, _ = validate.validate_policy(_snapshot(rules))
    assert any("尾部直连块顺序错误" in e for e in errors), errors


def test_rule_after_match_left_to_renderer():
    """兜底错位由渲染器自动归位并告警（既有设计），策略级不报错。"""
    rules = [
        {"type": "MATCH", "value": "", "target": "DIRECT", **_ALL},
        _rset("cn"),                                # 排到兜底后面
    ]
    errors, _ = validate.validate_policy(_snapshot(rules))
    assert not [e for e in errors if "兜底规则之后" in e], errors
    # 但尾部直连块的不变量仍然生效（cn 在 MATCH 之后 = 尾块顺序被破坏）
    assert any("尾部直连块顺序错误" in e for e in errors), errors


def test_cloud_fallback_after_cn_is_build_error():
    rules = [
        _rset("cn"), _rset("aws"),                  # 云服务商被国内直连抢先
        _rset("cn-ip"),
        {"type": "MATCH", "value": "", "target": "DIRECT", **_ALL},
    ]
    errors, _ = validate.validate_policy(_snapshot(rules))
    assert any("aws" in e and "cn/cn-ip" in e for e in errors), errors
