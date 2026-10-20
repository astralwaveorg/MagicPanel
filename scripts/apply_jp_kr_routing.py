"""生产配置：日韩自动组 + 内联规则集 + 机房优先。

一次性脚本（可重复执行）：
1. 新建「日韩自动」组：url-test（自动测速取最优），过滤日本 + 韩国节点，
   节点来源与其它「自动」组一致；
2. 新建内联规则集「日韩服务」（behavior=domain）与「日韩服务-IP」（behavior=ipcidr），
   把指定域名与 IP 收进规则集，避免散落成十几条独立规则；
3. 新增两条 RULE-SET 规则，把这两个规则集指向「日韩自动」；
4. 「日韩自动」加入「节点选择」，便于手工选择；
5. 「美国优先」改为本地美国机房节点优先（配合策略组的"本地节点排在最前"）。
"""
import json
import os
import sys

# 容器内的应用包在 /app，仓库里在 server/app —— 两种位置都支持
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _candidate in (os.path.join(_HERE, "server"), _HERE, "/app"):
    if os.path.isdir(os.path.join(_candidate, "app")):
        sys.path.insert(0, _candidate)
        break

from app import db, security  # noqa: E402

# 需要走日韩出口的域名（用 DOMAIN-SUFFIX，www.xxx 会被 xxx 覆盖，故去重）
JP_KR_DOMAINS = [
    "panel.eoysky.com",
    "bot.eoysky.com",
    "cookie.astralwave.vip",
    "sub.rsshub.in",
    "ql.astralwave.vip",
    "rsshub.in",
    "www.rsshub.in",
    "dilyslyu.com",
    "www.dilyslyu.com",
    "oapi.dnscli.top",
]
# 需要走日韩出口的 IP（IP-CIDR 单独放一个 ipcidr 规则集）
JP_KR_IPS = ["158.179.167.131"]

GROUP_NAME = "日韩自动"
DOMAIN_SET = "日韩服务"
IP_SET = "日韩服务-IP"

# 日本 + 韩国节点的名称过滤（与其它「自动」组同构）
JP_KR_FILTER = (
    "(?i)🇯🇵|🇰🇷|日本|日 本|韩国|韓國|Japan|Korea|"
    "(^|[^A-Za-z])(JP|KR)([^A-Za-z]|$)"
)


def _set_content(conn, name: str, behavior: str, payload: list[str]) -> bool:
    """新建或更新内联规则集。"""
    content = "payload:\n" + "".join(f"  - {line}\n" for line in payload)
    row = db.one(conn, "SELECT * FROM rule_providers WHERE name=?", (name,))
    if row:
        if row["kind"] == "inline" and row["content"] == content:
            return False
        conn.execute(
            "UPDATE rule_providers SET behavior=?, format='yaml', kind='inline', "
            "inline_content=?, content=?, enabled=1, updated_at=? WHERE id=?",
            (behavior, content, content, db.now(), row["id"]),
        )
        return True
    now = db.now()
    conn.execute(
        "INSERT INTO rule_providers(name, behavior, format, kind, interval, "
        "client_interval, enabled, inline_content, content, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (name, behavior, "yaml", "inline", 86400, 0, 1, content, content, now, now),
    )
    return True


def _ensure_rule(conn, rule_type: str, value: str, target: str) -> bool:
    row = db.one(conn, "SELECT id FROM rules WHERE type=? AND value=? AND target=?",
                 (rule_type, value, target))
    if row:
        return False
    sort = (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM rules"))["s"]
    now = db.now()
    conn.execute(
        "INSERT INTO rules(sort, type, value, target, enabled, note, no_resolve, "
        "targets, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (sort, rule_type, value, target, 1, "日韩出口", 0, "[]", now, now),
    )
    return True


def main() -> None:
    with db.tx() as conn:
        # 1) 日韩自动组
        sources = [r["name"] for r in db.all_(
            conn, "SELECT name FROM sources WHERE enabled=1 ORDER BY id")]
        group = db.one(conn, "SELECT * FROM proxy_groups WHERE name=?", (GROUP_NAME,))
        if not group:
            sort = (db.one(conn, "SELECT COALESCE(MAX(sort),0)+1 AS s FROM proxy_groups"))["s"]
            conn.execute(
                "INSERT INTO proxy_groups(name, type, sort, hidden, filter, use_sources, "
                "local_nodes, proxies, url, interval, timeout, tolerance, lazy, strategy, "
                "targets, local_first, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (GROUP_NAME, "url-test", sort, 1, JP_KR_FILTER,
                 json.dumps(sources, ensure_ascii=False), "[]", "[]",
                 "https://www.gstatic.com/generate_204", 600, 8000, 150, 1, "", "[]", 0,
                 db.now(), db.now()),
            )
            created_group = True
        else:
            conn.execute(
                "UPDATE proxy_groups SET type='url-test', filter=?, use_sources=?, "
                "hidden=1, updated_at=? WHERE id=?",
                (JP_KR_FILTER, json.dumps(sources, ensure_ascii=False), db.now(),
                 group["id"]),
            )
            created_group = False

        # 2) 内联规则集（域名去重：www.x 已被 x 覆盖）
        domains = []
        for name in JP_KR_DOMAINS:
            if any(name == d or name.endswith("." + d) for d in domains):
                continue
            domains.append(name)
        domain_payload = [f"DOMAIN-SUFFIX,{d}" for d in domains]
        ip_payload = [f"IP-CIDR,{ip}/32,no-resolve" for ip in JP_KR_IPS]
        set1 = _set_content(conn, DOMAIN_SET, "domain", domain_payload)
        set2 = _set_content(conn, IP_SET, "ipcidr", ip_payload)

        # 3) 规则
        rule1 = _ensure_rule(conn, "RULE-SET", DOMAIN_SET, GROUP_NAME)
        rule2 = _ensure_rule(conn, "RULE-SET", IP_SET, GROUP_NAME)

        # 4) 节点选择里加入日韩自动
        pick = db.one(conn, "SELECT * FROM proxy_groups WHERE name='节点选择'")
        members = json.loads(pick["proxies"] or "[]")
        added_pick = False
        if GROUP_NAME not in members:
            members.insert(members.index("日本自动") + 1 if "日本自动" in members
                           else len(members), GROUP_NAME)
            conn.execute("UPDATE proxy_groups SET proxies=?, updated_at=? WHERE id=?",
                         (json.dumps(members, ensure_ascii=False), db.now(), pick["id"]))
            added_pick = True

        # 5) 美国优先：本地美国机房节点优先
        us_local = [int(r["id"]) for r in db.all_(
            conn, "SELECT id, name FROM local_nodes WHERE enabled=1 ORDER BY id")
            if "美国" in r["name"]]
        us_group = db.one(conn, "SELECT * FROM proxy_groups WHERE name='美国优先'")
        changed_us = False
        if us_group and us_local:
            before = (json.loads(us_group["local_nodes"] or "[]"),
                      us_group["local_first"])
            if before != (us_local, 1):
                conn.execute(
                    "UPDATE proxy_groups SET local_nodes=?, local_first=1, updated_at=? "
                    "WHERE id=?", (json.dumps(us_local), db.now(), us_group["id"]))
                changed_us = True

        security.audit(conn, "系统", "配置日韩自动与机房优先", "group", "",
                       {"group": GROUP_NAME, "domains": domains, "ips": JP_KR_IPS,
                        "us_local": us_local})
        print(json.dumps({
            "created_group": created_group,
            "domain_set_updated": set1,
            "ip_set_updated": set2,
            "rules_added": [rule1, rule2],
            "pick_added": added_pick,
            "us_local_first": changed_us,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
