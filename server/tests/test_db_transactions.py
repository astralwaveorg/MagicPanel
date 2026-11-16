"""写事务的并发行为：先读后写也要能扛住并发写者（WAL 下的写锁升级陷阱）。"""
import threading
import time


def test_tx_takes_write_lock_upfront(monkeypatch):
    """事务一开始就是 BEGIN IMMEDIATE：不是读到一半才去抢锁。"""
    from app import db

    seen = []
    original = db.connect

    def spy():
        conn = original()
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(db, 'connect', spy)
    with db.tx() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS _tx_probe(x)")
        conn.execute("INSERT INTO _tx_probe VALUES(1)")
    assert any(s.strip().upper().startswith('BEGIN IMMEDIATE') for s in seen), seen


def test_read_then_write_survives_concurrent_writer():
    """另一个写者在事务中途提交，本事务再写也不该报 database is locked。

    旧实现用延迟 BEGIN：事务先读到快照，另一个写者提交后，本事务的写锁升级
    在 WAL 下立刻 BUSY（等不了 busy_timeout），接口随机 500。
    """
    from app import db

    errors = []
    entered = threading.Event()

    with db.tx() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS _tx_probe(x)")
        conn.execute("DELETE FROM _tx_probe")

    def slow_writer():
        try:
            with db.tx() as conn:
                conn.execute("SELECT COUNT(*) FROM _tx_probe")
                entered.set()
                time.sleep(0.3)
                conn.execute("INSERT INTO _tx_probe VALUES(1)")
        except Exception as exc:          # pragma: no cover - 失败时给出可读信息
            errors.append(exc)

    def other_writer():
        try:
            with db.tx() as conn:
                conn.execute("INSERT INTO _tx_probe VALUES(2)")
        except Exception as exc:          # pragma: no cover
            errors.append(exc)

    first = threading.Thread(target=slow_writer)
    first.start()
    if not entered.wait(5):
        first.join(5)
        raise AssertionError(f'第一个写事务没有进入：{errors}')
    second = threading.Thread(target=other_writer)
    second.start()
    first.join(20)
    second.join(20)
    assert not errors, errors
