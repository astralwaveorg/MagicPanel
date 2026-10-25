"""拖拽排序：sort 键必须全局唯一，且子集重排不打乱区间外的行。

客户端与界面都按 (sort, id) 排序，sort 本身没有语义、只负责定序。
两个坑都在这里：

1. sort 值重复时，两个组拿到同一个 sort，相对顺序退回由 id 决定，
   拖动不会有任何效果（界面表现为"拖了没反应"）。重排前必须消歧。
2. 子集重排时若把子集的值原地互换，子集跨过的区间内其它行会被挤到
   错误的位置。这里按"连续块"语义处理：子集放回它占据的位置区间，
   区间内其余行整体顺延，相对顺序不变。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import db  # noqa: E402


def _fresh(rows):
    """建一张只有 id/sort 的小表，返回连接（每次重建前先关掉旧的）。"""
    for conn in getattr(_fresh, "_conns", []):
        conn.close()
    _fresh._conns = []
    conn = db.connect()
    _fresh._conns.append(conn)
    conn.executescript("DROP TABLE IF EXISTS t_sort_demo;")
    conn.executescript(
        "CREATE TABLE t_sort_demo (id INTEGER PRIMARY KEY, sort INTEGER);")
    for rid, val in rows:
        conn.execute("INSERT INTO t_sort_demo VALUES (?,?)", (rid, val))
    return conn


def _order(conn):
    return [r["id"] for r in db.all_(
        conn, "SELECT id FROM t_sort_demo ORDER BY sort, id")]


def _rows(conn):
    return [(r["id"], r["sort"]) for r in db.all_(
        conn, "SELECT id, sort FROM t_sort_demo ORDER BY sort, id")]


def test_unchanged_order_keeps_sort_values():
    """相对顺序没变时，sort 数值一个都不能动。"""
    conn = _fresh([(1, 0), (2, 3), (3, 6), (4, 9)])
    db.reorder_subset(conn, "t_sort_demo", [1, 2, 3, 4])
    assert _rows(conn) == [(1, 0), (2, 3), (3, 6), (4, 9)]


def test_adjacent_subset_swap_takes_effect():
    """相邻两项互换：顺序要变，区间外的行不动。"""
    conn = _fresh([(1, 0), (2, 3), (3, 6), (4, 9)])
    db.reorder_subset(conn, "t_sort_demo", [3, 2])
    assert _order(conn) == [1, 3, 2, 4]
    assert dict(_rows(conn))[1] == 0
    assert dict(_rows(conn))[4] == 9


def test_duplicate_sort_values_can_be_reordered():
    """sort 值重复的两组：拖动必须能换序，重排后 sort 全局唯一。"""
    conn = _fresh([(1, 0), (2, 6), (3, 6), (4, 9)])
    db.reorder_subset(conn, "t_sort_demo", [3, 2])
    assert _order(conn) == [1, 3, 2, 4]
    assert len({s for _, s in _rows(conn)}) == 4


def test_duplicate_sort_values_keep_order_when_unchanged():
    """值重复但相对顺序没变：顺序保持，同时把重复消掉。"""
    conn = _fresh([(1, 0), (2, 6), (3, 6), (4, 9)])
    db.reorder_subset(conn, "t_sort_demo", [1, 2, 3, 4])
    assert _order(conn) == [1, 2, 3, 4]
    assert len({s for _, s in _rows(conn)}) == 4


def test_non_contiguous_subset_keeps_others_relative_order():
    """跨段子集：子集按新顺序，区间内其余行的相对顺序不能变。"""
    conn = _fresh([(1, 0), (2, 3), (3, 6), (4, 9)])
    db.reorder_subset(conn, "t_sort_demo", [4, 1])
    assert _order(conn) == [4, 1, 2, 3]


def test_full_reorder_follows_submitted_order():
    """全量重排：顺序完全按提交的 id 数组，sort 仍然唯一。"""
    conn = _fresh([(1, 0), (2, 3), (3, 6), (4, 9)])
    db.reorder_subset(conn, "t_sort_demo", [4, 3, 2, 1])
    assert _order(conn) == [4, 3, 2, 1]
    assert len({s for _, s in _rows(conn)}) == 4


def test_invalid_ids_rejected_without_side_effects():
    """id 重复或含不存在的 id：一律拒绝，且不动数据。"""
    conn = _fresh([(1, 0), (2, 3), (3, 6), (4, 9)])
    before = _rows(conn)
    assert db.reorder_subset(conn, "t_sort_demo", [1, 1, 2]) == 0
    assert _rows(conn) == before
    assert db.reorder_subset(conn, "t_sort_demo", [1, 99]) == 0
    assert _rows(conn) == before
