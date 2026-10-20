"""生产差异化配置：按目标区分策略组、分流规则与目标级基础配置。

背景：改造前 8 个发布目标只产出 2 份完全相同的产物；本脚本让每个目标
按“角色”真正不同：Mac mini（常驻服务）不需要手动交互组与下载器进程规则，
Apple TV 不需要手动挑节点与网盘分流，桌面端保留进程规则。

可重复执行（幂等）。
"""
import json
import sys

sys.path.insert(0, "/app")

from app import db, security
from app.services import base_config as bc

# 目标改名：名字体现角色，而不是机型
TARGET_RENAMES = {
    "stash-macos": "stash-macos-desktop",     # MacBook：日常桌面
    "stash-macmini": "stash-macos-server",     # Mac mini：常驻服务
}

DEVICE_RENAMES = {
    "Clash-Windows": "Mihomo-Windows",
    "Flclash-Android": "FlClash-Android",
}

# 手动交互组：需要人挑节点，适用于桌面与移动端；电视端与常驻服务不需要
MANUAL_GROUPS = ["手动选择", "美国手动", "白月光手动", "牛逼手动", "神龙手动"]
INTERACTIVE_TARGETS = [
    "stash-macos-desktop", "stash-ios", "stash-android", "stash-windows",
    "mihomo-android", "mihomo-windows",
]
# 网盘分流：电视端与常驻服务用不到
MEDIA_GROUPS = ["百度网盘"]
MEDIA_TARGETS = [
    "stash-macos-desktop", "stash-ios", "stash-android", "stash-windows",
    "mihomo-android", "mihomo-windows",
]
# 下载器进程规则：只桌面端有意义
DESKTOP_ONLY_TARGETS = ["stash-macos-desktop", "stash-windows", "mihomo-windows"]


def rename_targets(conn) -> list:
    changed = []
    for old, new in TARGET_RENAMES.items():
        row = db.one(conn, "SELECT id FROM targets WHERE name=?", (old,))
        if not row:
            continue
        exists = db.one(conn, "SELECT id FROM targets WHERE name=?", (new,))
        if exists:
            continue
        conn.execute("UPDATE targets SET name=?, updated_at=? WHERE id=?",
                     (new, db.now(), row["id"]))
        changed.append(f"{old} → {new}")
    return changed


def rename_devices(conn) -> list:
    changed = []
    for old, new in DEVICE_RENAMES.items():
        row = db.one(conn, "SELECT id FROM devices WHERE name=?", (old,))
        if not row:
            continue
        if db.one(conn, "SELECT id FROM devices WHERE name=?", (new,)):
            continue
        conn.execute("UPDATE devices SET name=? WHERE id=?", (new, row["id"]))
        changed.append(f"{old} → {new}")
    return changed


def scope_groups(conn) -> int:
    count = 0
    for names, targets in ((MANUAL_GROUPS, INTERACTIVE_TARGETS),
                           (MEDIA_GROUPS, MEDIA_TARGETS)):
        for name in names:
            row = db.one(conn, "SELECT id, targets FROM proxy_groups WHERE name=?", (name,))
            if not row:
                continue
            value = json.dumps(targets, ensure_ascii=False)
            if row["targets"] != value:
                conn.execute("UPDATE proxy_groups SET targets=?, updated_at=? WHERE id=?",
                             (value, db.now(), row["id"]))
                count += 1
    return count


def scope_rules(conn) -> int:
    count = 0
    now = db.now()
    # 进程名规则：仅桌面目标
    for row in db.all_(conn, "SELECT id, targets FROM rules "
                             "WHERE type='PROCESS-NAME' AND enabled=1"):
        value = json.dumps(DESKTOP_ONLY_TARGETS, ensure_ascii=False)
        if row["targets"] != value:
            conn.execute("UPDATE rules SET targets=?, updated_at=? WHERE id=?",
                         (value, now, row["id"]))
            count += 1
    # 百度网盘规则：跟随百度网盘组
    for row in db.all_(conn, "SELECT id, targets FROM rules "
                             "WHERE target='百度网盘' AND enabled=1"):
        value = json.dumps(MEDIA_TARGETS, ensure_ascii=False)
        if row["targets"] != value:
            conn.execute("UPDATE rules SET targets=?, updated_at=? WHERE id=?",
                         (value, now, row["id"]))
            count += 1
    return count


def server_base_config(conn) -> bool:
    """Mac mini（常驻服务）：更安静的日志 + 内网域名走系统解析。"""
    row = db.one(conn, "SELECT * FROM base_configs "
                       "WHERE engine='stash' AND target='stash-macos-server'")
    doc = {
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "dns": {
            # 自带解析链，不依赖客户端兜底；内网域名走系统解析
            "nameserver": [
                "https://dns.alidns.com/dns-query",
                "https://doh.pub/dns-query",
            ],
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "proxy-server-nameserver": ["223.5.5.5", "119.29.29.29"],
            "nameserver-policy": {
                "+.lan": "system",
                "+.local": "system",
            },
        },
    }
    text = bc.to_yaml(bc.normalize(doc))
    if row and row["content"] == text:
        return False
    conn.execute(
        "INSERT INTO base_configs(engine, target, content, updated_at) "
        "VALUES(?,?,?,?) ON CONFLICT(engine, target) DO UPDATE SET "
        "content=excluded.content, updated_at=excluded.updated_at",
        ("stash", "stash-macos-server", text, db.now()))
    return True


def main() -> None:
    with db.tx() as conn:
        renamed_targets = rename_targets(conn)
        renamed_devices = rename_devices(conn)
        groups = scope_groups(conn)
        rules = scope_rules(conn)
        server = server_base_config(conn)
        security.audit(conn, "astral", "应用目标差异化配置", "policy", "",
                       {"targets": renamed_targets, "devices": renamed_devices,
                        "groups_scoped": groups, "rules_scoped": rules,
                        "server_base": server})
    print(json.dumps({
        "renamed_targets": renamed_targets,
        "renamed_devices": renamed_devices,
        "groups_scoped": groups,
        "rules_scoped": rules,
        "server_base": server,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
