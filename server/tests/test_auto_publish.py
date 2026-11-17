"""自动构建发布的闸门：Mihomo 目标必须真的做过核心校验（mihomo -t）。

回归背景：设备专属产物的构建结果里没有写 core_checked 字段，
闸门用 item.get("core_checked") 判断时取到 None（falsy），
把明明写着「核心校验通过」的设备产物当成没校验——
自动构建于是每小时建一次、永远发不到生产环境。
"""
from app.services import scheduler
from conftest import auth_headers, setup_admin
from test_api import make_policy


def test_unchecked_core_targets_ignores_verified_device_results():
    """历史构建的设备产物没有 core_checked 字段，但校验通过，不该被拦。"""
    results = {
        "Mihomo-macOS": {
            "engine": "mihomo", "core_checked": True,
            "verification": "核心校验通过（mihomo -t）"},
        "Astral-Windows-Mihomo": {
            "engine": "mihomo",
            "verification": "核心校验通过（mihomo -t）"},
    }
    assert scheduler._unchecked_core_targets(results) == []


def test_unchecked_core_targets_blocks_static_only():
    """真没做核心校验的目标仍要拦住；Stash 不在管辖区。"""
    results = {
        "Mihomo-macOS": {
            "engine": "mihomo", "core_checked": False,
            "verification": "静态通过（未做核心校验）"},
        "Stash-iOS": {
            "engine": "stash", "core_checked": False, "verification": "静态通过"},
    }
    assert scheduler._unchecked_core_targets(results) == ["Mihomo-macOS"]


def test_unchecked_core_targets_empty_results():
    assert scheduler._unchecked_core_targets({}) == []
    assert scheduler._unchecked_core_targets(None) == []


def test_device_artifact_records_core_checked(client, monkeypatch):
    """设备专属产物的构建结果必须写 core_checked（与平台产物一致）。

    少了这个字段，自动构建发布的闸门会把「核心校验通过」的设备产物
    当成没校验，于是自动构建一直发不出去。
    """
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/targets", headers=h, json={
        "name": "mihomo-android", "engine": "mihomo", "platform": "android"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "节点选择", "type": "select", "proxies": ["DIRECT"]})
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "安卓", "platform": "android", "target_id": 1}).json()
    # 再来一台：逐项选满会被归一成「包含所有」，限定才收得住
    client.post("/api/v1/devices", headers=h, json={
        "name": "平板", "platform": "android", "target_id": 1})

    # 只给这台设备的规则 → 会额外产出一份设备专属产物
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "only-this-device.example.com",
        "target": "节点选择", "devices": [dev["name"]]})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT"})

    # 假装核心可用且校验通过
    monkeypatch.setattr(tester, "validate_config", lambda *a, **k: (True, ""))
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build["results"]
    assert dev["name"] in build["results"], build["results"].keys()
    assert build["results"][dev["name"]]["core_checked"] is True
    assert "核心校验" in build["results"][dev["name"]]["verification"]
    # 这种产物不该被自动构建发布的闸门拦下
    assert scheduler._unchecked_core_targets(build["results"]) == []


def test_device_artifact_without_core_records_false(client, monkeypatch):
    """核心不可用时，设备产物要明确记 False，并写明「未做核心校验」。"""
    from app.services import tester

    csrf = setup_admin(client)
    h = auth_headers(csrf)
    client.post("/api/v1/targets", headers=h, json={
        "name": "mihomo-android", "engine": "mihomo", "platform": "android"})
    client.post("/api/v1/groups", headers=h, json={
        "name": "节点选择", "type": "select", "proxies": ["DIRECT"]})
    dev = client.post("/api/v1/devices", headers=h, json={
        "name": "安卓", "platform": "android", "target_id": 1}).json()
    # 再来一台：逐项选满会被归一成「包含所有」，限定才收得住
    client.post("/api/v1/devices", headers=h, json={
        "name": "平板", "platform": "android", "target_id": 1})
    client.post("/api/v1/rules", headers=h, json={
        "type": "DOMAIN-SUFFIX", "value": "only-this-device.example.com",
        "target": "节点选择", "devices": [dev["name"]]})
    client.post("/api/v1/rules", headers=h, json={
        "type": "MATCH", "target": "DIRECT"})

    monkeypatch.setattr(tester, "validate_config", lambda *a, **k: (False, ""))
    build = client.post("/api/v1/builds", headers=h, json={}).json()
    assert build["verify_status"] == "success", build["results"]
    item = build["results"][dev["name"]]
    assert item["core_checked"] is False
    assert "未做核心校验" in item["verification"]
    # 没做核心校验就要拦下，不发生产（平台产物与设备产物都算）
    assert set(scheduler._unchecked_core_targets(build["results"])) == {
        "mihomo-android", dev["name"]}


def test_auto_publish_backoff_and_reuse(client, monkeypatch):
    """发布失败 → 指数退避（调度 tick 不再每 30 秒重建构建）；
    退避到期后重试复用同策略的已构建版本，不重复建构建；成功后清除退避。

    2026-11-18 修复：原来失败把 auto_build_last_attempt 清空，
    下个 tick（30s）就重建一个完整构建再试，持续失败时构建互相驱逐。
    """
    from app import db
    from app.services import releases, scheduler, tester

    csrf = setup_admin(client)
    make_policy(client, csrf)
    h = auth_headers(csrf)
    client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_fetch_sources": "0", "auto_fetch_rules": "0",
    }})
    # 假装核心可用：mihomo 产物过了核心校验，闸门放行到发布这一步
    monkeypatch.setattr(tester, "validate_config", lambda *a, **k: (True, ""))

    def boom(*a, **k):
        raise releases.ReleaseError("模拟发布失败")
    monkeypatch.setattr(releases, "publish_build", boom)

    summary = scheduler.run_once(force=True)
    assert "模拟发布失败" in summary["build_error"]
    assert summary["retry_backoff_seconds"] >= 600
    with db.connect() as conn:
        fail_count = db.get_setting(conn, "auto_build_fail_count", "")
        backoff = db.get_setting(conn, "auto_build_backoff_until", "")
    assert fail_count == "1" and backoff

    # 到了间隔（把 last_attempt 拨回过去），但还在退避期内：调度 tick 不重试
    with db.tx() as conn:
        db.set_setting(conn, "auto_build_last_attempt", "2000-01-01T00:00:00+08:00")
    summary = scheduler.run_once(force=False)
    # backoff 键不进 summary["build"]：那个键算"有活动"，会让退避期内
    # 每 30 秒刷一条 automation_runs（2026-11-18 红队修复）
    assert summary["backoff"] == "上次发布失败，退避等待重试"
    assert summary["build"] is None

    # 退避到期：复用同策略已构建版本，不再新建构建
    with db.tx() as conn:
        db.set_setting(conn, "auto_build_backoff_until", "2000-01-01T00:00:00+08:00")
    monkeypatch.setattr(releases, "publish_build",
                        lambda *a, **k: {"ok": True})
    summary = scheduler.run_once(force=False)
    assert summary["build"]["status"] == "reuse"
    assert summary["published"] == "production"
    assert len(client.get("/api/v1/builds", headers=h).json()) == 1
    # 发布成功：退避状态清除
    with db.connect() as conn:
        assert db.get_setting(conn, "auto_build_fail_count", "") == "0"
        assert db.get_setting(conn, "auto_build_backoff_until", "") == ""
