"""一次性生产数据修正：百度网盘分流、规则来源行为、客户端更新间隔。

在容器内执行：docker exec -i magicpanel python - < scripts/apply_production_fixes.py
可重复执行（幂等）。
"""
import json
import os
import sys

# 容器内默认 /app；本地测试可用 MAGICPANEL_APP_PATH 覆盖
sys.path.insert(0, os.environ.get("MAGICPANEL_APP_PATH", "/app"))

from app import db, security
from app.services import local_nodes as ln

# 百度网盘使用到的域名（pan/yun/pcs 为网盘与传输，baidupcs/bcebos 为对象存储）
BAIDU_DOMAINS = [
    "pan.baidu.com",
    "yun.baidu.com",
    "pcs.baidu.com",
    "d.pcs.baidu.com",
    "nd.pcs.baidu.com",
    "baidupcs.com",
    "bcebos.com",
    "issuepcdn.baidu.com",
    "bdstatic.com",
    "baiduhstatic.com",
]
GROUP_NAME = "百度网盘"
RULE_NOTE = "百度网盘走代理（Stash 对代理流量默认阻断 QUIC，直连不回退）"


def ensure_group(conn) -> int:
    row = db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (GROUP_NAME,))
    if row:
        return row["id"]
    sort = db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM proxy_groups")["s"]
    now = db.now()
    cur = conn.execute(
        "INSERT INTO proxy_groups(name, type, sort, hidden, filter, use_sources, "
        "local_nodes, proxies, url, interval, timeout, tolerance, lazy, strategy, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (GROUP_NAME, "select", sort, 0, "", "[]", "[]",
         json.dumps(["节点选择", "DIRECT"], ensure_ascii=False),
         "https://www.gstatic.com/generate_204", 600, 8000, 150, 1, "", now, now),
    )
    security.audit(conn, "astral", "新增策略组", "group", cur.lastrowid,
                   {"name": GROUP_NAME, "reason": RULE_NOTE})
    return cur.lastrowid


def insert_baidu_rules(conn) -> int:
    cn = db.one(conn, "SELECT id, sort FROM rules WHERE type='RULE-SET' AND value='cn'")
    if not cn:
        return 0
    pending = [d for d in BAIDU_DOMAINS if not db.one(
        conn, "SELECT id FROM rules WHERE type='DOMAIN-SUFFIX' AND value=?", (d,))]
    if not pending:
        return 0
    # 让出位置：sort 大于等于 cn 的规则整体后移
    conn.execute("UPDATE rules SET sort = sort + ? WHERE sort >= ?",
                 (len(pending), cn["sort"]))
    now = db.now()
    for offset, domain in enumerate(pending):
        conn.execute(
            "INSERT INTO rules(sort, type, value, target, enabled, note, no_resolve, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (cn["sort"] + offset, "DOMAIN-SUFFIX", domain, GROUP_NAME, 1,
             RULE_NOTE, 0, now, now),
        )
    security.audit(conn, "astral", "新增分流规则", "rule", "",
                   {"domains": pending, "target": GROUP_NAME})
    return len(pending)


def main() -> None:
    with db.tx() as conn:
        group_id = ensure_group(conn)
        added = insert_baidu_rules(conn)
        now = db.now()
        for name in ("Google", "GitHub"):
            conn.execute(
                "UPDATE rule_providers SET behavior='domain', updated_at=? "
                "WHERE name=? AND behavior='classical'", (now, name))
        conn.execute("UPDATE sources SET client_interval=3600, updated_at=?", (now,))
        conn.execute("UPDATE rule_providers SET client_interval=3600, updated_at=?", (now,))
        # 本地节点带宽字段规范化为整数 Mbps（Stash 用 down-speed，Mihomo 用 down）
        for row in db.all_(conn, "SELECT id, params_enc FROM local_nodes "
                                 "WHERE protocol='hysteria2'"):
            params = json.loads(security.decrypt_text(row["params_enc"]))
            changed = False
            for key in ("up", "down"):
                if key in params:
                    mbps = ln._bandwidth_mbps(params[key])
                    if mbps != params[key]:
                        params[key] = mbps
                        changed = True
            if changed:
                conn.execute(
                    "UPDATE local_nodes SET params_enc=?, updated_at=? WHERE id=?",
                    (security.encrypt_text(json.dumps(params, ensure_ascii=False)),
                     now, row["id"]))
    print(json.dumps({
        "group_id": group_id,
        "baidu_rules_added": added,
        "client_interval": 3600,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
