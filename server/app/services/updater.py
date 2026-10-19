"""节点来源 / 规则来源的抓取与测速实现。

手动操作与内置定时任务共用这里，保证失败状态、审计和快照行为一致。
失败时先提交状态再抛出异常，避免调用方的事务回滚把失败记录一起丢掉。
"""
import json

from .. import db, security
from . import fetcher, tester


class NotFound(Exception):
    pass


class InvalidOperation(Exception):
    pass


def _source_row(conn, source_id: int):
    row = db.one(conn, "SELECT * FROM sources WHERE id=?", (source_id,))
    if not row:
        raise NotFound("节点来源不存在")
    return row


def _provider_row(conn, rp_id: int):
    row = db.one(conn, "SELECT * FROM rule_providers WHERE id=?", (rp_id,))
    if not row:
        raise NotFound("规则来源不存在")
    return row


def _action(automatic: bool, manual: str, auto: str) -> str:
    return auto if automatic else manual


def refresh_source(source_id: int, operator: str, automatic: bool = False):
    """抓取节点来源并留存快照；失败时保留最近一次成功快照。"""
    error = ""
    with db.tx() as conn:
        row = _source_row(conn, source_id)
        url = security.decrypt_text(row["url_enc"])
        now = db.now()
        conn.execute(
            "UPDATE sources SET last_attempt_at=?, updated_at=? WHERE id=?",
            (now, now, source_id),
        )
        try:
            body = fetcher.fetch(
                url, ua=row["ua"], allow_private=bool(row["allow_private"]))
            nodes = fetcher.parse_nodes(body)
        except fetcher.FetchError as exc:
            error = str(exc)
            conn.execute(
                "UPDATE sources SET last_status='failed', last_error=?, "
                "fail_count=fail_count+1, last_attempt_at=?, updated_at=? WHERE id=?",
                (error, now, now, source_id),
            )
            security.audit(
                conn, operator,
                _action(automatic, "刷新节点来源失败", "自动抓取节点来源失败"),
                "source", source_id, {"name": row["name"], "error": error},
            )
        else:
            text = body.decode("utf-8", "replace")
            # 新快照的节点集合可能变化，旧测速结果不再可信。
            # 启用“只分发可用节点”的来源需要尽快重新测速，因此把 test_attempt_at
            # 清空，让调度器在同一轮或下一轮抓取后立即补测；其他来源保持原测速节奏。
            conn.execute(
                "UPDATE sources SET last_status='ok', last_error='', "
                "last_fetched_at=?, last_attempt_at=?, node_count=?, sha256=?, "
                "fail_count=0, snapshot_enc=?, nodes_meta=?, test_results='{}', "
                "tested_at=NULL, "
                "test_attempt_at=CASE WHEN filter_unavailable=1 THEN NULL "
                "ELSE test_attempt_at END, updated_at=? WHERE id=?",
                (now, now, len(nodes), security.sha256_text(text),
                 security.encrypt_text(text), json.dumps(nodes, ensure_ascii=False),
                 now, source_id),
            )
            security.audit(
                conn, operator,
                _action(automatic, "刷新节点来源", "自动抓取节点来源"),
                "source", source_id,
                {"name": row["name"], "node_count": len(nodes)},
            )
    if error:
        raise fetcher.FetchError(error)
    with db.connect() as conn:
        return _source_row(conn, source_id)


def test_source(source_id: int, operator: str, automatic: bool = False):
    """用本地 Mihomo 核心测速；结果只反映服务器侧网络的连通性。"""
    error = ""
    with db.tx() as conn:
        row = _source_row(conn, source_id)
        if not row["snapshot_enc"]:
            raise InvalidOperation("还没有节点快照，请先抓取来源")
        snapshot = security.decrypt_text(row["snapshot_enc"])
        now = db.now()
        conn.execute(
            "UPDATE sources SET test_attempt_at=?, updated_at=? WHERE id=?",
            (now, now, source_id),
        )
        try:
            outcome = tester.test_nodes(snapshot)
        except tester.TestError as exc:
            error = str(exc)
            conn.execute(
                "UPDATE sources SET test_attempt_at=?, updated_at=? WHERE id=?",
                (now, now, source_id),
            )
            security.audit(
                conn, operator,
                _action(automatic, "测试节点连通性失败", "自动测速失败"),
                "source", source_id, {"name": row["name"], "error": error},
            )
        else:
            conn.execute(
                "UPDATE sources SET test_results=?, tested_at=?, "
                "test_attempt_at=?, updated_at=? WHERE id=?",
                (json.dumps(outcome["results"], ensure_ascii=False),
                 now, now, now, source_id),
            )
            security.audit(
                conn, operator,
                _action(automatic, "测试节点连通性", "自动测速"),
                "source", source_id,
                {"name": row["name"], "total": outcome["total"],
                 "ok": outcome["ok"], "failed": outcome["failed"]},
            )
    if error:
        raise tester.TestError(error)
    with db.connect() as conn:
        return _source_row(conn, source_id)


def refresh_provider(rp_id: int, operator: str, automatic: bool = False):
    """抓取远程规则来源并留存快照；内联来源不参与抓取。"""
    error = ""
    with db.tx() as conn:
        row = _provider_row(conn, rp_id)
        if row["kind"] != "remote":
            raise InvalidOperation("内联规则来源无需抓取")
        now = db.now()
        conn.execute(
            "UPDATE rule_providers SET last_attempt_at=?, updated_at=? WHERE id=?",
            (now, now, rp_id),
        )
        try:
            body = fetcher.fetch(row["url"])
            count = fetcher.count_rules(body, row["behavior"])
        except fetcher.FetchError as exc:
            error = str(exc)
            conn.execute(
                "UPDATE rule_providers SET last_status='failed', last_error=?, "
                "last_attempt_at=?, updated_at=? WHERE id=?",
                (error, now, now, rp_id),
            )
            security.audit(
                conn, operator,
                _action(automatic, "刷新规则来源失败", "自动抓取规则来源失败"),
                "rule_provider", rp_id, {"name": row["name"], "error": error},
            )
        else:
            text = body.decode("utf-8", "replace")
            conn.execute(
                "UPDATE rule_providers SET last_status='ok', last_error='', "
                "last_fetched_at=?, last_attempt_at=?, rule_count=?, sha256=?, "
                "content=?, updated_at=? WHERE id=?",
                (now, now, count, security.sha256_text(text), text, now, rp_id),
            )
            security.audit(
                conn, operator,
                _action(automatic, "刷新规则来源", "自动抓取规则来源"),
                "rule_provider", rp_id,
                {"name": row["name"], "rule_count": count},
            )
    if error:
        raise fetcher.FetchError(error)
    with db.connect() as conn:
        return _provider_row(conn, rp_id)
