"""自动构建发布的测速门禁：没有节点的来源不能把发布永久卡住。

线上事故（2026-11-04）：新建一个还没抓到内容的来源（启用「只分发可用节点」），
它的测速结果永远出不来 → 自动构建发布被卡住 → 面板的「立即发布」与定时发布
都推不出去新版本，整条发布链路静默停摆。

约定：
  * 关了自动测速的来源不参与门禁（早就有的约定）；
  * **一个节点都没有的来源同样不参与门禁**——它进不了产物，不会违反
    「只分发可用节点」的承诺；
  * 有节点但测不出结果的来源仍然卡门禁（这是门禁的本意）。
"""
from conftest import auth_headers, setup_admin
from test_api import make_policy


def _prepare(client, h, csrf):
    """造一套最小策略，并关掉自动抓取（测试里不碰外网）。"""
    make_policy(client, csrf)
    client.put("/api/v1/settings", headers=h, json={"values": {
        "auto_fetch_sources": "0", "auto_fetch_rules": "0",
    }})


def _source(client, h, name="机场A", **kw):
    body = {"name": name, "url": "https://a.example.com/sub?token=abc123"}
    body.update(kw)
    r = client.post("/api/v1/sources", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _run_once():
    from app.services import scheduler
    return scheduler.run_once(force=True)


def test_source_without_nodes_does_not_block_auto_publish(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _prepare(client, h, csrf)
    # 只分发可用节点 + 自动测速，但一个节点都没抓到
    _source(client, h, name="空机场", filter_unavailable=True, auto_test=True)
    summary = _run_once()
    assert "等待测速结果" not in (summary.get("build_error") or ""), summary
    assert "没有节点的来源不参与门禁" in (summary.get("skipped") or ""), summary
    assert summary["build"] is not None


def test_source_with_nodes_but_no_results_still_blocks(client):
    """有节点的来源测不出结果时，门禁照旧要拦住（这是门禁的本意）。"""
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _prepare(client, h, csrf)
    source = client.get("/api/v1/sources").json()[0]
    from app import db
    with db.tx() as conn:
        conn.execute(
            "UPDATE sources SET filter_unavailable=1, node_count=1, "
            "test_results='{}', tested_at=NULL, test_attempt_at=NULL WHERE id=?",
            (source["id"],),
        )
    summary = _run_once()
    assert "等待测速结果" in (summary.get("build_error") or ""), summary
    assert summary["build"] is None


def test_source_with_auto_test_off_does_not_block(client):
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    _prepare(client, h, csrf)
    _source(client, h, name="不测速的机场", filter_unavailable=True,
            auto_test=False)
    summary = _run_once()
    assert "等待测速结果" not in (summary.get("build_error") or ""), summary
    assert "未开启测速的来源不参与门禁" in (summary.get("skipped") or ""), summary
