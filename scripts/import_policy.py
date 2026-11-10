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

TABLES = ("rules", "proxy_groups", "rule_providers")


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
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"  # noqa: S608
    conn.execute(f"DELETE FROM {table}")  # noqa: S608 - 表名来自固定常量
    conn.executemany(sql, [[row.get(c) for c in columns] for row in rows])
    return len(rows)


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
