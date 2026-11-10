"""导出线上策略（规则 / 策略组 / 规则来源）为可入库的快照 JSON。

只导出无凭据的三张表：
- `rules`：分流规则（含顺序 `sort`）
- `proxy_groups`：策略组
- `rule_providers`：规则来源元数据

**不导出**：`sources`（订阅地址含令牌）、`local_nodes`（节点凭据）、
`devices`（设备令牌）。因此快照可以安全提交到仓库。

用法（容器内或本机均可）：

    python scripts/export_policy.py --db /app/data/magicpanel.db --out policy/snapshots/xxx.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

TABLES: dict[str, str] = {
    # 表名 -> 排序子句（顺序本身就是策略的一部分）
    "rules": "ORDER BY sort, id",
    "proxy_groups": "ORDER BY sort, id",
    "rule_providers": "ORDER BY name",
}

# `rule_providers` 里有两列不能入库：
# - `content`：MRS 二进制缓存，可重新下载，且体积巨大
# - `proxy_url_enc`：加密后的订阅地址，属于凭据
# 因此对该表使用列白名单，其余表整行导出（不含凭据）。
PROVIDER_COLUMNS = (
    "id",
    "name",
    "behavior",
    "format",
    "kind",
    "url",
    "repo_path",
    "inline_content",
    "interval",
    "client_interval",
    "enabled",
)


def _rows(conn: sqlite3.Connection, table: str, order_by: str) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    columns = "*" if table != "rule_providers" else ",".join(PROVIDER_COLUMNS)
    # 表名与列名均来自本文件的固定常量，不存在注入面
    sql = f"SELECT {columns} FROM {table} {order_by}"
    return [dict(row) for row in conn.execute(sql)]


def _build_meta(conn: sqlite3.Connection) -> dict[str, object]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, status, verify_status, policy_sha, created_at "
        "FROM builds ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {}
    return {
        "build_id": row["id"],
        "build_status": row["status"],
        "verify_status": row["verify_status"],
        "policy_sha": row["policy_sha"],
        "build_created_at": row["created_at"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 MagicPanel 策略快照（无凭据）")
    parser.add_argument("--db", required=True, help="magicpanel.db 路径")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        payload: dict[str, object] = {
            "schema": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "meta": _build_meta(conn),
        }
        for table, order_by in TABLES.items():
            payload[table] = _rows(conn, table, order_by)
    finally:
        conn.close()

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = " ".join(f"{t}={len(payload[t])}" for t in TABLES)  # type: ignore[arg-type]
    print(f"已导出 {out_path}：{counts} digest={payload['digest'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
