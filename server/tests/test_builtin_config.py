"""引擎默认配置可覆盖、可恢复默认的回归测试。"""
import yaml

from conftest import auth_headers, setup_admin
from test_api import make_policy


def _yaml(doc):
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def test_builtin_default_is_editable_and_resettable(client):
    csrf = setup_admin(client)
    hdr = auth_headers(csrf)

    # 默认值可读
    resp = client.get("/api/v1/base-config?engine=stash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["readonly"] is False
    origin_mode = data["effective"]["mode"]

    # 改一个键 → 只把与默认值的差异记下来
    doc = dict(data["effective"])
    doc["mode"] = "global" if origin_mode != "global" else "rule"
    resp = client.put("/api/v1/base-config?engine=stash",
                      json={"content": _yaml(doc), "updated_at": data.get("updated_at", "")},
                      headers=hdr)
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved["overlay"].get("mode") == doc["mode"]
    assert len(saved["overlay"]) == 1, "只应保存与默认值不同的差异"
    assert saved["effective"]["mode"] == doc["mode"]

    # 引擎平台配置继承新的默认值
    resp = client.get("/api/v1/base-config?engine=stash&platform=ios")
    assert resp.status_code == 200
    assert resp.json()["effective"]["mode"] == doc["mode"]

    # 作用域列表里引擎默认配置项标记为"已自定义"
    resp = client.get("/api/v1/base-config/scopes")
    builtins = {s["engine"]: s for s in resp.json()["scopes"] if s.get("kind") == "builtin"}
    assert set(builtins) == {"stash", "mihomo"}
    assert builtins["stash"]["customized"] is True
    assert builtins["mihomo"]["customized"] is False

    # 恢复默认 → 覆盖记录清空，默认值回到源码内容
    resp = client.post("/api/v1/base-config/reset?engine=stash", headers=hdr)
    assert resp.status_code == 200
    assert resp.json()["overlay"] == {}
    assert resp.json()["effective"]["mode"] == origin_mode

    resp = client.get("/api/v1/base-config/scopes")
    builtins = {s["engine"]: s for s in resp.json()["scopes"] if s.get("kind") == "builtin"}
    assert not any(s["customized"] for s in builtins.values())


def test_builtin_default_rejects_protected_keys(client):
    csrf = setup_admin(client)
    hdr = auth_headers(csrf)
    resp = client.put("/api/v1/base-config?engine=stash",
                      json={"content": _yaml({"rules": ["MATCH,DIRECT"]})},
                      headers=hdr)
    assert resp.status_code == 400
    assert "基础配置不能包含" in resp.text


def test_builtin_scope_needs_engine(client):
    """引擎默认配置是按引擎分层的，engine 必填。"""
    setup_admin(client)
    resp = client.get("/api/v1/base-config")
    assert resp.status_code == 200
    assert resp.json()["engine"]


def test_builtin_scope_reports_program_default_as_baseline(client):
    """引擎默认配置层没有上层可比，基线是"程序内置的默认值"。

    界面靠这个基线区分"本层新增"和"本层覆盖"。
    """
    csrf = setup_admin(client)
    hdr = auth_headers(csrf)

    resp = client.get("/api/v1/base-config?engine=stash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["inherited"], "基线不应为空"
    assert data["inherited"].get("mode") == data["effective"].get("mode")

    # 改一个键 → 基线不变，覆盖记录里只留这一个键
    doc = dict(data["effective"])
    doc["mode"] = "global" if data["effective"].get("mode") != "global" else "rule"
    resp = client.put("/api/v1/base-config?engine=stash",
                      json={"content": _yaml(doc), "updated_at": data.get("updated_at", "")},
                      headers=hdr)
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved["inherited"].get("mode") == data["inherited"].get("mode"), "基线是默认值，不随改动变化"
    assert saved["overlay"].get("mode") == doc["mode"]


def test_platform_scope_baseline_is_upper_layer(client):
    """引擎平台配置层的基线是引擎默认配置层的生效值。"""
    csrf = setup_admin(client)
    hdr = auth_headers(csrf)

    resp = client.get("/api/v1/base-config?engine=stash")
    default = resp.json()

    resp = client.get("/api/v1/base-config?engine=stash&platform=ios")
    assert resp.status_code == 200
    data = resp.json()
    assert data["inherited"] == default["effective"], "基线应等于上层生效值"


def test_apply_on_builtin_scope_stores_only_the_diff(client):
    """「保存并构建发布」走 apply，也要只把与默认值的差异存下来。

    否则一次发布就会把整份默认配置写进覆盖记录，之后无法分辨哪些是改动。
    """
    csrf = setup_admin(client)
    make_policy(client, csrf)
    hdr = auth_headers(csrf)
    default = client.get("/api/v1/base-config?engine=stash").json()
    doc = dict(default["effective"])
    doc["mode"] = "global" if doc.get("mode") != "global" else "rule"

    resp = client.post("/api/v1/base-config/apply", headers=hdr, json={
        "engine": "stash", "platform": "", "content": _yaml(doc),
        "env": "testing", "note": "改引擎默认配置",
    })
    assert resp.status_code == 200, resp.text

    saved = client.get("/api/v1/base-config?engine=stash").json()
    assert list(saved["overlay"].keys()) == ["mode"], "只应保存与默认值不同的差异"
    assert saved["effective"]["mode"] == doc["mode"]


def test_home_system_domains_are_built_in():
    """「指到家里」的域名用 system 解析（约束 38 同源问题的面板侧修复）。

    2026-11-13 实证：homehub.stream / magichub.top 指向家里 NAS，
    路由器分流 DNS 给内网地址、公网 DoH 给家宽公网 IP——代理接管 DNS
    后从内网访问自己的公网 IP 会被 NAT 回环挡住（关代理立刻恢复）。
    引擎默认配置的 nameserver-policy 必须带 system 解析。
    """
    from app.services import base_config as bc
    for engine in ("stash", "mihomo"):
        doc = bc.default_doc(engine)
        policy = (doc.get("dns") or {}).get("nameserver-policy") or {}
        for domain in bc._HOME_SYSTEM_DOMAINS:
            assert policy.get(f"+.{domain}") == "system", (engine, domain)
        assert doc.get(bc.SYSTEM_DNS_KEY) == list(bc._HOME_SYSTEM_DOMAINS)


def test_render_merges_system_dns_domains():
    """渲染把伪键里的 system 解析域合成进 nameserver-policy（追加不覆盖）。"""
    import yaml
    from app.compiler import render
    snap = {
        "sources": [], "rule_providers": [], "local_nodes": [],
        "groups": [{"name": "PROXY", "type": "select", "hidden": False,
                    "filter": "", "use_sources": [], "local_nodes": [],
                    "proxies": ["DIRECT"], "targets": ["*"], "devices": ["*"],
                    "interval": 600, "timeout": 8000, "tolerance": 100,
                    "lazy": True, "strategy": ""}],
        "rules": [{"type": "MATCH", "value": "", "target": "PROXY",
                   "enabled": True, "targets": ["*"], "devices": ["*"]}],
        "snippets": [],
        "base": {"stash|": {"_system_dns_domains": ["myhome.example",
                                                    "homehub.stream"]}},
    }
    cfg = yaml.safe_load(render.render_target(snap, {"engine": "stash"}))
    policy = cfg["dns"]["nameserver-policy"]
    assert policy["+.myhome.example"] == "system"
    assert policy["+.homehub.stream"] == "system"
    # 基线的海外敏感域策略保留
    assert policy["+.microsoft.com"]


def test_cn_ip_must_not_have_no_resolve():
    """约束 23：cn-ip 是未收录国内域名的最后直连机会，不能带 no-resolve。"""
    from app.compiler import validate
    snap = {
        "sources": [], "rule_providers": [{"name": "cn-ip", "enabled": True,
                                           "behavior": "ipcidr"}],
        "local_nodes": [], "groups": [], "rules": [], "snippets": [],
    }
    snap["rules"] = [{"type": "MATCH", "value": "", "target": "DIRECT",
                      "enabled": True, "targets": ["*"], "devices": ["*"],
                      "variant_id": 0}]
    errors, _ = validate.validate_policy(snap)[0]
    assert not errors
    snap["rules"].insert(0, {"type": "RULE-SET", "value": "cn-ip",
                             "target": "DIRECT", "enabled": True,
                             "no_resolve": True, "targets": ["*"],
                             "devices": ["*"], "variant_id": 0})
    errors, _ = validate.validate_policy(snap)[0]
    assert any("cn-ip" in e and "no-resolve" in e for e in errors), errors


def test_platform_layer_accepts_effective_value_with_inherited_dns(client):
    """回归：平台层提交「完整生效值」（含继承的 dns 键）必须能保存。

    2026-11-13 实证：有效值里的 dns 键继承自引擎默认层，保存时按
    allow_dns=False 拦 effective 会让平台/设备层永远保存不了配置。
    dns 位置约束由「对 overlay 的校验」把关：继承的 dns 被差异计算剔除，
    本层新写的 dns 键依然会被拒绝。
    """
    csrf = setup_admin(client)
    hdr = auth_headers(csrf)
    default = client.get("/api/v1/base-config?engine=mihomo").json()
    doc = dict(default["effective"])
    assert "dns" in doc, "mihomo 引擎默认层带 dns 段"
    doc["ipv6"] = not doc.get("ipv6", False)

    resp = client.put("/api/v1/base-config?engine=mihomo&platform=linux",
                      headers=hdr, json={"content": _yaml(doc)})
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved["effective"]["ipv6"] == doc["ipv6"]
    assert "dns" not in saved["overlay"], "继承的 dns 键不应进入本层差异"

    # 本层新写 dns 键仍然被拒：位置约束由 overlay 校验把关
    doc2 = dict(doc)
    doc2["dns"] = dict(doc2["dns"] or {})
    doc2["dns"]["nameserver"] = ["https://1.2.3.4/dns-query"]
    resp = client.put("/api/v1/base-config?engine=mihomo&platform=linux",
                      headers=hdr, json={"content": _yaml(doc2)})
    assert resp.status_code == 400, resp.text
