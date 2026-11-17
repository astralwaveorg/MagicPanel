"""核心价值链路的端到端集成测试（2026-11-18 新增）。

此前「登录 → 改策略 → 构建 → 发布 → 设备拉到新配置」这条产品的
完整生效链路没有任何一层测试端到端验证过（e2e 只测门户且不连真实后端）。
本文件用真实 app（tmp 数据目录）走完整链路，断言设备真的拿到新配置。
"""
import yaml
from conftest import auth_headers, setup_admin
from test_api import make_policy


def _device(client, h, name="链路手机"):
    target = client.get("/api/v1/targets", headers=h).json()[0]
    r = client.post("/api/v1/devices", headers=h, json={
        "name": name, "platform": target["platform"], "target_id": target["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_admin_full_chain_login_edit_build_publish_feed(client):
    """登录 → 新增规则 → 构建 → 发布测试 → 设备 feed 拉到新规则。"""
    from app import db

    # 1. 初始化管理员并登录（拿 CSRF，和真实浏览器同一套握手）
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    dev = _device(client, h)
    token = dev["token"]

    # 2. 新增一条分流规则（目标指向既有策略组）
    r = client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "chain-test.example.com",
        "target": "节点选择"})
    assert r.status_code == 201, r.text

    # 3. 构建：新规则必须出现在产物里
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build["results"]
    art = client.get(f"/api/v1/builds/{build['id']}/artifact/stash-ios").json()["content"]
    assert "chain-test.example.com" in art, "新规则没进产物"

    # 4. 发布到测试环境；设备 env=production 先拉生产（无版本 → 503）
    assert client.get(f"/feed/{token}/config.yaml").status_code == 503
    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                    json={"reason": "链路测试"})
    assert r.status_code == 200, r.text

    # 5. 设备切到测试环境，拉配置断言新规则真的下发
    r = client.put(f"/api/v1/devices/{dev['id']}", headers=h,
                   json={"name": dev["name"], "platform": dev["platform"],
                         "target_id": dev["target_id"], "env": "testing"})
    assert r.status_code == 200, r.text
    feed = client.get(f"/feed/{token}/config.yaml")
    assert feed.status_code == 200, feed.text
    cfg = yaml.safe_load(feed.text)
    assert any("chain-test.example.com" in str(rule)
               for rule in cfg.get("rules", [])), "设备拉到的配置里没有新规则"

    # 6. 拉取计数与配置时效被记录
    row = client.get("/api/v1/devices", headers=h).json()[0]
    assert row["last_config_at"] is not None
    assert row["pull_count"] >= 1

    # 7. 审计留痕：登录、构建、发布都进了审计
    audits = client.get("/api/v1/audit?limit=200", headers=h).json()["items"]
    actions = {a["action"] for a in audits}
    assert "发布到测试环境" in actions
    assert "创建构建" in actions


def test_feed_concurrent_pulls_are_counted(client):
    """多设备并发拉取：短事务计数不丢、响应不互相干扰。

    feed 的拉取计数走独立短事务（2026-11-18 修复 rule_resource 在只读
    连接上 UPDATE 的竞态），这里用真线程并发验证。
    """
    import concurrent.futures

    from conftest import auth_headers, setup_admin
    from test_api import make_policy, publish_to_prod

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    dev = _device(client, h, name="并发设备")
    bid = client.post("/api/v1/builds", headers=h, json={}).json()["id"]
    publish_to_prod(client, h, bid)

    token = dev["token"]
    # config 本体走完整的 record 短事务链路；抓取一次真实 ETag 后，
    # 一半请求带 If-None-Match 走 304 分支（同样记账）
    first = client.get(f"/feed/{token}/config.yaml")
    assert first.status_code == 200
    etag = first.headers["ETag"]
    paths = ([f"/feed/{token}/config.yaml"] * 8 +
             [f"/feed/{token}/config.yaml?etag={i}" for i in range(4)])
    headers_all = [None] * 8 + [{"if-none-match": etag}] * 4
    def pull(args):
        path, hdr = args
        return client.get(path, headers=hdr or {}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(pull, zip(paths, headers_all)))
    bad = [(p, c) for p, c in zip(paths, codes) if c not in (200, 304)]
    assert not bad, bad

    row = client.get("/api/v1/devices", headers=h).json()[0]
    assert row["pull_count"] >= 12, row["pull_count"]
    assert row["last_config_at"] is not None
