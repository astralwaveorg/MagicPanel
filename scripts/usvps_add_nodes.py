"""一次性生产数据修正：接入 usvps 洛杉矶 NTT 落地机（5 账户 × Reality/Hysteria2）。

在容器内执行：docker exec -i magicpanel python - < scripts/usvps_add_nodes.py
凭据从 /app/data/usvps-credentials.json 读取（ingest 成功后自动删除，避免明文滞留）。
可重复执行（幂等）：节点按 name upsert，组按 name upsert，select 组插入位置已存在则跳过。

步骤：
1. upsert 10 个本地节点（Reality 01-05 / Hysteria2 06-10，序号同账户序 astral/lvsp/lyh/dilys/agent）
2. 建 select 组「🇺🇸 美国NTT落地」，成员为这 10 个节点
3. 所有 select 组的 proxies 第二位插入该组（测试期临时安排，验证完可调）
4. 10 节点追加进 ⚡️ 自动测速 / 🇺🇸 美国自动 / 🏢 自建优先 的成员池（仅追加，不改变既有顺序）
"""
import json
import os
import sys

sys.path.insert(0, os.environ.get("MAGICPANEL_APP_PATH", "/app"))

from app import db, security
from app.services import local_nodes as ln

CREDS_PATH = os.path.join(os.environ.get("MAGICPANEL_DATA_DIR", "/app/data"),
                          "usvps-credentials.json")
GROUP = "🇺🇸 美国NTT落地"
ACCOUNTS = ["astral", "lvsp", "lyh", "dilys", "agent"]
# 机器参数与 usvps-credentials.json 一致；账户凭据从 creds 文件读取
VLESS = {"server": "192.220.75.184", "port": 443, "sni": "www.apple.com",
         "pub": "zRaM-g3w3t2W3ElS0uKbfJEU3e8VTnF_PbhysK6WpDk",
         "sid": "432ace26675328df"}
HY2 = {"server": "usb.magichub.top", "port": 58591, "sni": "usb.magichub.top"}
# 仅追加成员的既有组（自动测速池与自建兜底）
APPEND_GROUPS = ["⚡️ 自动测速", "🇺🇸 美国自动", "🏢 自建优先"]


def load_creds() -> dict:
    with open(CREDS_PATH, encoding="utf-8") as fh:
        creds = json.load(fh)
    return {a["name"]: a for a in creds["accounts"]}


def upsert_nodes(creds: dict) -> dict:
    """按 name upsert，返回 节点名 → id（Reality 在前、Hysteria2 在后）。"""
    ids: dict[str, int] = {}
    plans = []
    for i, acc in enumerate(ACCOUNTS, 1):
        plans.append((f"🇺🇸 美国NTT {i:02d}", "vless", VLESS["server"], VLESS["port"], {
            "uuid": creds[acc]["uuid"],
            "flow": "xtls-rprx-vision",
            "tls": True,
            "servername": VLESS["sni"],
            "skip_cert_verify": False,
            "network": "tcp",
            "reality_public_key": VLESS["pub"],
            "reality_short_id": VLESS["sid"],
            "udp": True,
        }, "client-fingerprint: chrome\n"))
    for i, acc in enumerate(ACCOUNTS, 1):
        plans.append((f"🇺🇸 美国NTT {i + 5:02d}", "hysteria2", HY2["server"], HY2["port"], {
            "password": creds[acc]["hy2pass"],
            "sni": HY2["sni"],
            "skip_cert_verify": False,
            "obfs": "",
            "up": 0,
            "down": 0,
            "udp": True,
        }, ""))
    with db.tx() as conn:
        max_sort = db.one(conn, "SELECT COALESCE(MAX(sort), 0) AS n FROM local_nodes")["n"]
        for idx, (name, protocol, server, port, params, extra) in enumerate(plans):
            params_enc = security.encrypt_text(json.dumps(params, ensure_ascii=False))
            extra_enc = security.encrypt_text(extra)
            row = db.one(conn, "SELECT id FROM local_nodes WHERE name=?", (name,))
            if row:
                conn.execute(
                    "UPDATE local_nodes SET node_type=?, protocol=?, server=?, port=?, "
                    "params_enc=?, extra_yaml_enc=?, enabled=1, updated_at=? WHERE id=?",
                    ("机房", protocol, server, port, params_enc, extra_enc, db.now(), row["id"]))
                ids[name] = row["id"]
                print(f"  更新节点 {name} (id={row['id']})")
            else:
                cur = conn.execute(
                    "INSERT INTO local_nodes(name, node_type, protocol, server, port, "
                    "params_enc, extra_yaml_enc, enabled, sort, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (name, "机房", protocol, server, port, params_enc, extra_enc,
                     1, max_sort + 1 + idx, db.now(), db.now()))
                ids[name] = cur.lastrowid
                print(f"  新增节点 {name} (id={cur.lastrowid})")
    return ids


def upsert_group(ids: dict) -> int:
    """独立 select 组，成员顺序 = Reality 01-05 + Hysteria2 06-10。"""
    ordered_ids = [ids[f"🇺🇸 美国NTT {i:02d}"] for i in range(1, 11)]
    local_nodes_json = json.dumps(ordered_ids, ensure_ascii=False)
    with db.tx() as conn:
        row = db.one(conn, "SELECT id FROM proxy_groups WHERE name=?", (GROUP,))
        if row:
            conn.execute(
                "UPDATE proxy_groups SET type='select', hidden=0, filter='', "
                "use_sources='[]', local_nodes=?, proxies='[]', targets='[\"*\"]', "
                "devices='[\"*\"]', updated_at=? WHERE id=?",
                (local_nodes_json, db.now(), row["id"]))
            gid = row["id"]
            print(f"  更新组 {GROUP} (id={gid})")
        else:
            sort = db.one(conn, "SELECT COALESCE(MAX(sort), 0) + 1 AS n FROM proxy_groups")["n"]
            cur = conn.execute(
                "INSERT INTO proxy_groups(name, type, sort, hidden, filter, use_sources, "
                "local_nodes, proxies, targets, devices, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (GROUP, "select", sort, 0, "", "[]", local_nodes_json, "[]",
                 "[\"*\"]", "[\"*\"]", db.now(), db.now()))
            gid = cur.lastrowid
            print(f"  新增组 {GROUP} (id={gid})")
    return gid


def insert_into_selects(gid: int) -> None:
    """所有 select 组（除本组）proxies 第二位插入组名；已存在则跳过。"""
    with db.tx() as conn:
        for g in db.all_(conn, "SELECT id, name, proxies FROM proxy_groups "
                                "WHERE type='select' AND name != ? ORDER BY id", (GROUP,)):
            proxies = json.loads(g["proxies"] or "[]")
            if GROUP in proxies:
                print(f"  跳过 {g['name']}（已在第 {proxies.index(GROUP) + 1} 位）")
                continue
            proxies.insert(min(1, len(proxies)), GROUP)
            conn.execute("UPDATE proxy_groups SET proxies=?, updated_at=? WHERE id=?",
                         (json.dumps(proxies, ensure_ascii=False), db.now(), g["id"]))
            print(f"  {g['name']}：第二位插入 → {proxies[:3]}")


def append_pools(ids: dict) -> None:
    """把 10 节点追加进自动测速池与自建兜底（仅追加，不动既有顺序）。"""
    new_ids = [ids[f"🇺🇸 美国NTT {i:02d}"] for i in range(1, 11)]
    with db.tx() as conn:
        for name in APPEND_GROUPS:
            g = db.one(conn, "SELECT id, local_nodes FROM proxy_groups WHERE name=?", (name,))
            if not g:
                print(f"  组 {name} 不存在，跳过")
                continue
            lst = json.loads(g["local_nodes"] or "[]")
            added = [i for i in new_ids if i not in lst]
            if not added:
                print(f"  跳过 {name}（节点已在池中）")
                continue
            conn.execute("UPDATE proxy_groups SET local_nodes=?, updated_at=? WHERE id=?",
                         (json.dumps(lst + added, ensure_ascii=False), db.now(), g["id"]))
            print(f"  {name}：追加 {len(added)} 个节点")


def ingest_done() -> None:
    try:
        os.remove(CREDS_PATH)
        print("  已删除明文凭据文件")
    except OSError:
        pass


def main() -> None:
    print("== 1. upsert 本地节点")
    ids = upsert_nodes(load_creds())
    print("== 2. 独立策略组")
    gid = upsert_group(ids)
    print("== 3. select 组第二位插入")
    insert_into_selects(gid)
    print("== 4. 追加自动测速/自建兜底池")
    append_pools(ids)
    ingest_done()
    print("== 完成")


if __name__ == "__main__":
    main()
