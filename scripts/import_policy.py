"""把策略快照导入 MagicPanel 数据库（用于复现线上策略 / 灾后重建）。

行为：
1. 校验快照 `digest`（防止文件被手工改坏）；
2. 默认先备份数据库为 `<db>.before-import-<时间戳>`；
3. 整表替换 `rules` / `proxy_groups` / `rule_providers`（保留自增 id）；
4. `--dry-run` 只打印将要写入的条数。

**不触碰** `sources` / `local_nodes` / `devices`（凭据仍以线上为准）。

用法：

    python scripts/import_policy.py --db /app/data/magicpanel.db \
        --in policy/snapshots/2026-11-10.json [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

TABLES = ("variants", "rules", "proxy_groups", "rule_providers")


def _load(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    claimed = data.pop("digest", None)
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if claimed != actual:
        raise SystemExit(
            f"快照校验失败：digest 不符（claimed={claimed} actual={actual}）"
        )
    data["digest"] = claimed
    return data


def _replace(conn: sqlite3.Connection, table: str, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    columns = list(rows[0].keys())
    # 补齐目标库「NOT NULL 且无默认值」而快照没有的列（导出白名单不含
    # created_at/updated_at；老库靠建表时的默认值兜底，全新库会直接失败）
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for info in conn.execute(f"PRAGMA table_info({table})"):  # noqa: S608
        name, notnull, dflt = info[1], info[3], info[4]
        if name in columns or not notnull or dflt is not None:
            continue
        columns.append(name)
        filler = now if name.endswith("_at") else ""
        for row in rows:
            row[name] = filler
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"  # noqa: S608
    conn.execute(f"DELETE FROM {table}")  # noqa: S608 - 表名来自固定常量
    conn.executemany(sql, [[row.get(c) for c in columns] for row in rows])
    if table == "rule_providers":
        _refill_inline_content(conn)
    return len(rows)


def _refill_inline_content(conn: sqlite3.Connection) -> int:
    """整表导入后回填内联来源的分发正文。

    导出白名单不含 `content`（可能含二进制 MRS 缓存），因此整表导入后
    内联来源的正文快照为空——feed 分发 404，而远程抓取任务不会补内联
    来源（2026-11-21 线上事故：connectivity-check / dns-direct /
    lvsp-direct 三行 404）。这里按 `inline_content` 原样回填，并同步
    计数与指纹（content 的 sha256 即分发 ETag，必须逐字节一致）。
    rule_count 用简化口径（非注释、非 payload 行），仅用于界面显示。
    """
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT id, inline_content, format FROM rule_providers "
        "WHERE kind='inline' AND inline_content != ''"
    ).fetchall()
    fixed = 0
    for rid, text, fmt in rows:
        if (fmt or "yaml") == "mrs":
            count = 0
        else:
            count = sum(
                1 for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
                and ln.strip() != "payload:"
            )
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        conn.execute(
            "UPDATE rule_providers SET content=?, rule_count=?, sha256=?, "
            "last_status='ok', last_fetched_at=COALESCE(last_fetched_at, ?) "
            "WHERE id=?",
            (text, count, sha, now, rid),
        )
        fixed += 1
    if fixed:
        print(f"  已回填内联来源分发正文: {fixed} 条")
    return fixed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入 MagicPanel 策略快照")
    parser.add_argument("--db", required=True, help="magicpanel.db 路径")
    parser.add_argument("--in", dest="src", required=True, help="快照 JSON 路径")
    parser.add_argument("--dry-run", action="store_true", help="只校验与统计，不写库")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    src_path = Path(args.src)
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 1
    if not src_path.is_file():
        print(f"快照不存在：{src_path}", file=sys.stderr)
        return 1

    data = _load(src_path)
    meta = data.get("meta") or {}
    print(
        f"快照 {src_path.name}：导出于 {data.get('exported_at')}，"
        f"来自构建 {meta.get('build_id')}"
    )

    for table in TABLES:
        rows = data.get(table) or []
        print(f"  {table}: {len(rows)} 条")
        if args.dry_run:
            continue

    if args.dry_run:
        print("dry-run：未写库")
        return 0

    backup = db_path.with_suffix(db_path.suffix + f".before-import-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(db_path, backup)
    print(f"已备份：{backup}")

    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for table in TABLES:
                count = _replace(conn, table, data.get(table) or [])
                print(f"  已写入 {table}: {count} 条")
    finally:
        conn.close()

    print("完成。请重新构建并发布：")
    print(
        "  docker exec magicpanel python -c "
        '"from app.routers import builds; '
        "print(builds.create_build('import', note='导入策略快照'))\""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
