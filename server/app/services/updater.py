"""节点来源 / 规则来源的抓取与测速实现。

手动操作与内置定时任务共用这里，保证失败状态、审计和快照行为一致。
失败时先提交状态再抛出异常，避免调用方的事务回滚把失败记录一起丢掉。

写事务只用于极短的状态更新；网络请求与核心测速都在事务之外执行，
避免慢上游长期占用 SQLite 写锁（设备拉取配置会被阻塞）。
"""
import base64
import json
import threading

import yaml

from .. import config, db, security
from . import fetcher, source_nodes, tester


class NotFound(Exception):
    pass


class InvalidOperation(Exception):
    pass


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    """按 key 取互斥锁。

    锁表会随 key 数量单调增长（长跑实例下缓慢泄漏），
    这里在没有其它持有者时顺手回收，避免无限增长。
    """
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def _release_lock(key: str, lock: threading.Lock) -> None:
    with _locks_guard:
        if _locks.get(key) is lock and not lock.locked():
            _locks.pop(key, None)


def _source_row(conn, source_id: int):
    row = db.one(conn, "SELECT * FROM sources WHERE id=?", (source_id,))
    if not row:
        raise NotFound("节点来源不存在")
    return row


def _snippet_row(conn, sid: int):
    row = db.one(conn, "SELECT * FROM snippets WHERE id=?", (sid,))
    if not row:
        raise NotFound("拓展模块不存在")
    return row


def _provider_row(conn, rp_id: int):
    row = db.one(conn, "SELECT * FROM rule_providers WHERE id=?", (rp_id,))
    if not row:
        raise NotFound("规则来源不存在")
    return row


def _action(automatic: bool, manual: str, auto: str) -> str:
    return auto if automatic else manual


def _error_text(exc: Exception) -> str:
    if isinstance(exc, (fetcher.FetchError, tester.TestError)):
        return str(exc)
    return f"{type(exc).__name__}：{exc}"


def refresh_source(source_id: int, operator: str, automatic: bool = False):
    """抓取节点来源并留存快照；失败时保留最近一次成功快照。"""
    key = f"source:{source_id}"
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        raise InvalidOperation("该来源正在抓取中，请稍候再试")
    try:
        # 阶段一：短事务，记录本次尝试时间
        with db.tx() as conn:
            row = _source_row(conn, source_id)
            url = security.decrypt_text(row["url_enc"])
            ua = row["ua"]
            allow_private = bool(row["allow_private"])
            proxy = (security.decrypt_text(row["proxy_url_enc"])
                     if row["proxy_url_enc"] else "")
            name = row["name"]
            now = db.now()
            conn.execute(
                "UPDATE sources SET last_attempt_at=?, updated_at=? WHERE id=?",
                (now, now, source_id),
            )
        # 阶段二：事务外发起网络请求
        error = ""
        body = None
        nodes: list = []
        text = ""
        try:
            body = fetcher.fetch(url, ua=ua, allow_private=allow_private,
                                 proxy=proxy)
            nodes = source_nodes.extract(body)
            # 只留 proxies 段：机场订阅里的 rules / dns / 策略组与面板无关，
            # 留着既撑大快照，也会让内联模式把机场的规则和策略组混进产物。
            text = source_nodes.dump(nodes)
        except Exception as exc:  # 含 httpx.InvalidURL 等非 FetchError 异常
            error = _error_text(exc)
        # 阶段三：短事务落库结果或失败状态
        with db.tx() as conn:
            now = db.now()
            if error:
                conn.execute(
                    "UPDATE sources SET last_status='failed', last_error=?, "
                    "fail_count=fail_count+1, last_attempt_at=?, updated_at=? "
                    "WHERE id=?",
                    (error, now, now, source_id),
                )
                security.audit(
                    conn, operator,
                    _action(automatic, "刷新节点来源失败", "自动抓取节点来源失败"),
                    "source", source_id, {"name": name, "error": error},
                )
            else:
                meta = [{"name": str(n["name"]), "type": str(n["type"])}
                        for n in nodes]
                # 新快照的节点集合可能变化，旧测速结果不再可信：
                # 清空 test_results 并把 test_attempt_at 置空，调度器会在同一轮
                # 立即补测（不依赖“只分发可用节点”开关）。
                conn.execute(
                    "UPDATE sources SET last_status='ok', last_error='', "
                    "last_fetched_at=?, last_attempt_at=?, node_count=?, sha256=?, "
                    "fail_count=0, snapshot_enc=?, nodes_meta=?, test_results='{}', "
                    "tested_at=NULL, test_attempt_at=NULL, updated_at=? WHERE id=?",
                    (now, now, len(nodes), security.sha256_text(text),
                     security.encrypt_text(text),
                     json.dumps(meta, ensure_ascii=False), now, source_id),
                )
                security.audit(
                    conn, operator,
                    _action(automatic, "刷新节点来源", "自动抓取节点来源"),
                    "source", source_id,
                    {"name": name, "node_count": len(nodes)},
                )
        if error:
            raise fetcher.FetchError(error)
        with db.connect() as conn:
            return _source_row(conn, source_id)
    finally:
        lock.release()
        _release_lock(key, lock)


def test_source(source_id: int, operator: str, automatic: bool = False):
    """用本地 Mihomo 核心测速；结果只反映服务器侧网络的连通性。"""
    key = f"source:{source_id}"
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        raise InvalidOperation("该来源正在测速中，请稍候再试")
    try:
        # 阶段一：短事务，取快照并记录尝试时间
        with db.tx() as conn:
            row = _source_row(conn, source_id)
            if not row["snapshot_enc"]:
                raise InvalidOperation("还没有节点快照，请先抓取来源")
            snapshot = security.decrypt_text(row["snapshot_enc"])
            name = row["name"]
            now = db.now()
            conn.execute(
                "UPDATE sources SET test_attempt_at=?, updated_at=? WHERE id=?",
                (now, now, source_id),
            )
        # 阶段二：事务外跑核心测速
        error = ""
        outcome = None
        try:
            outcome = tester.test_nodes(snapshot)
        except Exception as exc:  # 含 yaml/编码等非 TestError 异常
            error = _error_text(exc)
        # 阶段三：短事务落库
        with db.tx() as conn:
            now = db.now()
            if error:
                conn.execute(
                    "UPDATE sources SET test_attempt_at=?, updated_at=? WHERE id=?",
                    (now, now, source_id),
                )
                security.audit(
                    conn, operator,
                    _action(automatic, "测试节点连通性失败", "自动测速失败"),
                    "source", source_id, {"name": name, "error": error},
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
                    {"name": name, "total": outcome["total"],
                     "ok": outcome["ok"], "failed": outcome["failed"]},
                )
        if error:
            raise tester.TestError(error)
        with db.connect() as conn:
            return _source_row(conn, source_id)
    finally:
        lock.release()
        _release_lock(key, lock)


def refresh_provider(rp_id: int, operator: str, automatic: bool = False):
    """抓取远程规则来源并留存快照；内联来源不参与抓取。"""
    key = f"provider:{rp_id}"
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        raise InvalidOperation("该规则来源正在抓取中，请稍候再试")
    try:
        with db.tx() as conn:
            row = _provider_row(conn, rp_id)
            if row["kind"] != "remote":
                raise InvalidOperation("内联规则来源无需抓取")
            url = row["url"]
            behavior = row["behavior"]
            fmt = row["format"] or "yaml"
            proxy = (security.decrypt_text(row["proxy_url_enc"])
                     if row["proxy_url_enc"] else "")
            name = row["name"]
            now = db.now()
            conn.execute(
                "UPDATE rule_providers SET last_attempt_at=?, updated_at=? "
                "WHERE id=?",
                (now, now, rp_id),
            )
        error = ""
        body = None
        count = 0
        try:
            body = fetcher.fetch(url, proxy=proxy)
            count = fetcher.count_rules(body, behavior, fmt)
        except Exception as exc:
            error = _error_text(exc)
        with db.tx() as conn:
            now = db.now()
            if error:
                conn.execute(
                    "UPDATE rule_providers SET last_status='failed', last_error=?, "
                    "last_attempt_at=?, updated_at=? WHERE id=?",
                    (error, now, now, rp_id),
                )
                security.audit(
                    conn, operator,
                    _action(automatic, "刷新规则来源失败", "自动抓取规则来源失败"),
                    "rule_provider", rp_id, {"name": name, "error": error},
                )
            else:
                if fmt in config.BINARY_FORMATS:
                    # 二进制格式（MRS）：按 base64 存库，下发时还原成字节，
                    # 指纹对原始字节计算，与客户端拿到的一致。
                    text = base64.b64encode(body).decode("ascii")
                    sha = security.sha256_bytes(body)
                else:
                    text = body.decode("utf-8", "replace")
                    sha = security.sha256_text(text)
                conn.execute(
                    "UPDATE rule_providers SET last_status='ok', last_error='', "
                    "last_fetched_at=?, last_attempt_at=?, rule_count=?, sha256=?, "
                    "content=?, updated_at=? WHERE id=?",
                    (now, now, count, sha, text, now, rp_id),
                )
                security.audit(
                    conn, operator,
                    _action(automatic, "刷新规则来源", "自动抓取规则来源"),
                    "rule_provider", rp_id,
                    {"name": name, "rule_count": count},
                )
        if error:
            raise fetcher.FetchError(error)
        with db.connect() as conn:
            return _provider_row(conn, rp_id)
    finally:
        lock.release()
        _release_lock(key, lock)


def refresh_snippet(sid: int, operator: str, automatic: bool = False):
    """抓取远程拓展模块并留存快照；内联拓展模块不参与抓取。

    与 refresh_provider 同构：失败时先提交状态再抛异常，
    并保留上一次可用内容（内容进产物，坏内容会直接打坏客户端配置）。
    """
    key = f"snippet:{sid}"
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        raise InvalidOperation("该拓展模块正在抓取中，请稍候再试")
    try:
        with db.tx() as conn:
            row = _snippet_row(conn, sid)
            if row["source"] != "remote":
                raise InvalidOperation("内联拓展模块无需抓取")
            url = row["url"]
            proxy = (security.decrypt_text(row["proxy_url_enc"])
                     if row["proxy_url_enc"] else "")
            name = row["name"]
            now = db.now()
            conn.execute(
                "UPDATE snippets SET last_attempt_at=?, updated_at=? WHERE id=?",
                (now, now, sid),
            )
        error = ""
        body = None
        try:
            body = fetcher.fetch(url, proxy=proxy)
            # 抓到的内容仍要过拓展模块的校验：非法 YAML 或结构键会打坏产物
            text = body.decode("utf-8", "replace")
            _validate_snippet_content(text)
        except Exception as exc:
            error = _error_text(exc)
        with db.tx() as conn:
            now = db.now()
            if error:
                conn.execute(
                    "UPDATE snippets SET last_status='failed', last_error=?, "
                    "last_attempt_at=?, updated_at=? WHERE id=?",
                    (error, now, now, sid),
                )
                security.audit(
                    conn, operator,
                    _action(automatic, "刷新拓展模块失败", "自动抓取拓展模块失败"),
                    "snippet", sid, {"name": name, "error": error},
                )
            else:
                conn.execute(
                    "UPDATE snippets SET last_status='ok', last_error='', "
                    "last_fetched_at=?, last_attempt_at=?, content=?, updated_at=? "
                    "WHERE id=?",
                    (now, now, text, now, sid),
                )
                security.audit(
                    conn, operator,
                    _action(automatic, "刷新拓展模块", "自动抓取拓展模块"),
                    "snippet", sid, {"name": name},
                )
        if error:
            raise fetcher.FetchError(error)
        with db.connect() as conn:
            return _snippet_row(conn, sid)
    finally:
        lock.release()
        _release_lock(key, lock)


def _validate_snippet_content(text: str) -> None:
    """远程抓到的片段必须仍是合法的非空 YAML 映射，且不含结构键。"""
    from . import base_config as base_config_service
    try:
        fragment = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise fetcher.FetchError(f"内容不是合法 YAML：{exc}") from exc
    if not isinstance(fragment, dict) or not fragment:
        raise fetcher.FetchError("内容必须是非空的 YAML 映射（键值结构）")
    for key, reason in base_config_service.PROTECTED_KEYS.items():
        if key in fragment:
            raise fetcher.FetchError(f"拓展模块不能包含“{key}”：{reason}")
