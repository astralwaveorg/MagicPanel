#!/usr/bin/env python3
"""MagicPanel 自建节点管理 CLI（在容器内执行，由 scripts/node_admin.sh 注入）。

为什么单独做这个工具：
- 本地节点的写库必须同时维护 `node_catalog` 与策略组成员投影，直接 UPDATE
  会漏掉别名与成员解析，构建时才会暴露；
- 每次新增/改节点还要导快照、建构建、发测试/生产、核对产物，手工步骤多。

本文件只依赖面板已有服务与本文件内的纯解析函数，因此：
- 不随镜像发布也能用（脚本从 stdin 注入容器执行）；
- `add/update/delete/test/list` 全部复用面板 router/service 的事务与校验；
- 支持 `--dry-run`，不产生任何写入。

典型调用（外层由 node_admin.sh 处理 SSH 与快照）：

    node_admin.sh add "vless://uuid@1.2.3.4:443?security=reality&sni=...&pbk=...&sid=..."
    node_admin.sh add --link ./node.yaml --region US --no-publish
    node_admin.sh update "vless://..."          # 按 server:port 匹配已有节点
    node_admin.sh delete --name "🇺🇸 美国自建 05" --force
    node_admin.sh list --region US
    node_admin.sh test --name "🇺🇸 美国自建 05"
    node_admin.sh publish --note "手工补发"

约定（与 AGENTS.md 一致）：
- 本地节点命名 `🇺🇸 美国自建 NN`，类型默认「机房」，产物标识为 `名称 (机房)`；
- 新增节点默认追加到对应地区的自建 fallback 组末尾，不改既有优先级；
- 快照不导出 `local_nodes`（凭据），由外层脚本在改动前后各导一份。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# 地区 → (旗帜, 名称前缀, 默认策略组)
REGIONS = {
    "US": ("🇺🇸", "美国自建", "🇺🇸 US自建"),
    "JP": ("🇯🇵", "日本自建", "🇯🇵 JP自建"),
    "SG": ("🇸🇬", "新加坡自建", "🇸🇬 SG自建"),
    "HK": ("🇭🇰", "香港自建", "🇭🇰香港"),
    "TW": ("🇹🇼", "台湾自建", "🇹🇼台湾"),
    "KR": ("🇰🇷", "韩国自建", "🇰🇷韩国"),
    "GB": ("🇬🇧", "英国自建", "🇬🇧英国"),
    "DE": ("🇩🇪", "德国自建", "🇩🇪德国"),
}
PROTOCOLS = {"vless", "hysteria2", "hy2", "trojan", "ss"}
DEFAULT_NODE_TYPE = "机房"
DEFAULT_OPERATOR = os.environ.get("MAGICPANEL_NODE_OPERATOR", "agent")
position_given = False


# ---------------------------------------------------------------------------
# 解析：vless:// / hysteria2:// / trojan:// / ss:// / Clash YAML
# ---------------------------------------------------------------------------

def _one(query: dict, key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def _truthy(value) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


def _mbps(value) -> int:
    if value in (None, ""):
        return 0
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else 0


def _split_hostport(value: str) -> tuple[str, int]:
    if value.startswith("["):  # [ipv6]:port
        host, _, rest = value.partition("]")
        port = rest.lstrip(":")
        return host.lstrip("["), int(port or 443)
    host, _, port = value.rpartition(":")
    if not host:
        return value, 443
    return host, int(port or 443)


def _network_params(params: dict, query: dict) -> None:
    network = params.get("network") or "tcp"
    if network == "ws":
        params["ws_path"] = _one(query, "path", "/") or "/"
        params["ws_host"] = _one(query, "host")
    elif network == "grpc":
        params["grpc_service_name"] = _one(query, "serviceName")


def parse_vless(url: str) -> dict:
    u = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(u.query)
    if not u.hostname:
        raise ValueError("VLESS 链接缺少服务器地址")
    security = _one(q, "security").lower()
    params = {
        "uuid": urllib.parse.unquote(u.username or ""),
        "flow": _one(q, "flow"),
        "tls": security in ("tls", "reality", "xtls"),
        "servername": _one(q, "sni") or _one(q, "host"),
        "skip_cert_verify": _truthy(_one(q, "allowInsecure")),
        "network": _one(q, "type", "tcp") or "tcp",
        "reality_public_key": _one(q, "pbk"),
        "reality_short_id": _one(q, "sid"),
        "reality_support_x25519mlkem768": False,
        "udp": True,
    }
    _network_params(params, q)
    return {"protocol": "vless", "server": u.hostname,
            "port": int(u.port or 443), "params": params}


def parse_hysteria2(url: str) -> dict:
    u = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(u.query)
    if not u.hostname:
        raise ValueError("Hysteria2 链接缺少服务器地址")
    password = urllib.parse.unquote(u.username or "")
    if not password and u.password:
        password = urllib.parse.unquote(u.password)
    params = {
        "password": password,
        "sni": _one(q, "sni") or _one(q, "peer"),
        "skip_cert_verify": _truthy(_one(q, "insecure")),
        "obfs": _one(q, "obfs"),
        "obfs_password": _one(q, "obfs-password"),
        "up": _mbps(_one(q, "upmbps")),
        "down": _mbps(_one(q, "downmbps")),
        "udp": True,
    }
    return {"protocol": "hysteria2", "server": u.hostname,
            "port": int(u.port or 443), "params": params}


def parse_trojan(url: str) -> dict:
    u = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(u.query)
    if not u.hostname:
        raise ValueError("Trojan 链接缺少服务器地址")
    params = {
        "password": urllib.parse.unquote(u.username or ""),
        "sni": _one(q, "sni") or _one(q, "peer"),
        "skip_cert_verify": _truthy(_one(q, "allowInsecure")),
        "network": _one(q, "type", "tcp") or "tcp",
        "udp": True,
    }
    _network_params(params, q)
    return {"protocol": "trojan", "server": u.hostname,
            "port": int(u.port or 443), "params": params}


def _b64decode(value: str) -> str:
    value = value.strip()
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode()).decode()


def parse_ss(url: str) -> dict:
    body = url.split("://", 1)[1]
    body = body.split("#", 1)[0]
    query = ""
    if "?" in body:
        body, query = body.split("?", 1)
    q = urllib.parse.parse_qs(query)
    if "@" in body:
        userinfo, hostport = body.rsplit("@", 1)
        if ":" in userinfo:
            method, password = userinfo.split(":", 1)
        else:
            method, password = _b64decode(userinfo).split(":", 1)
    else:
        decoded = _b64decode(body)
        userinfo, hostport = decoded.rsplit("@", 1)
        method, password = userinfo.split(":", 1)
    host, port = _split_hostport(hostport)
    params = {
        "cipher": method,
        "password": urllib.parse.unquote(password),
        "udp": True,
    }
    return {"protocol": "ss", "server": host, "port": port, "params": params}


def from_clash_proxy(proxy: dict) -> dict:
    """把一条 Clash/Mihomo proxy 映射成面板的协议参数。"""
    kind = (proxy.get("type") or "").lower()
    server = proxy.get("server")
    port = proxy.get("port")
    if not server or not port:
        raise ValueError("Clash 节点缺少 server / port")
    port = int(port)
    common = {
        "network": proxy.get("network") or "tcp",
    }
    if kind == "vless":
        ro = proxy.get("reality-opts") or {}
        params = {
            "uuid": proxy.get("uuid", ""),
            "flow": proxy.get("flow", ""),
            "tls": bool(proxy.get("tls", True)),
            "servername": proxy.get("servername") or proxy.get("sni") or "",
            "skip_cert_verify": bool(proxy.get("skip-cert-verify", False)),
            "network": common["network"],
            "reality_public_key": ro.get("public-key", ""),
            "reality_short_id": ro.get("short-id", ""),
            "reality_support_x25519mlkem768": bool(ro.get("support-x25519mlkem768", False)),
            "udp": bool(proxy.get("udp", True)),
        }
        ws = proxy.get("ws-opts") or {}
        if ws:
            params["ws_path"] = ws.get("path") or "/"
            params["ws_host"] = (ws.get("headers") or {}).get("Host", "")
        grpc = proxy.get("grpc-opts") or {}
        if grpc:
            params["grpc_service_name"] = grpc.get("grpc-service-name", "")
        return {"protocol": "vless", "server": server, "port": port, "params": params}
    if kind in ("hysteria2", "hy2"):
        params = {
            "password": proxy.get("password") or proxy.get("auth") or "",
            "sni": proxy.get("sni") or "",
            "skip_cert_verify": bool(proxy.get("skip-cert-verify", False)),
            "obfs": proxy.get("obfs") or "",
            "obfs_password": proxy.get("obfs-password") or "",
            "up": _mbps(proxy.get("up")),
            "down": _mbps(proxy.get("down")),
            "udp": True,
        }
        return {"protocol": "hysteria2", "server": server, "port": port, "params": params}
    if kind == "trojan":
        params = {
            "password": proxy.get("password", ""),
            "sni": proxy.get("sni", ""),
            "skip_cert_verify": bool(proxy.get("skip-cert-verify", False)),
            "network": common["network"],
            "udp": bool(proxy.get("udp", True)),
        }
        ws = proxy.get("ws-opts") or {}
        if ws:
            params["ws_path"] = ws.get("path") or "/"
            params["ws_host"] = (ws.get("headers") or {}).get("Host", "")
        return {"protocol": "trojan", "server": server, "port": port, "params": params}
    if kind == "ss":
        params = {
            "cipher": proxy.get("cipher", ""),
            "password": proxy.get("password", ""),
            "udp": bool(proxy.get("udp", True)),
        }
        return {"protocol": "ss", "server": server, "port": port, "params": params}
    raise ValueError(f"暂不支持的 Clash 协议：{kind or '未知'}")


def _yaml_block(text: str, index: int) -> str:
    """从整段部署输出里截出 proxies: 块，遇到顶层新键或分隔线即停止。"""
    lines = text[index:].splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if line.strip() and not line[0].isspace() and not line.startswith("-"):
            break
        block.append(line)
    return "\n".join(block)


def parse_clash(text: str) -> dict:
    try:
        import yaml
    except ImportError:
        raise ValueError("缺少 PyYAML，无法解析 Clash 片段")
    index = text.find("proxies:")
    if index < 0:
        raise ValueError("没有找到 proxies: 段落")
    data = yaml.safe_load(_yaml_block(text, index))
    if not isinstance(data, dict):
        raise ValueError("Clash 片段不是键值映射")
    proxies = data.get("proxies") or []
    if not proxies:
        raise ValueError("proxies 为空")
    return from_clash_proxy(proxies[0])


def parse_source(text: str) -> dict:
    """从链接、Clash YAML 或整段部署输出中解析一个节点。"""
    raw = (text or "").replace("&amp;", "&").strip()
    if not raw:
        raise ValueError("没有输入内容")
    match = re.search(r"(?:vless|hysteria2|hy2|trojan|ss)://[^\s\"'<>]+", raw)
    if match:
        url = match.group(0).rstrip(".,)")
        scheme = url.split("://", 1)[0].lower()
        if scheme == "vless":
            return parse_vless(url)
        if scheme in ("hysteria2", "hy2"):
            return parse_hysteria2(url)
        if scheme == "trojan":
            return parse_trojan(url)
        if scheme == "ss":
            return parse_ss(url)
    return parse_clash(raw)


# ---------------------------------------------------------------------------
# 命名与地区
# ---------------------------------------------------------------------------

def region_prefix(region: str) -> str:
    flag, label, _ = REGIONS[region]
    return f"{flag} {label}"


def next_name(existing_names, prefix: str) -> str:
    pattern = re.compile(re.escape(prefix) + r"\s+(\d{2})$")
    numbers = [int(m.group(1)) for name in existing_names if (m := pattern.match(name or ""))]
    return f"{prefix} {max(numbers, default=0) + 1:02d}"


def detect_region(server: str, explicit: str | None) -> str:
    if explicit:
        code = explicit.upper()
        if code not in REGIONS:
            raise ValueError(f"不支持的地区 {code}，可选：{'、'.join(REGIONS)}")
        return code
    ip = server
    try:
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", server):
            ip = socket.gethostbyname(server)
        with urllib.request.urlopen(
                f"http://ip-api.com/json/{ip}?fields=status,countryCode", timeout=6) as resp:
            data = json.load(resp)
        code = (data or {}).get("countryCode")
        if (data or {}).get("status") == "success" and code in REGIONS:
            return code
    except Exception:
        pass
    raise ValueError("无法自动判断地区，请用 --region US/JP/SG 指定")


# ---------------------------------------------------------------------------
# 面板数据操作（延迟导入 app，保证纯解析函数可在容器外测试）
# ---------------------------------------------------------------------------

def _lookup_node(conn, name=None, server=None, port=None):
    from app import db
    if name:
        row = db.one(conn, "SELECT * FROM local_nodes WHERE name=?", (name,))
        if not row:
            raise ValueError(f"本地节点不存在：{name}")
        return row
    rows = db.all_(conn, "SELECT * FROM local_nodes WHERE server=? AND port=? ORDER BY id",
                   (server, int(port)))
    if not rows:
        raise ValueError(f"本地节点不存在：{server}:{port}")
    if len(rows) > 1:
        names = "、".join(r["name"] for r in rows)
        raise ValueError(f"同一地址端口有多个节点：{names}，请用 --name 指定")
    return rows[0]


def _node_payload(row):
    from app import security
    return json.loads(security.decrypt_text(row["params_enc"]) or "{}") if row["params_enc"] else {}


def _extra_payload(row):
    from app import security
    return security.decrypt_text(row["extra_yaml_enc"]) if row["extra_yaml_enc"] else ""


def _create(parsed, name, node_type, extra, operator):
    from app.routers.local_nodes import LocalNodeBody, create_node
    body = LocalNodeBody(
        name=name, node_type=node_type, protocol=parsed["protocol"],
        server=parsed["server"], port=int(parsed["port"]), params=parsed["params"],
        extra_yaml=extra, enabled=True)
    return create_node(body, user={"username": operator})


def _update(node_id, parsed, name, node_type, params, extra, enabled, operator):
    from app.routers.local_nodes import LocalNodeBody, update_node
    body = LocalNodeBody(
        name=name, node_type=node_type, protocol=parsed["protocol"],
        server=parsed["server"], port=int(parsed["port"]), params=params,
        extra_yaml=extra, enabled=enabled)
    return update_node(node_id, body, user={"username": operator})


def _delete(node_id, force, operator):
    from app.routers.local_nodes import delete_node
    return delete_node(node_id, force=force, user={"username": operator})


def _group_row(conn, name):
    from app import db
    row = db.one(conn, "SELECT * FROM proxy_groups WHERE variant_id=0 AND name=?", (name,))
    if not row:
        groups = [r["name"] for r in db.all_(
            conn, "SELECT name FROM proxy_groups WHERE variant_id=0 ORDER BY sort")]
        raise ValueError(f"策略组不存在：{name}。可选：{'、'.join(groups)}")
    return row


def _members(conn, group):
    from app.services import node_refs
    groups, nodes = node_refs.context(conn)
    if group["members_format"] == "typed-v2":
        return json.loads(group["members_v2"] or "[]"), groups, nodes
    members = node_refs.legacy_refs(
        json.loads(group["proxies"] or "[]"), variant_id=group["variant_id"],
        groups=groups, nodes=nodes,
        local_ids=json.loads(group["local_nodes"] or "[]"),
        local_first=bool(group["local_first"]))
    return members, groups, nodes


def _insert_member(conn, group, new_ref, new_name, position):
    from app.services import node_refs
    members, groups, nodes = _members(conn, group)
    if new_ref in members:
        if not position:
            return members
        members = [m for m in members if m != new_ref]
    names = node_refs.resolve_refs(
        members, variant_id=group["variant_id"],
        groups=[dict(g) for g in groups], nodes=[dict(n) for n in nodes])
    if not position or position == "end":
        members.append(new_ref)
    elif position == "start":
        members.insert(0, new_ref)
    else:
        offset = 1 if position.startswith("after:") else 0
        target = position.split(":", 1)[1] if ":" in position else ""
        if not target:
            raise ValueError("--position 需要 end / start / after:节点名 / before:节点名")
        index = next((i for i, n in enumerate(names)
                      if n == target or n.split(" (")[0] == target), None)
        if index is None:
            raise ValueError(f"找不到定位节点：{target}。当前成员：{'、'.join(names)}")
        members.insert(index + offset, new_ref)
    return members


def _save_group(conn, group, members, operator):
    from app.routers.policy import GroupBody, update_group
    body = GroupBody(
        name=group["name"], variant_id=group["variant_id"], type=group["type"],
        hidden=bool(group["hidden"]), filter=group["filter"],
        use_sources=json.loads(group["use_sources"] or "[]"),
        local_nodes=json.loads(group["local_nodes"] or "[]"),
        members_v2=members, url=group["url"], interval=group["interval"],
        timeout=group["timeout"], tolerance=group["tolerance"],
        lazy=bool(group["lazy"]), strategy=group["strategy"] or "",
        targets=json.loads(group["targets"] or '["*"]'),
        devices=json.loads(group["devices"] or '["*"]'),
        local_first=bool(group["local_first"]))
    update_group(group["id"], body, user={"username": operator})


def _node_uid(conn, node_id):
    from app import db
    row = db.one(conn, "SELECT node_uid FROM node_catalog WHERE local_node_id=?", (node_id,))
    return row["node_uid"] if row else None


# ---------------------------------------------------------------------------
# 构建 / 发布 / 产物核对
# ---------------------------------------------------------------------------

def _publish(operator, note, node_name):
    from app import db
    from app.routers.builds import (PublishBody, create_build, publish_to_prod,
                                    publish_to_test)
    build_id, verify = create_build(operator, note=note)
    with db.connect() as conn:
        row = db.one(conn, "SELECT results FROM builds WHERE id=?", (build_id,))
        results = json.loads(row["results"] or "{}")
    bad = [name for name, item in results.items() if not item.get("ok")]
    if verify not in ("success", "warning") or bad:
        return {"build": build_id, "ok": False, "verify": verify, "bad": bad}
    tested = publish_to_test(build_id, PublishBody(reason=note),
                             user={"username": operator})
    production = publish_to_prod(build_id, PublishBody(reason=note),
                                 user={"username": operator})
    feed = _verify_feed(node_name) if node_name else []
    return {"build": build_id, "ok": True, "test": tested,
            "prod": production, "feed": feed}


def _verify_feed(node_name):
    from app import db, security
    with db.connect() as conn:
        devices = db.all_(
            conn, "SELECT d.name, d.token_enc, t.engine AS engine FROM devices d "
                  "LEFT JOIN targets t ON t.id=d.target_id "
                  "WHERE d.env='production' ORDER BY d.id")
    picked, engines = [], set()
    for device in devices:
        engine = device["engine"] or ""
        if engine in engines:
            continue
        engines.add(engine)
        picked.append(device)
        if len(picked) >= 2:
            break
    result = []
    for device in picked:
        try:
            token = security.decrypt_text(device["token_enc"])
            url = f"http://127.0.0.1:8000/feed/{token}/config.yaml"
            text = urllib.request.urlopen(url, timeout=20).read().decode()
            result.append({"device": device["name"], "engine": device["engine"],
                           "ok": node_name in text})
        except Exception as exc:  # 产物核对失败不推翻已完成的发布，但要显式报告
            result.append({"device": device["name"], "engine": device["engine"],
                           "ok": False, "error": str(exc)})
    return result


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------

def _read_source(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    if os.path.isfile(value):
        with open(value, encoding="utf-8") as handle:
            return handle.read()
    return value


def _names(conn):
    from app import db
    return [r["name"] for r in db.all_(conn, "SELECT name FROM local_nodes ORDER BY sort, id")]


def cmd_list(args):
    from app import db
    with db.connect() as conn:
        rows = db.all_(conn, "SELECT * FROM local_nodes ORDER BY sort, id")
        group_rows = db.all_(conn, "SELECT name, proxies FROM proxy_groups ORDER BY sort")
    items = []
    for row in rows:
        if args.region:
            prefix = region_prefix(args.region.upper())
            if not row["name"].startswith(prefix):
                continue
        emit = f"{row['name']} ({row['node_type']})" if row["node_type"] else row["name"]
        groups = [g["name"] for g in group_rows
                  if emit in json.loads(g["proxies"] or "[]")]
        items.append({"id": row["id"], "name": row["name"], "node_type": row["node_type"],
                      "protocol": row["protocol"], "server": row["server"],
                      "port": row["port"], "enabled": bool(row["enabled"]),
                      "test_status": row["test_status"], "test_delay": row["test_delay"],
                      "groups": groups})
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    for item in items:
        state = "启用" if item["enabled"] else "停用"
        delay = f"{item['test_delay']}ms" if item["test_delay"] else "-"
        print(f"#{item['id']:>3} {item['name']}  [{item['node_type']}]  "
              f"{item['protocol']} {item['server']}:{item['port']}  "
              f"{state}  测速 {item['test_status'] or '-'}/{delay}  "
              f"组 {'、'.join(item['groups']) or '-'}")
    return 0


def cmd_test(args):
    from app import db
    from app.routers.local_nodes import test_node
    with db.connect() as conn:
        row = _lookup_node(conn, name=args.name, server=args.server, port=args.port)
    result = test_node(row["id"], user={"username": args.operator})
    print(json.dumps(result, ensure_ascii=False) if args.json else
          f"{row['name']} 测速：{'ok' if result.get('ok') else 'failed'}，"
          f"延迟 {result.get('delay')}ms")
    return 0 if result.get("ok") else 1


def cmd_add(args):
    from app import db
    parsed = parse_source(_read_source(args.link))
    region = detect_region(parsed["server"], args.region)
    prefix = region_prefix(region)
    with db.connect() as conn:
        names = _names(conn)
        existing = db.all_(
            conn, "SELECT * FROM local_nodes WHERE server=? AND port=? ORDER BY id",
            (parsed["server"], int(parsed["port"])))
    if len(existing) > 1:
        raise SystemExit("同一地址端口存在多个节点，请用 update --name 指定")
    existing = existing[0] if existing else None

    if existing:
        node = existing
        name = args.name or node["name"]
        node_type = args.type or node["node_type"] or DEFAULT_NODE_TYPE
        merged = {**_node_payload(node), **parsed["params"]}
        if args.mlkem:
            merged["reality_support_x25519mlkem768"] = True
        extra = args.extra_yaml if args.extra_yaml is not None else _extra_payload(node)
        action = "update"
        print(f"[upsert] 检测到同地址端口节点「{node['name']}」，按更新处理")
    else:
        name = args.name or next_name(names, prefix)
        node_type = args.type or DEFAULT_NODE_TYPE
        merged = dict(parsed["params"])
        if args.mlkem:
            merged["reality_support_x25519mlkem768"] = True
        extra = args.extra_yaml or ""
        action = "add"

    if args.name and existing and args.name != existing["name"]:
        action = "rename-update"

    group_name = args.group
    if group_name == "none":
        group_name = ""
    elif not group_name:
        group_name = REGIONS[region][2] if action == "add" or args.group else ""

    if args.dry_run:
        print(json.dumps({
            "action": action, "name": name, "node_type": node_type,
            "protocol": parsed["protocol"], "server": parsed["server"],
            "port": parsed["port"], "region": region,
            "group": group_name or None, "position": args.position,
            "publish": not args.no_publish,
        }, ensure_ascii=False, indent=1))
        return 0

    if existing:
        row = _update(existing["id"], parsed, name, node_type, merged, extra,
                      bool(existing["enabled"]), args.operator)
    else:
        row = _create(parsed, name, node_type, extra, args.operator)
    print(f"[{action}] #{row['id']} {row['name']} ({node_type}) "
          f"{parsed['protocol']} {parsed['server']}:{parsed['port']}")

    if group_name:
        with db.connect() as conn:
            group = _group_row(conn, group_name)
            uid = _node_uid(conn, row["id"])
            if not uid:
                raise SystemExit("节点目录未同步，无法加入策略组")
            ref = {"kind": "node", "ref": uid}
            position = args.position if position_given else None
            members = _insert_member(conn, group, ref, f"{name} ({node_type})", position)
            _save_group(conn, group, members, args.operator)
            where = args.position if position_given else ("末尾" if not existing else "保持现有位置")
            print(f"[group] {group_name}：{name} 已加入（{where}）")

    if args.no_publish:
        print("[publish] 已跳过（--no-publish）")
        return 0
    note = args.note or f"node-admin {action}: {row['name']}"
    result = _publish(args.operator, note, f"{row['name']} ({node_type})")
    if not result.get("ok"):
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 1
    print(f"[publish] build #{result['build']} 已发布生产；产物核对：")
    for item in result.get("feed", []):
        print(f"  - {item['device']} ({item['engine']}): "
              f"{'ok' if item['ok'] else 'FAILED'}")
    return 0


def cmd_update(args):
    if not args.link and not any((args.name, args.server, args.port, args.rename)):
        raise SystemExit("update 需要 --link，或 --name / --server+--port 指定节点")
    from app import db
    parsed = parse_source(_read_source(args.link)) if args.link else None
    lookup_server = args.server or (parsed["server"] if parsed else None)
    lookup_port = args.port or (parsed["port"] if parsed else None)
    with db.connect() as conn:
        node = _lookup_node(conn, name=args.name, server=lookup_server, port=lookup_port)
    name = args.rename or (args.name if args.name else node["name"])
    protocol = parsed["protocol"] if parsed else node["protocol"]
    server = parsed["server"] if parsed else node["server"]
    port = int(parsed["port"]) if parsed else int(node["port"])
    node_type = args.type or node["node_type"] or DEFAULT_NODE_TYPE
    merged = {**_node_payload(node), **(parsed["params"] if parsed else {})}
    if args.mlkem:
        merged["reality_support_x25519mlkem768"] = True
    extra = args.extra_yaml if args.extra_yaml is not None else _extra_payload(node)
    if args.dry_run:
        print(json.dumps({"action": "update", "id": node["id"], "name": name,
                          "node_type": node_type, "protocol": protocol,
                          "server": server, "port": port}, ensure_ascii=False, indent=1))
        return 0
    row = _update(node["id"], {"protocol": protocol, "server": server, "port": port,
                               "params": merged}, name, node_type, merged, extra,
                  bool(node["enabled"]), args.operator)
    print(f"[update] #{row['id']} {row['name']} {protocol} {server}:{port}")
    if args.group:
        with db.connect() as conn:
            group = _group_row(conn, args.group)
            uid = _node_uid(conn, row["id"])
            members = _insert_member(conn, group, {"kind": "node", "ref": uid},
                                     f"{name} ({node_type})",
                                     args.position if position_given else None)
            _save_group(conn, group, members, args.operator)
    if args.no_publish:
        print("[publish] 已跳过（--no-publish）")
        return 0
    note = args.note or f"node-admin update: {row['name']}"
    result = _publish(args.operator, note, f"{row['name']} ({node_type})")
    if not result.get("ok"):
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 1
    print(f"[publish] build #{result['build']} 已发布生产")
    return 0


def cmd_delete(args):
    from app import db
    from fastapi import HTTPException
    with db.connect() as conn:
        node = _lookup_node(conn, name=args.name, server=args.server, port=args.port)
        emit = f"{node['name']} ({node['node_type']})" if node["node_type"] else node["name"]
    if args.dry_run:
        print(json.dumps({"action": "delete", "id": node["id"], "name": node["name"],
                          "emit": emit, "force": args.force}, ensure_ascii=False, indent=1))
        return 0
    try:
        result = _delete(node["id"], args.force, args.operator)
    except HTTPException as exc:
        print(f"[delete] 拒绝：{exc.detail}")
        return 1
    print(f"[delete] {emit} 已删除；解绑组：{'、'.join(result.get('detached_groups', [])) or '-'}")
    if args.no_publish:
        print("[publish] 已跳过（--no-publish）")
        return 0
    result = _publish(args.operator, args.note or f"node-admin delete: {node['name']}", None)
    if not result.get("ok"):
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 1
    print(f"[publish] build #{result['build']} 已发布生产")
    return 0


def cmd_publish(args):
    result = _publish(args.operator, args.note or "node-admin publish", None)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("ok") else 1


def build_parser():
    parser = argparse.ArgumentParser(
        description="MagicPanel 自建节点管理（在容器内执行；外层用 scripts/node_admin.sh）")
    sub = parser.add_subparsers(dest="action", required=True)

    def common(p):
        p.add_argument("--operator", default=DEFAULT_OPERATOR)
        p.add_argument("--json", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--note", default="")

    p_add = sub.add_parser("add", help="新增节点；同 server:port 已存在时自动更新")
    p_add.add_argument("link", nargs="?", help="vless://... / Clash YAML 文件 / - 读 stdin")
    p_add.add_argument("--link", dest="link_opt", help="同位置参数")
    p_add.add_argument("--name")
    p_add.add_argument("--region", choices=sorted(REGIONS))
    p_add.add_argument("--group", help="目标策略组；none 表示不加组")
    p_add.add_argument("--type", default="", help=f"节点类型，默认 {DEFAULT_NODE_TYPE}")
    p_add.add_argument("--position", default="end",
                       help="end / start / after:节点名 / before:节点名")
    p_add.add_argument("--extra-yaml", default=None)
    p_add.add_argument("--mlkem", action="store_true")
    p_add.add_argument("--no-publish", action="store_true")
    common(p_add)

    p_update = sub.add_parser("update", help="更新节点（按 server:port 或 --name 匹配）")
    p_update.add_argument("link", nargs="?")
    p_update.add_argument("--link", dest="link_opt")
    p_update.add_argument("--name")
    p_update.add_argument("--server")
    p_update.add_argument("--port", type=int)
    p_update.add_argument("--rename")
    p_update.add_argument("--group")
    p_update.add_argument("--type", default="")
    p_update.add_argument("--position", default="end")
    p_update.add_argument("--extra-yaml", default=None)
    p_update.add_argument("--mlkem", action="store_true")
    p_update.add_argument("--no-publish", action="store_true")
    common(p_update)

    p_delete = sub.add_parser("delete", help="删除节点并从策略组解绑")
    p_delete.add_argument("--name")
    p_delete.add_argument("--server")
    p_delete.add_argument("--port", type=int)
    p_delete.add_argument("--force", action="store_true")
    p_delete.add_argument("--no-publish", action="store_true")
    common(p_delete)

    p_list = sub.add_parser("list", help="列出本地节点")
    p_list.add_argument("--region", choices=sorted(REGIONS))
    p_list.add_argument("--json", action="store_true")

    p_test = sub.add_parser("test", help="用面板同款 Mihomo 核心测速")
    p_test.add_argument("--name")
    p_test.add_argument("--server")
    p_test.add_argument("--port", type=int)
    p_test.add_argument("--json", action="store_true")
    p_test.add_argument("--operator", default=DEFAULT_OPERATOR)

    p_pub = sub.add_parser("publish", help="只跑一次构建并发布生产")
    p_pub.add_argument("--operator", default=DEFAULT_OPERATOR)
    p_pub.add_argument("--note", default="")

    return parser


def container_main(argv=None):
    """容器内入口：所有真实写库与发布都在这里执行。"""
    global position_given
    if argv is None:
        payload = os.environ.get("MAGICPANEL_NODE_ARGV_B64")
        argv = (json.loads(base64.b64decode(payload)) if payload else sys.argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    position_given = any(a == "--position" or a.startswith("--position=") for a in argv)
    if getattr(args, "link_opt", None):
        args.link = args.link_opt
    if not hasattr(args, "operator"):
        args.operator = DEFAULT_OPERATOR
    try:
        if args.action == "add":
            if not getattr(args, "link", None):
                raise SystemExit("add 需要节点链接或 Clash YAML（位置参数或 --link）")
            return cmd_add(args)
        if args.action == "update":
            return cmd_update(args)
        if args.action == "delete":
            if not any((args.name, args.server)):
                raise SystemExit("delete 需要 --name 或 --server+--port")
            return cmd_delete(args)
        if args.action == "list":
            return cmd_list(args)
        if args.action == "test":
            if not any((args.name, args.server)):
                raise SystemExit("test 需要 --name 或 --server+--port")
            return cmd_test(args)
        if args.action == "publish":
            return cmd_publish(args)
        raise SystemExit(f"未知命令：{args.action}")
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------
# 宿主模式：SSH 调 NAS、前后快照、交互式中文菜单
# ---------------------------------------------------------------------------

NAS = os.environ.get("MAGICPANEL_NAS", "archon@10.0.1.2")
CONTAINER = os.environ.get("MAGICPANEL_CONTAINER", "magicpanel")
SNAPSHOT_DIR = os.environ.get("MAGICPANEL_SNAPSHOT_DIR", "/opt/magicpanel/policy/snapshots")
OPERATOR = os.environ.get("MAGICPANEL_NODE_OPERATOR", "agent")
LOCAL_MODE = os.environ.get("MAGICPANEL_LOCAL", "0") == "1"

HOST_USAGE = """\
MagicPanel 自建节点管理（内网）

  mpnode                         进入中文交互菜单
  mpnode add "vless://..."       直接新增/更新节点并发布
  mpnode update "vless://..."    按链接里的 server:port 匹配并更新
  mpnode delete --name "..." --force
  mpnode list [--region US]
  mpnode test --name "..."
  mpnode publish

可选参数：--dry-run 只看计划；--no-publish 只改数据；--region US/JP/SG；
--name 指定名称；--position end/start/after:节点名；--group 指定策略组。

默认通过 SSH 连接 archon@10.0.1.2 上的 magicpanel 容器；可用环境变量
MAGICPANEL_NAS、MAGICPANEL_CONTAINER、MAGICPANEL_LOCAL=1 覆盖。
"""


def _run_container(args, capture=False):
    script = Path(__file__).read_text(encoding="utf-8")
    payload = base64.b64encode(
        json.dumps(args, ensure_ascii=False).encode()).decode()
    if LOCAL_MODE:
        cmd = ["docker", "exec", "-i",
               "-e", "MAGICPANEL_NODE_INSIDE=1",
               "-e", f"MAGICPANEL_NODE_ARGV_B64={payload}",
               "-e", f"MAGICPANEL_NODE_OPERATOR={OPERATOR}",
               "-w", "/app", CONTAINER, "python", "-"]
    else:
        remote = (f"docker exec -i -e MAGICPANEL_NODE_INSIDE=1 "
                  f"-e MAGICPANEL_NODE_ARGV_B64='{payload}' "
                  f"-e MAGICPANEL_NODE_OPERATOR='{OPERATOR}' "
                  f"-w /app {CONTAINER} python -")
        cmd = ["ssh", NAS, remote]
    return subprocess.run(cmd, input=script, text=True, capture_output=capture)


def _snapshot(tag):
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    name = f"mpnode-{tag}-{stamp}.json"
    remote = (f"cd /opt/magicpanel && python3 scripts/export_policy.py "
              f"--db data/magicpanel.db --out {SNAPSHOT_DIR}/{name}")
    cmd = ["sh", "-c", remote] if LOCAL_MODE else ["ssh", NAS, remote]
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        raise SystemExit(f"快照失败：{(result.stderr or result.stdout).strip()}")
    print(f"[快照] {name}")
    return name


def run_action(args):
    action = args[0] if args and not args[0].startswith("-") else ""
    mutating = action in ("add", "update", "delete") and "--dry-run" not in args
    before = after = None
    if mutating:
        before = _snapshot(f"{action}-before")
    result = _run_container(args)
    if mutating:
        try:
            after = _snapshot(f"{action}-after")
        except SystemExit as exc:
            print(f"[警告] 改后快照失败：{exc}", file=sys.stderr)
    if before and after:
        print(f"[快照] {SNAPSHOT_DIR}/{{{before},{after}}}")
    return result.returncode


def _json_call(args):
    result = _run_container(args, capture=True)
    if result.returncode != 0:
        print((result.stdout or "").rstrip())
        print((result.stderr or "").rstrip(), file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except Exception:
        print((result.stdout or "").rstrip())
        return None


def _print_nodes(nodes):
    for index, node in enumerate(nodes, 1):
        state = "启用" if node.get("enabled") else "停用"
        print(f"{index:>2}) {node['name']}  [{node.get('node_type') or '-'}]  "
              f"{node.get('protocol')} {node.get('server')}:{node.get('port')}  {state}")


def _choose_node(nodes, title):
    if not nodes:
        print("没有可用节点。")
        return None
    print(title)
    _print_nodes(nodes)
    while True:
        raw = input("输入序号（回车取消）：").strip()
        if not raw:
            return None
        try:
            index = int(raw) - 1
        except ValueError:
            print("请输入数字。")
            continue
        if 0 <= index < len(nodes):
            return nodes[index]
        print("序号超出范围。")


def _prompt_multiline(title):
    print(title)
    print("（粘贴完成后按两次回车；只粘一行时直接回车即可）")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "" and lines:
            break
        if line:
            lines.append(line)
    return "\n".join(lines)


def _confirm(prompt, default=True):
    suffix = " [Y/n] " if default else " [y/N] "
    raw = input(prompt + suffix).strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "是", "1")


def interactive_add():
    source = _prompt_multiline("请粘贴节点链接或 Clash YAML：")
    if not source:
        return
    plan = _json_call(["add", source, "--dry-run"])
    if plan is None:
        region = input("自动识别地区失败，请输入地区代码（US/JP/SG/HK/TW/KR/GB/DE）：").strip().upper()
        if not region:
            return
        plan = _json_call(["add", source, "--region", region, "--dry-run"])
        if plan is None:
            return
    print("\n将执行：")
    print(f"  名称：{plan['name']}（{plan['node_type']}）")
    print(f"  地址：{plan['protocol']} {plan['server']}:{plan['port']}")
    print(f"  地区：{plan['region']}    策略组：{plan.get('group') or '不加入'}")
    region = input(f"地区 [{plan['region']}]（回车保持）：").strip().upper() or plan["region"]
    name = input(f"名称 [{plan['name']}]（回车保持）：").strip()
    position = input("位置 end/start/after:节点名（回车末尾）：").strip()
    args = ["add", source, "--region", region]
    if name and name != plan["name"]:
        args += ["--name", name]
    if position:
        args += ["--position", position]
    if not _confirm("发布到生产？", True):
        args += ["--no-publish"]
    final = _json_call(args + ["--dry-run"])
    if final is None:
        return
    print(f"\n最终：{final['name']}  {final['protocol']} {final['server']}:{final['port']}"
          f"  → {final.get('group') or '不加入'}（{final.get('position')}）")
    if not _confirm("确认执行？", True):
        return
    run_action(args)


def interactive_update():
    nodes = _json_call(["list", "--json"]) or []
    node = _choose_node(nodes, "选择要更新的节点：")
    if not node:
        return
    source = _prompt_multiline(f"粘贴「{node['name']}」的新链接：")
    if not source:
        return
    args = ["update", source, "--name", node["name"]]
    rename = input(f"新名称 [{node['name']}]（回车不改）：").strip()
    if rename and rename != node["name"]:
        args += ["--rename", rename]
    if not _confirm("确认更新并发布？", True):
        return
    run_action(args)


def interactive_delete():
    nodes = _json_call(["list", "--json"]) or []
    node = _choose_node(nodes, "选择要删除的节点：")
    if not node:
        return
    print(f"将删除 {node['name']}，并从所有策略组解绑，然后发布生产。")
    if not _confirm("确认删除？", False):
        return
    run_action(["delete", "--name", node["name"], "--force"])


def interactive_test():
    nodes = _json_call(["list", "--json"]) or []
    node = _choose_node(nodes, "选择要测速的节点：")
    if not node:
        return
    run_action(["test", "--name", node["name"]])


def interactive_menu():
    print("MagicPanel 自建节点管理（内网）")
    while True:
        print("""
  1) 新增节点（粘贴链接或 Clash 配置）
  2) 更新节点（换 UUID / 密钥 / 端口）
  3) 删除节点
  4) 查看节点
  5) 测速
  6) 发布一次构建
  0) 退出
""")
        choice = input("请选择：").strip()
        try:
            if choice == "1":
                interactive_add()
            elif choice == "2":
                interactive_update()
            elif choice == "3":
                interactive_delete()
            elif choice == "4":
                run_action(["list"])
            elif choice == "5":
                interactive_test()
            elif choice == "6":
                if _confirm("创建构建并发布生产？", True):
                    run_action(["publish", "--note", "交互式补发"])
            elif choice in ("0", "q", "quit", "exit"):
                return 0
            else:
                print("请输入 0-6。")
        except KeyboardInterrupt:
            print("\n已取消。")
            return 0


def main(argv=None):
    if os.environ.get("MAGICPANEL_NODE_INSIDE") == "1":
        return container_main(argv)
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return interactive_menu()
    if argv[0] in ("-h", "--help"):
        print(HOST_USAGE)
        return 0
    try:
        return run_action(argv)
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
