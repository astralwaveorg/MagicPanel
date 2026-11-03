"""发布产物引用的资源守卫 + 停用资源继续下发。

产物不可变、只移动指针：当前生产版本里还写着的规则来源 / 节点来源，
删掉或改名会让仍在使用旧产物的设备直接 404——客户端会一直重试，并把
整个订阅更新判为失败（实测 Stash 每分钟刷一次
"artifact refresh failed ... HTTP 404"，配置再也更新不进来）。

两条约定：
  * 停用 ≠ 删除：内容还在就继续下发（feed 仍返回 200）；
  * 删除 / 改名被当前生产产物引用时返回 409 + 引用明细
    （复用既有 code，前端自动弹二次确认），force=1 才放行。
"""
from conftest import auth_headers, setup_admin
from test_api import make_policy, publish_to_prod


def _rule_provider(client, h, name="rules-a"):
    r = client.post("/api/v1/rule-providers", headers=h, json={
        "name": name, "kind": "inline", "behavior": "domain",
        "inline_content": "payload:\n  - a.example.com\n"})
    assert r.status_code == 201, r.text
    return r.json()


def _device(client, h, name="iPhone"):
    target = client.get("/api/v1/targets", headers=h).json()[0]
    r = client.post("/api/v1/devices", headers=h, json={
        "name": name, "platform": target["platform"], "target_id": target["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def _publish_with_provider(client, h, rp):
    """把策略发布到生产，返回设备令牌。

    产物会带上**全部已启用**的规则来源（不只看有没有规则引用），
    所以这里不额外建 RULE-SET 规则——那样会先被"仍被分流规则引用"的
    守卫拦掉，测不到"被生产产物引用"这条。
    """
    dev = _device(client, h)
    bid = client.post("/api/v1/builds", headers=h, json={}).json()["id"]
    publish_to_prod(client, h, bid)
    return dev["token"]


def test_disabled_rule_provider_is_still_served(client):
    """停用只影响新构建；已发布产物引用的资源仍要能取到。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    rp = _rule_provider(client, h)
    token = _publish_with_provider(client, h, rp)

    assert client.get(f"/feed/{token}/res/rule/{rp['name']}").status_code == 200

    client.patch(f"/api/v1/rule-providers/{rp['id']}/enabled", headers=h,
                 json={"enabled": False})
    # 停用 ≠ 删除：老产物还指着这个地址，回 404 会让客户端更新失败
    r = client.get(f"/feed/{token}/res/rule/{rp['name']}")
    assert r.status_code == 200, r.text


def test_release_referenced_rule_provider_cannot_be_deleted(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    rp = _rule_provider(client, h)
    _publish_with_provider(client, h, rp)

    r = client.delete(f"/api/v1/rule-providers/{rp['id']}", headers=h)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "rule_provider_in_use"
    assert detail["references"][0]["type"] == "生产产物"
    # 拒绝时不动数据
    names = [x["name"] for x in client.get("/api/v1/rule-providers", headers=h).json()]
    assert rp["name"] in names

    r = client.delete(f"/api/v1/rule-providers/{rp['id']}?force=1", headers=h)
    assert r.status_code == 200, r.text


def test_release_referenced_rule_provider_cannot_be_renamed(client):
    """改名 = 旧名字消失，老产物上写着的地址就 404 了。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    rp = _rule_provider(client, h)
    _publish_with_provider(client, h, rp)

    body = {"name": "rules-b", "kind": "inline", "behavior": "domain",
            "inline_content": "payload:\n  - a.example.com\n"}
    r = client.put(f"/api/v1/rule-providers/{rp['id']}", headers=h, json=body)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "rule_provider_in_use"
    assert detail["rename_to"] == "rules-b"

    r = client.put(f"/api/v1/rule-providers/{rp['id']}?force=1", headers=h,
                   json=body)
    assert r.status_code == 200, r.text
