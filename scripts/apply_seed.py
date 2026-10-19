#!/usr/bin/env python3
"""把种子数据幂等写入数据库（在容器内执行）。

用法：docker exec -i -e PYTHONPATH=/app -w /app magicpanel python - < /tmp/seed_payload.py
实际配合：先 build_seed.py 生成 JSON，再本脚本读取。
按名称查重，已存在的条目跳过；节点来源符号 SRC:<关键字> 按子串匹配实际来源名。
"""
import json
import sys

from app import db, security


def resolve_sources(conn) -> dict:
    names = [r["name"] for r in db.all_(conn, "SELECT name FROM sources")]
    mapping = {}
    for kw in ("神龙", "白月光", "牛逼"):
        hit = [n for n in names if kw in n]
        if not hit:
            raise SystemExit(f"数据库中找不到包含“{kw}”的节点来源")
        mapping[f"SRC:{kw}"] = hit[0]
    return mapping


def main() -> None:
    payload = json.load(sys.stdin)
    stats = {"rule_providers": [0, 0], "groups": [0, 0], "rules": [0, 0], "targets": [0, 0]}
    with db.tx() as conn:
        mapping = resolve_sources(conn)
        now = db.now()

        for rp in payload["rule_providers"]:
            if db.one(conn, "SELECT id FROM rule_providers WHERE name=?", (rp["name"],)):
                stats["rule_providers"][1] += 1
                continue
            conn.execute(
                "INSERT INTO rule_providers(name, behavior, format, kind, url, "
                "inline_content, interval, enabled, last_status, created_at, updated_at) "
                "VALUES(?,?,?, 'remote', ?, '', ?, 1, 'never', ?, ?)",
                (rp["name"], rp["behavior"], rp["format"], rp["url"],
                 rp["interval"], now, now),
            )
            stats["rule_providers"][0] += 1

        for g in payload["groups"]:
            if db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (g["name"],)):
                stats["groups"][1] += 1
                continue
            sort = db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM proxy_groups")["s"]
            use = [mapping.get(u, u) for u in g["use_sources"]]
            conn.execute(
                "INSERT INTO proxy_groups(name, type, sort, hidden, filter, use_sources, "
                "proxies, url, interval, timeout, tolerance, lazy, strategy, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'',?,?)",
                (g["name"], g["type"], sort, int(g["hidden"]), g["filter"],
                 json.dumps(use, ensure_ascii=False),
                 json.dumps(g["proxies"], ensure_ascii=False),
                 g["url"], g["interval"], g["timeout"], g["tolerance"],
                 int(g["lazy"]), now, now),
            )
            stats["groups"][0] += 1

        for r in payload["rules"]:
            dup = db.one(
                conn, "SELECT id FROM rules WHERE type=? AND value=? AND target=?",
                (r["type"], r["value"], r["target"]))
            if dup:
                stats["rules"][1] += 1
                continue
            sort = db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM rules")["s"]
            conn.execute(
                "INSERT INTO rules(sort, type, value, target, enabled, note, no_resolve, "
                "created_at, updated_at) VALUES(?,?,?,?,1,?,?,?,?)",
                (sort, r["type"], r["value"], r["target"], r.get("note", ""),
                 int(r.get("no_resolve", False)), now, now),
            )
            stats["rules"][0] += 1

        for t in payload["targets"]:
            if db.one(conn, "SELECT id FROM targets WHERE name=?", (t["name"],)):
                stats["targets"][1] += 1
                continue
            conn.execute(
                "INSERT INTO targets(name, engine, platform, description, extra_yaml, "
                "update_interval, created_at, updated_at) VALUES(?,?,?,?,'',12,?,?)",
                (t["name"], t["engine"], t["platform"], t.get("description", ""), now, now),
            )
            stats["targets"][0] += 1

        security.audit(conn, "seed", "导入种子数据", "system", "", stats)

    print(json.dumps({"来源映射": mapping, "统计(新增/跳过)": stats},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
