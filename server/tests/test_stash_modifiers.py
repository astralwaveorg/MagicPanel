"""Stash 专属修饰符：no-track 与 pre-matching。

这两个参数 Mihomo 不认（它的规则参数只有 no-resolve 与 src），所以：
- 产物里只有 Stash 平台带这两个修饰符；
- pre-matching 的目标必须是 REJECT / REJECT-DROP 字面量，用策略组会让客户端加载失败；
- pre-matching 只能用在"连接建立前就能判断"的规则类型上；
- 兜底规则（MATCH）不能加 no-track，否则客户端不记录任何连接。
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from conftest import setup_admin, auth_headers  # noqa: E402


def make_group(client, csrf, name="广告过滤"):
    h = auth_headers(csrf)
    r = client.post("/api/v1/groups", headers=h, json={
        "name": name, "type": "select", "proxies": ["REJECT"], "use_sources": [],
    })
    assert r.status_code == 201, r.text


def create_rule(client, csrf, **kw):
    h = auth_headers(csrf)
    body = {"type": "DOMAIN-SUFFIX", "value": "ads.example.com", "target": "DIRECT"}
    body.update(kw)
    return client.post("/api/v1/rules", headers=h, json=body)


def test_no_track_and_pre_matching_saved(client):
    """勾上的修饰符要存进库里，并在接口返回里体现。"""
    csrf = setup_admin(client)
    r = create_rule(client, csrf, target="REJECT", no_track=True, pre_matching=True)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["no_track"] is True
    assert data["pre_matching"] is True


def test_pre_matching_rejects_group_target(client):
    """pre-matching 的目标用策略组会让客户端加载失败，接口必须拦。"""
    csrf = setup_admin(client)
    make_group(client, csrf)
    r = create_rule(client, csrf, target="广告过滤", pre_matching=True)
    assert r.status_code == 400, r.text
    assert "REJECT" in r.text


def test_pre_matching_rejects_process_rule(client):
    """进程类规则依赖建连后的信息，不能用 pre-matching。"""
    csrf = setup_admin(client)
    r = create_rule(client, csrf, type="PROCESS-NAME", value="curl",
                    target="REJECT", pre_matching=True)
    assert r.status_code == 400, r.text


def test_match_cannot_have_no_track(client):
    """兜底规则加 no-track 等于让客户端不记录任何连接。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT", "no_track": True})
    assert r.status_code == 400, r.text


def test_batch_skips_ineligible_pre_matching(client):
    """批量开 pre-matching：目标不合规的规则要跳过并说明原因。"""
    csrf = setup_admin(client)
    make_group(client, csrf)
    ok = create_rule(client, csrf, target="REJECT").json()
    bad = create_rule(client, csrf, target="广告过滤",
                      value="ads2.example.com").json()
    h = auth_headers(csrf)
    r = client.patch("/api/v1/rules/batch", headers=h, json={
        "ids": [ok["id"], bad["id"]], "pre_matching": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["updated"] == 1
    assert any(s["id"] == bad["id"] for s in data["skipped"])


def test_render_only_stash_carries_modifiers(client):
    """产物里只有 Stash 带这两个修饰符，Mihomo 产物保持干净。"""
    from app.compiler import render

    snapshot = {
        "sources": [],
        "groups": [],
        "rule_providers": [],
        "rules": [
            {"type": "RULE-SET", "value": "ads", "target": "REJECT",
             "enabled": True, "no_resolve": False, "no_track": True,
             "pre_matching": True, "targets": ["*"], "devices": ["*"]},
            {"type": "MATCH", "value": "", "target": "DIRECT", "enabled": True,
             "targets": ["*"], "devices": ["*"]},
        ],
        "snippets": [],
    }
    stash = yaml.safe_load(render.render_target(
        snapshot, {"name": "t", "engine": "stash", "extra_yaml": ""}))
    mihomo = yaml.safe_load(render.render_target(
        snapshot, {"name": "t", "engine": "mihomo", "extra_yaml": ""}))

    # rules[0] 是置顶的 FEED 域名直连规则，随后是基线里的个人直连域名
    # （_direct_domains 已固化到引擎默认配置），用户规则从其后开始
    from app.services import base_config as bc
    personal = bc.normalize_domains(
        bc.default_doc("stash").get(bc.DIRECT_DOMAINS_KEY))
    offset = 1 + len(personal)
    assert stash["rules"][1] == "DOMAIN-SUFFIX,magichub.top,DIRECT"
    assert stash["rules"][offset] == "RULE-SET,ads,REJECT,no-track,pre-matching"
    assert mihomo["rules"][offset] == "RULE-SET,ads,REJECT"
    # 兜底规则永远不带修饰符
    assert stash["rules"][-1] == "MATCH,DIRECT"


def test_validate_blocks_pre_matching_with_group_target():
    """策略层校验：pre-matching 目标不是 REJECT 字面量时构建期就要报错。"""
    from app.compiler import validate

    snapshot = {
        "sources": [],
        "groups": [{"name": "广告过滤", "type": "select", "proxies": ["REJECT"],
                    "use_sources": [], "targets": ["*"], "devices": ["*"]}],
        "rule_providers": [],
        "rules": [
            {"type": "RULE-SET", "value": "ads", "target": "广告过滤",
             "enabled": True, "no_track": False, "pre_matching": True,
             "targets": ["*"], "devices": ["*"]},
            {"type": "MATCH", "value": "", "target": "DIRECT", "enabled": True,
             "targets": ["*"], "devices": ["*"]},
        ],
        "snippets": [],
    }
    errors, _ = validate.validate_policy(snapshot)
    assert any("pre-matching" in e for e in errors), errors


def test_same_ruleset_on_disjoint_platforms_is_not_duplicate():
    """同一规则集在互斥的引擎平台各一条，不该报"规则重复"。"""
    from app.compiler import validate

    base = {
        "sources": [],
        "groups": [],
        "rule_providers": [{"name": "ads", "enabled": True}],
        "snippets": [],
    }
    disjoint = dict(base, rules=[
        {"type": "RULE-SET", "value": "ads", "target": "REJECT", "enabled": True,
         "no_track": False, "pre_matching": True,
         "targets": ["Stash-iOS"], "devices": ["*"]},
        {"type": "RULE-SET", "value": "ads", "target": "DIRECT", "enabled": True,
         "no_track": False, "pre_matching": False,
         "targets": ["Mihomo-Android"], "devices": ["*"]},
        {"type": "MATCH", "value": "", "target": "DIRECT", "enabled": True,
         "targets": ["*"], "devices": ["*"]},
    ])
    _, warnings = validate.validate_policy(disjoint)
    assert not any("规则重复" in w for w in warnings), warnings

    overlapping = dict(base, rules=[
        {"type": "RULE-SET", "value": "ads", "target": "REJECT", "enabled": True,
         "no_track": False, "pre_matching": True,
         "targets": ["Stash-iOS"], "devices": ["*"]},
        {"type": "RULE-SET", "value": "ads", "target": "DIRECT", "enabled": True,
         "no_track": False, "pre_matching": False,
         "targets": ["*"], "devices": ["*"]},
        {"type": "MATCH", "value": "", "target": "DIRECT", "enabled": True,
         "targets": ["*"], "devices": ["*"]},
    ])
    _, warnings = validate.validate_policy(overlapping)
    assert any("规则重复" in w for w in warnings), warnings
