"""设备「配置本体」更新时间的记录与陈旧判定。

以前 last_pull_at 被规则集、节点来源这些**子资源**的拉取一起刷新，
面板上的「最近下载」「24 小时内拉取过」因此看不出设备到底多久没拿到
新配置——设备配置卡住不更新时，界面完全正常，故障是隐形的
（2026-11-04 线上实证：Mac mini 的配置本体自 11-03 01:39 起就没再
生效，而面板显示它「3 小时前刚下载过」）。

约定：
  * last_pull_at   —— 任意资源（配置本体 + 规则集 + 节点来源）的拉取；
  * last_config_at —— 只有配置本体（config.yaml）被拉取时才更新；
  * config_stale   —— 超过 3 倍 profile-update-interval 没更新即判定陈旧。
"""
from conftest import auth_headers, setup_admin
from test_api import make_policy, publish_to_prod


def _device(client, h, name="iPhone"):
    target = client.get("/api/v1/targets", headers=h).json()[0]
    r = client.post("/api/v1/devices", headers=h, json={
        "name": name, "platform": target["platform"], "target_id": target["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_config_pull_time_is_tracked_separately(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    dev = _device(client, h)
    token = dev["token"]
    bid = client.post("/api/v1/builds", headers=h, json={}).json()["id"]
    publish_to_prod(client, h, bid)

    # 设备建好但还没拉过：配置时间未知，判定为陈旧
    row = client.get("/api/v1/devices", headers=h).json()[0]
    assert row["last_config_at"] is None
    assert row["config_stale"] is True

    # 拉一次配置本体
    r = client.get(f"/feed/{token}/config.yaml")
    assert r.status_code == 200, r.text
    row = client.get("/api/v1/devices", headers=h).json()[0]
    assert row["last_config_at"] is not None
    assert row["config_stale"] is False
    assert row["config_age_hours"] < 1

    # 拉子资源不刷新「配置本体」的时间——否则陈旧的设备看起来一直很新
    before = row["last_config_at"]
    assert client.get(f"/feed/{token}/res/rule/no-such-rule").status_code == 404
    row2 = client.get("/api/v1/devices", headers=h).json()[0]
    assert row2["last_config_at"] == before


def test_overview_counts_stale_devices(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    make_policy(client, csrf)
    dev = _device(client, h)
    bid = client.post("/api/v1/builds", headers=h, json={}).json()["id"]
    publish_to_prod(client, h, bid)

    ov = client.get("/api/v1/overview", headers=h).json()
    assert ov["counts"]["devices_stale"] == 1
    assert ov["devices"][0]["config_stale"] is True

    client.get(f"/feed/{dev['token']}/config.yaml")
    ov = client.get("/api/v1/overview", headers=h).json()
    assert ov["counts"]["devices_stale"] == 0
    assert ov["devices"][0]["config_stale"] is False
