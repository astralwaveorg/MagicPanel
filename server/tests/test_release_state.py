"""版本生命周期状态机的边界用例。

重构后的模型：一个构建在任意时刻只有一种生命周期状态，
生产 / 测试两个环境各由「状态」唯一确定（不再有独立的通道指针表）：

    BUILT       已构建：从没发布过，产物可物理删除
    TESTING     测试中：当前测试环境生效的唯一版本
    PRODUCTION  生产中：当前生产环境生效的唯一版本
    OFFLINE     已下线：曾发布过，被替换或手动撤销，只能归档不能删

允许的流转：

    BUILT / OFFLINE ──publish-to-test──▶ TESTING
    TESTING / OFFLINE ──publish-to-prod─▶ PRODUCTION
    TESTING ──offline──▶ OFFLINE
    BUILT ──delete──▶ （物理删除）

这套用例是状态机重构的核心交付物：每个用例都断言"状态"，
而不只是接口返回码。
"""
import shutil

from conftest import auth_headers, setup_admin
from test_api import make_policy


# ---- 小工具 ----

def _create_build(client, h, note=""):
    """创建构建：生命周期状态恒为 BUILT，校验结果单独看 verify_status。"""
    r = client.post("/api/v1/builds", headers=h, json={"note": note})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "BUILT", data
    assert data["verify_status"] == "success", data
    return data


def _release_state(client):
    """当前发布状态：{"production": build|None, "testing": build|None}。"""
    return client.get("/api/v1/release-state").json()


def _rows_with_status(client, status):
    """直接查 builds 表：某个生命周期状态有多少行。

    唯一性是数据库层的部分唯一索引保证的，接口返回体看不到全部行，
    所以这里直接查表断言 count == 1。
    """
    from app import db
    with db.connect() as conn:
        return db.all_(conn, "SELECT id FROM builds WHERE status=?", (status,))


def _row(client, bid):
    """直接查 builds 表里某一行。"""
    from app import db
    with db.connect() as conn:
        return db.one(conn, "SELECT * FROM builds WHERE id=?", (bid,))


def _artifacts_dir(bid):
    from app import config
    return config.BUILDS_DIR / str(bid)


# ---- 四态流转 ----

def test_builtin_to_testing_to_production(client):
    """BUILT → TESTING → PRODUCTION：两个环境各自出现唯一的生效版本。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    build = _create_build(client, h, "首个版本")
    bid = build["id"]
    assert _release_state(client) == {"production": None, "testing": None}

    r = client.post(f"/api/v1/builds/{bid}/publish-to-test", headers=h,
                    json={"reason": "先上测试"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TESTING"
    assert r.json()["env"] == "testing"

    state = _release_state(client)
    assert state["testing"]["id"] == bid
    assert state["testing"]["status"] == "TESTING"
    # 测试环境有版本了，生产环境仍然空着
    assert state["production"] is None
    assert _row(client, bid)["status"] == "TESTING"

    r = client.post(f"/api/v1/builds/{bid}/publish-to-prod", headers=h,
                    json={"reason": "验收通过上生产"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PRODUCTION"
    assert r.json()["env"] == "production"

    state = _release_state(client)
    assert state["production"]["id"] == bid
    assert state["production"]["status"] == "PRODUCTION"
    assert _row(client, bid)["status"] == "PRODUCTION"


def test_publish_metadata_is_recorded(client):
    """发布元数据上移到构建行：published_at / published_by / publish_reason。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)

    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": "灰度"})

    state = _release_state(client)["testing"]
    assert state["published_by"] == "admin"
    assert state["publish_reason"] == "灰度"
    assert state["published_at"]
    assert state["status_updated_at"]
    # 旧的"publish 子对象"结构已不存在
    assert "publish" not in state


def test_publish_to_testing_offlines_previous_testing(client):
    """发布至测试时，原 TESTING 版本自动下线，测试环境仍只有一条生效记录。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    first = _create_build(client, h, "一")
    second = _create_build(client, h, "二")
    client.post(f"/api/v1/builds/{first['id']}/publish-to-test", headers=h,
                json={"reason": "先上测试"})
    assert _row(client, first["id"])["status"] == "TESTING"

    r = client.post(f"/api/v1/builds/{second['id']}/publish-to-test", headers=h,
                    json={"reason": "换新版本"})
    assert r.status_code == 200, r.text
    # 被替换的旧版本自动下线
    assert _row(client, first["id"])["status"] == "OFFLINE"
    assert _row(client, second["id"])["status"] == "TESTING"
    # 测试环境指向新版本
    assert _release_state(client)["testing"]["id"] == second["id"]


def test_publish_to_production_offlines_previous_production(client):
    """发布至生产时，原 PRODUCTION 版本自动下线。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    first = _create_build(client, h, "一")
    second = _create_build(client, h, "二")
    for build in (first, second):
        client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                    json={"reason": "上测试"})
        client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "上生产"})

    assert _row(client, first["id"])["status"] == "OFFLINE"
    assert _row(client, second["id"])["status"] == "PRODUCTION"
    assert _release_state(client)["production"]["id"] == second["id"]


# ---- 状态机的拒绝路径 ----

def test_builtin_cannot_be_published_to_production_directly(client):
    """BUILT → PRODUCTION 被拒：没经过测试环境的版本不能直接上生产。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)

    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "直接上生产"})
    assert r.status_code == 400
    assert "请先发布至测试环境" in r.json()["detail"]
    # 状态不变，生产环境仍为空
    assert _row(client, build["id"])["status"] == "BUILT"
    assert _release_state(client)["production"] is None


def test_failed_verification_cannot_be_published(client):
    """校验失败的构建不能发布：verify_status != success 一律拒绝。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    # 空策略组 + 缺兜底规则 → 校验失败
    client.post("/api/v1/targets", headers=h, json={
        "name": "stash-ios", "engine": "stash", "platform": "ios"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "空组", "type": "select"})
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "failed"
    assert build["status"] == "BUILT"

    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                    json={"reason": "试试"})
    assert r.status_code == 400
    assert "未通过校验" in r.json()["detail"]
    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "试试"})
    assert r.status_code == 400
    assert _release_state(client) == {"production": None, "testing": None}


def test_publish_to_testing_twice_is_rejected(client):
    """已是当前测试版本的构建不能再发布一次。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)
    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": "第一次"})

    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                    json={"reason": "第二次"})
    assert r.status_code == 400
    assert "已是当前测试版本" in r.json()["detail"]


def test_publish_same_build_to_production_twice_is_rejected(client):
    """连续两次发布同一构建到生产：第二次 400，不会产生两条 PRODUCTION。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)
    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})

    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "上生产"})
    assert r.status_code == 200, r.text
    assert len(_rows_with_status(client, "PRODUCTION")) == 1

    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "再来一次"})
    assert r.status_code == 400
    assert "已是当前生产版本" in r.json()["detail"]
    # 唯一性没有被破坏
    assert len(_rows_with_status(client, "PRODUCTION")) == 1
    assert _release_state(client)["production"]["id"] == build["id"]


# ---- 手动下线 ----

def test_manual_offline_clears_testing_environment(client):
    """手动下线：TESTING → OFFLINE，下线后测试环境为空。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)
    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})

    r = client.post(f"/api/v1/builds/{build['id']}/offline", headers=h,
                    json={"reason": "有问题，先撤"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "OFFLINE"
    assert r.json()["action"] == "offline"
    assert _row(client, build["id"])["status"] == "OFFLINE"
    assert _release_state(client)["testing"] is None
    assert len(_rows_with_status(client, "TESTING")) == 0

    # 下线记录进入发布历史
    releases = client.get("/api/v1/releases").json()
    assert releases[0]["action"] == "offline"
    assert releases[0]["env"] == "testing"
    assert releases[0]["reason"] == "有问题，先撤"


def test_production_build_cannot_be_offlined(client):
    """生产版本不可手动下线：状态机只允许 TESTING → OFFLINE。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)
    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})
    client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                json={"reason": "上生产"})

    r = client.post(f"/api/v1/builds/{build['id']}/offline", headers=h,
                    json={"reason": "想撤生产"})
    assert r.status_code == 400
    assert "只有当前测试版本可以下线" in r.json()["detail"]
    # 生产版本不受影响
    assert _row(client, build["id"])["status"] == "PRODUCTION"
    assert _release_state(client)["production"]["id"] == build["id"]


# ---- 删除防呆 ----

def test_only_builtin_build_can_be_deleted(client):
    """删除防呆：TESTING / PRODUCTION / OFFLINE 一律 400，只有 BUILT 可删。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    # TESTING 不可删
    testing = _create_build(client, h, "测试中")
    client.post(f"/api/v1/builds/{testing['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})
    r = client.delete(f"/api/v1/builds/{testing['id']}", headers=h)
    assert r.status_code == 400
    assert "只有未发布过的构建可以删除" in r.json()["detail"]

    # PRODUCTION 不可删
    production = _create_build(client, h, "生产中")
    client.post(f"/api/v1/builds/{production['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})
    client.post(f"/api/v1/builds/{production['id']}/publish-to-prod", headers=h,
                json={"reason": "上生产"})
    r = client.delete(f"/api/v1/builds/{production['id']}", headers=h)
    assert r.status_code == 400
    assert "只有未发布过的构建可以删除" in r.json()["detail"]

    # OFFLINE 不可删（归档，不是垃圾）
    offline = _create_build(client, h, "已下线")
    client.post(f"/api/v1/builds/{offline['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})
    client.post(f"/api/v1/builds/{offline['id']}/offline", headers=h,
                json={"reason": "下线"})
    r = client.delete(f"/api/v1/builds/{offline['id']}", headers=h)
    assert r.status_code == 400
    assert "只有未发布过的构建可以删除" in r.json()["detail"]

    # BUILT 可删
    fresh = _create_build(client, h, "没发布过")
    r = client.delete(f"/api/v1/builds/{fresh['id']}", headers=h)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/builds/{fresh['id']}").status_code == 404
    # 从未发布过的构建没有发布历史可清理
    assert r.json()["deleted_releases"] == 0


def test_batch_delete_splits_deleted_and_blocked(client):
    """批量删除：BUILT 进 deleted，已发布的进 blocked 并说明原因。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    fresh = _create_build(client, h, "没发布过")
    published = _create_build(client, h, "发布过")
    client.post(f"/api/v1/builds/{published['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})

    r = client.post("/api/v1/builds/batch/delete", headers=h,
                    json={"ids": [fresh["id"], published["id"], 999999]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] == [fresh["id"]]
    assert [b["id"] for b in data["blocked"]] == [published["id"], 999999]
    assert "只有未发布过的构建可以删除" in data["blocked"][0]["reason"]
    assert "不存在" in data["blocked"][1]["reason"]


# ---- 唯一性 ----

def test_at_most_one_production_and_one_testing(client):
    """全局至多一条 PRODUCTION、一条 TESTING（数据库唯一索引保证）。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    builds = [_create_build(client, h, f"版本{i}") for i in range(4)]
    for build in builds:
        client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                    json={"reason": "上测试"})
    assert len(_rows_with_status(client, "TESTING")) == 1
    assert _release_state(client)["testing"]["id"] == builds[-1]["id"]

    for build in builds:
        client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "上生产"})
    assert len(_rows_with_status(client, "PRODUCTION")) == 1
    assert len(_rows_with_status(client, "TESTING")) == 0
    assert _release_state(client)["production"]["id"] == builds[-1]["id"]
    # 其余全部归档为 OFFLINE
    assert len(_rows_with_status(client, "OFFLINE")) == len(builds) - 1


# ---- 回滚 ----

def test_rollback_offline_build_to_production(client):
    """回滚：已下线版本可回滚为生产版本，原生产版本变 OFFLINE，唯一性不破。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    first = _create_build(client, h, "旧版本")
    second = _create_build(client, h, "新版本")
    for build in (first, second):
        client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                    json={"reason": "上测试"})
        client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "上生产"})
    assert _row(client, first["id"])["status"] == "OFFLINE"

    r = client.post(f"/api/v1/builds/{first['id']}/rollback-to-prod", headers=h,
                    json={"reason": "新版本有问题，回滚"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PRODUCTION"
    assert r.json()["action"] == "rollback"
    # 原生产版本下线，回滚版本上位
    assert _row(client, first["id"])["status"] == "PRODUCTION"
    assert _row(client, second["id"])["status"] == "OFFLINE"
    assert _release_state(client)["production"]["id"] == first["id"]
    assert len(_rows_with_status(client, "PRODUCTION")) == 1

    # 发布历史记录的是 rollback
    releases = client.get("/api/v1/releases").json()
    assert releases[0]["action"] == "rollback"
    assert releases[0]["env"] == "production"
    assert releases[0]["reason"] == "新版本有问题，回滚"


# ---- 产物已清理 ----

def test_build_with_removed_artifacts_cannot_be_published(client):
    """产物被留存清理掉的构建不能发布：上线后设备只会拿到 503。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)
    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})

    # 模拟留存清理：产物目录被删掉
    shutil.rmtree(_artifacts_dir(build["id"]), ignore_errors=True)

    r = client.post(f"/api/v1/builds/{build['id']}/publish-to-prod", headers=h,
                    json={"reason": "上生产"})
    assert r.status_code == 400
    assert "产物已被清理" in r.json()["detail"]
    # 状态没有被推进
    assert _row(client, build["id"])["status"] == "TESTING"
    assert _release_state(client)["production"] is None


# ---- 设备按环境取版本 ----

def test_device_env_selects_effective_build(client):
    """设备按 env 取对应环境的生效版本：production 取生产中，testing 取测试中。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)

    first = _create_build(client, h, "一")
    client.post(f"/api/v1/builds/{first['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})
    client.post(f"/api/v1/builds/{first['id']}/publish-to-prod", headers=h,
                json={"reason": "上生产"})

    # 改策略后再构建：新产物多一条规则，便于区分设备拿到的是哪个版本
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "second.example.com", "target": "节点选择"})
    second = _create_build(client, h, "二")
    client.post(f"/api/v1/builds/{second['id']}/publish-to-test", headers=h,
                json={"reason": "新版本上测试"})

    prod_dev = client.post("/api/v1/devices", headers=h, json={
        "name": "生产机", "platform": "ios", "target_id": 1, "env": "production"}).json()
    test_dev = client.post("/api/v1/devices", headers=h, json={
        "name": "测试机", "platform": "ios", "target_id": 1, "env": "testing"}).json()
    assert prod_dev["env"] == "production"
    assert test_dev["env"] == "testing"

    prod_text = client.get(f"/feed/{prod_dev['token']}/config.yaml").text
    test_text = client.get(f"/feed/{test_dev['token']}/config.yaml").text
    assert "second.example.com" not in prod_text
    assert "second.example.com" in test_text


def test_release_state_shape(client):
    """release-state 的结构：两个环境各一个构建（或 None），字段固定。"""
    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    build = _create_build(client, h)
    client.post(f"/api/v1/builds/{build['id']}/publish-to-test", headers=h,
                json={"reason": "上测试"})

    state = _release_state(client)
    assert set(state) == {"production", "testing"}
    assert state["production"] is None
    entry = state["testing"]
    assert set(entry) == {
        "id", "created_at", "created_by", "status", "verify_status", "policy_sha",
        "note", "published_at", "published_by", "publish_reason", "status_updated_at",
    }
    assert entry["verify_status"] == "success"
    assert entry["status"] == "TESTING"
