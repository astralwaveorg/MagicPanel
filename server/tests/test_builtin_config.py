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
