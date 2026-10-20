"""本地单节点：协议字段定义、校验与 Clash/Mihomo 出站渲染。

节点以 `[单] 名称` 写入产物顶层 proxies；策略组通过 local_nodes 字段引用。
协议字段由服务端统一定义，前端据此动态渲染表单。
"""
import json
from copy import deepcopy

import yaml

MARK = "[单]"

SS_CIPHERS = [
    "aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305", "none",
]
VMESS_CIPHERS = ["auto", "aes-128-gcm", "chacha20-poly1305", "none"]
NETWORKS = ["tcp", "ws", "grpc"]


def _bandwidth_mbps(value) -> int:
    """带宽统一以 Mbps 整数保存；兼容 "1000 Mbps" 这类写法。"""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace("mbps", "").replace("m", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return 0


def _field(key, label, kind="text", **kwargs):
    data = {"key": key, "label": label, "type": kind}
    data.update(kwargs)
    return data


PROTOCOLS = {
    "ss": {
        "label": "Shadowsocks",
        "default_port": 8388,
        "fields": [
            _field("cipher", "加密方式", "select", required=True, default="aes-256-gcm",
                   options=[{"value": value, "label": value} for value in SS_CIPHERS]),
            _field("password", "密码", "password", required=True),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "ssr": {
        "label": "ShadowsocksR",
        "default_port": 8388,
        "fields": [
            _field("cipher", "加密方式", "select", required=True, default="aes-256-cfb",
                   options=[{"value": value, "label": value} for value in [
                       "aes-128-cfb", "aes-192-cfb", "aes-256-cfb",
                       "aes-128-ctr", "aes-192-ctr", "aes-256-ctr",
                       "chacha20-ietf", "xchacha20-ietf-poly1305", "none",
                   ]]),
            _field("password", "密码", "password", required=True),
            _field("protocol", "协议插件", "select", required=True, default="origin",
                   options=[{"value": value, "label": value} for value in [
                       "origin", "auth_sha1_v4", "auth_aes128_md5", "auth_aes128_sha1",
                   ]]),
            _field("protocol_param", "协议参数", "text", default=""),
            _field("obfs", "混淆", "select", required=True, default="plain",
                   options=[{"value": value, "label": value} for value in [
                       "plain", "http_simple", "http_post", "tls1.2_ticket_auth",
                   ]]),
            _field("obfs_param", "混淆参数", "text", default=""),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "vmess": {
        "label": "VMess",
        "default_port": 443,
        "fields": [
            _field("uuid", "UUID", "password", required=True),
            _field("alter_id", "Alter ID", "number", default=0, min=0, max=65535),
            _field("cipher", "加密方式", "select", default="auto",
                   options=[{"value": value, "label": value} for value in VMESS_CIPHERS]),
            _field("tls", "启用 TLS", "switch", default=True),
            _field("servername", "SNI / 证书域名", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
            _field("network", "传输方式", "select", default="tcp",
                   options=[{"value": value, "label": value} for value in NETWORKS]),
            _field("ws_path", "WS 路径", "text", default="/", show_if={"key": "network", "in": ["ws"]}),
            _field("ws_host", "WS Host", "text", default="", show_if={"key": "network", "in": ["ws"]}),
            _field("grpc_service_name", "gRPC Service", "text", default="",
                   show_if={"key": "network", "in": ["grpc"]}),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "vless": {
        "label": "VLESS",
        "default_port": 443,
        "fields": [
            _field("uuid", "UUID", "password", required=True),
            _field("flow", "Flow", "select", default="",
                   options=[{"value": "", "label": "无"}, {"value": "xtls-rprx-vision", "label": "xtls-rprx-vision"}]),
            _field("tls", "启用 TLS", "switch", default=True),
            _field("servername", "SNI / 证书域名", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
            _field("network", "传输方式", "select", default="tcp",
                   options=[{"value": value, "label": value} for value in NETWORKS]),
            _field("ws_path", "WS 路径", "text", default="/", show_if={"key": "network", "in": ["ws"]}),
            _field("ws_host", "WS Host", "text", default="", show_if={"key": "network", "in": ["ws"]}),
            _field("grpc_service_name", "gRPC Service", "text", default="",
                   show_if={"key": "network", "in": ["grpc"]}),
            _field("reality_public_key", "Reality 公钥", "text", default=""),
            _field("reality_short_id", "Reality Short ID", "text", default=""),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "trojan": {
        "label": "Trojan",
        "default_port": 443,
        "fields": [
            _field("password", "密码", "password", required=True),
            _field("sni", "SNI", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
            _field("network", "传输方式", "select", default="tcp",
                   options=[{"value": value, "label": value} for value in NETWORKS]),
            _field("ws_path", "WS 路径", "text", default="/", show_if={"key": "network", "in": ["ws"]}),
            _field("ws_host", "WS Host", "text", default="", show_if={"key": "network", "in": ["ws"]}),
            _field("grpc_service_name", "gRPC Service", "text", default="",
                   show_if={"key": "network", "in": ["grpc"]}),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "hysteria2": {
        "label": "Hysteria2",
        "default_port": 443,
        "fields": [
            _field("password", "密码", "password", required=True),
            _field("sni", "SNI", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
            _field("obfs", "混淆", "select", default="",
                   options=[{"value": "", "label": "无"}, {"value": "salamander", "label": "salamander"}]),
            _field("obfs_password", "混淆密码", "password", default="",
                   show_if={"key": "obfs", "in": ["salamander"]}),
            _field("up", "上行带宽 (Mbps)", "bandwidth", default=0),
            _field("down", "下行带宽 (Mbps)", "bandwidth", default=0),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "tuic": {
        "label": "TUIC",
        "default_port": 443,
        "fields": [
            _field("version", "TUIC 版本", "select", default="5",
                   options=[{"value": "5", "label": "v5"},
                            {"value": "4", "label": "v4"}]),
            _field("uuid", "UUID", "password", required=True),
            _field("password", "密码", "password", required=True),
            _field("sni", "SNI", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
            _field("congestion_controller", "拥塞控制", "select", default="bbr",
                   options=[{"value": value, "label": value} for value in ["bbr", "cubic", "new_reno"]]),
            _field("udp_relay_mode", "UDP 中继模式", "select", default="native",
                   options=[{"value": value, "label": value} for value in ["native", "quic"]]),
            _field("reduce_rtt", "Reduce RTT", "switch", default=False),
        ],
    },
    "http": {
        "label": "HTTP 代理",
        "default_port": 8080,
        "fields": [
            _field("username", "用户名", "text", default=""),
            _field("password", "密码", "password", default=""),
            _field("tls", "启用 TLS", "switch", default=False),
            _field("sni", "SNI", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
        ],
    },
    "socks5": {
        "label": "SOCKS5",
        "default_port": 1080,
        "fields": [
            _field("username", "用户名", "text", default=""),
            _field("password", "密码", "password", default=""),
            _field("tls", "启用 TLS", "switch", default=False),
            _field("sni", "SNI", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "snell": {
        "label": "Snell",
        "default_port": 443,
        "fields": [
            _field("psk", "PSK", "password", required=True),
            _field("version", "版本", "select", default="3",
                   options=[{"value": str(v), "label": f"v{v}"} for v in (1, 2, 3, 4, 5)]),
            _field("obfs", "混淆", "select", default="",
                   options=[{"value": "", "label": "无"}, {"value": "http", "label": "http"}]),
            _field("obfs_host", "混淆 Host", "text", default="",
                   show_if={"key": "obfs", "in": ["http"]}),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "anytls": {
        "label": "AnyTLS",
        "default_port": 443,
        "fields": [
            _field("password", "密码", "password", required=True),
            _field("sni", "SNI", "text", default=""),
            _field("skip_cert_verify", "跳过证书校验", "switch", default=False),
            _field("udp", "启用 UDP", "switch", default=True),
        ],
    },
    "custom": {
        "label": "自定义 / 其他协议",
        "default_port": 443,
        "fields": [
            _field("proxy_type", "Proxy type（如 mieru / juicity / wireguard）", "text",
                   required=True, placeholder="mieru"),
        ],
    },
}


def protocol_schema() -> list[dict]:
    result = []
    for value, spec in PROTOCOLS.items():
        result.append({
            "value": value,
            "label": spec["label"],
            "default_port": spec["default_port"],
            "fields": deepcopy(spec["fields"]),
        })
    return result


def marked_name(name: str) -> str:
    return f"{MARK} {name}"


def default_params(protocol: str) -> dict:
    spec = PROTOCOLS.get(protocol)
    if not spec:
        return {}
    return {
        field["key"]: field.get("default")
        for field in spec["fields"]
        if field.get("default") is not None
    }


def normalize_params(protocol: str, params: dict) -> dict:
    """只保留当前协议声明的字段，并按类型规范化。"""
    spec = PROTOCOLS.get(protocol)
    if not spec:
        raise ValueError(f"不支持的协议：{protocol}")
    normalized = {}
    for field in spec["fields"]:
        key = field["key"]
        if key not in params:
            if "default" in field:
                normalized[key] = field["default"]
            elif field.get("required"):
                raise ValueError(f"{field['label']}不能为空")
            continue
        value = params[key]
        if field["type"] == "switch":
            normalized[key] = bool(value)
        elif field["type"] == "bandwidth":
            normalized[key] = _bandwidth_mbps(value)
            if normalized[key] < 0:
                raise ValueError(f"{field['label']}不能为负数")
        elif field["type"] == "number":
            try:
                normalized[key] = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{field['label']}必须是数字")
            if "min" in field and normalized[key] < field["min"]:
                raise ValueError(f"{field['label']}不能小于 {field['min']}")
            if "max" in field and normalized[key] > field["max"]:
                raise ValueError(f"{field['label']}不能大于 {field['max']}")
        else:
            normalized[key] = "" if value is None else str(value).strip()
        if field.get("required") and normalized.get(key) in ("", None):
            raise ValueError(f"{field['label']}不能为空")
        if field["type"] == "select" and normalized.get(key) not in ("", None):
            allowed = {option["value"] for option in field.get("options", [])}
            if allowed and normalized[key] not in allowed:
                raise ValueError(f"{field['label']}取值不支持")
    return normalized


def parse_extra(extra_yaml: str) -> dict:
    if not extra_yaml or not extra_yaml.strip():
        return {}
    try:
        data = yaml.safe_load(extra_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(f"高级 YAML 解析失败：{exc}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("高级 YAML 必须是键值映射")
    reserved = {"name", "type", "server", "port"}
    if reserved & set(data):
        raise ValueError("高级 YAML 不能覆盖 name / type / server / port")
    return data


def _put_network(entry: dict, params: dict) -> None:
    network = params.get("network") or "tcp"
    if network and network != "tcp":
        entry["network"] = network
    if network == "ws":
        opts = {}
        if params.get("ws_path"):
            opts["path"] = params["ws_path"]
        if params.get("ws_host"):
            opts["headers"] = {"Host": params["ws_host"]}
        if opts:
            entry["ws-opts"] = opts
    elif network == "grpc" and params.get("grpc_service_name"):
        entry["grpc-opts"] = {"grpc-service-name": params["grpc_service_name"]}


def _common_tls(entry: dict, params: dict, sni_field: str = "servername",
                sni_key: str = "servername") -> None:
    if params.get("tls"):
        entry["tls"] = True
    sni = params.get(sni_key) or params.get("servername")
    if sni:
        entry[sni_field] = sni
    if params.get("skip_cert_verify"):
        entry["skip-cert-verify"] = True


def render_proxy(node: dict, engine: str = "mihomo") -> dict:
    """把一个本地节点渲染为出站字典；Stash 与 Mihomo 的键名存在差异。"""
    params = node.get("params") or {}
    if isinstance(params, str):
        params = json.loads(params or "{}")
    protocol = node["protocol"]
    stash = engine == "stash"
    entry = {
        "name": marked_name(node["name"]),
        "type": params.get("proxy_type") if protocol == "custom" else protocol,
        "server": node["server"],
        "port": int(node["port"]),
    }
    if protocol == "ss":
        entry.update({
            "cipher": params.get("cipher") or "aes-256-gcm",
            "password": params.get("password", ""),
            "udp": bool(params.get("udp", True)),
        })
    elif protocol == "ssr":
        entry.update({
            "cipher": params.get("cipher") or "aes-256-cfb",
            "password": params.get("password", ""),
            "protocol": params.get("protocol") or "origin",
            "obfs": params.get("obfs") or "plain",
            "udp": bool(params.get("udp", True)),
        })
        if params.get("protocol_param"):
            entry["protocol-param"] = params["protocol_param"]
        if params.get("obfs_param"):
            entry["obfs-param"] = params["obfs_param"]
    elif protocol == "vmess":
        entry.update({
            "uuid": params.get("uuid", ""),
            "alterId": int(params.get("alter_id") or 0),
            "cipher": params.get("cipher") or "auto",
        })
        if not stash:
            entry["udp"] = bool(params.get("udp", True))
        _common_tls(entry, params)
        _put_network(entry, params)
    elif protocol == "vless":
        entry["uuid"] = params.get("uuid", "")
        entry["tls"] = bool(params.get("tls", True))
        if params.get("flow"):
            entry["flow"] = params["flow"]
        if not stash:
            entry["udp"] = bool(params.get("udp", True))
        _common_tls(entry, params)
        _put_network(entry, params)
        if params.get("reality_public_key"):
            entry["reality-opts"] = {
                "public-key": params["reality_public_key"],
                "short-id": params.get("reality_short_id", ""),
            }
    elif protocol == "trojan":
        entry["password"] = params.get("password", "")
        if not stash:
            entry["udp"] = bool(params.get("udp", True))
        _common_tls(entry, params, sni_field="sni", sni_key="sni")
        _put_network(entry, params)
    elif protocol == "hysteria2":
        # Stash 用 auth / up-speed / down-speed；Mihomo 用 password / up / down
        if stash:
            entry["auth"] = params.get("password", "")
        else:
            entry["password"] = params.get("password", "")
            entry["udp"] = bool(params.get("udp", True))
        if params.get("sni"):
            entry["sni"] = params["sni"]
        if params.get("skip_cert_verify"):
            entry["skip-cert-verify"] = True
        up = _bandwidth_mbps(params.get("up"))
        down = _bandwidth_mbps(params.get("down"))
        if stash:
            if up:
                entry["up-speed"] = up
            if down:
                entry["down-speed"] = down
        else:
            if up:
                entry["up"] = f"{up} Mbps"
            if down:
                entry["down"] = f"{down} Mbps"
        if params.get("obfs"):
            entry["obfs"] = params["obfs"]
            if params.get("obfs_password"):
                entry["obfs-password"] = params["obfs_password"]
    elif protocol == "tuic":
        version = str(params.get("version") or "5")
        if stash:
            # Stash 需要显式 version；v4 用 token，v5 用 uuid + password
            entry["version"] = int(version)
            if version == "4":
                if params.get("token"):
                    entry["token"] = params["token"]
            else:
                entry["uuid"] = params.get("uuid", "")
                entry["password"] = params.get("password", "")
        else:
            entry["uuid"] = params.get("uuid", "")
            entry["password"] = params.get("password", "")
            entry["udp-relay-mode"] = params.get("udp_relay_mode") or "native"
            if params.get("reduce_rtt"):
                entry["reduce-rtt"] = True
            entry["udp"] = bool(params.get("udp", True))
        entry["congestion-controller"] = params.get("congestion_controller") or "bbr"
        if params.get("sni"):
            entry["sni"] = params["sni"]
        if params.get("skip_cert_verify"):
            entry["skip-cert-verify"] = True
    elif protocol in ("http", "socks5"):
        if params.get("username"):
            entry["username"] = params["username"]
        if params.get("password"):
            entry["password"] = params["password"]
        if protocol == "socks5" and not stash:
            entry["udp"] = bool(params.get("udp", True))
        _common_tls(entry, params, sni_field="sni", sni_key="sni")
    elif protocol == "snell":
        entry.update({
            "psk": params.get("psk", ""),
            "version": int(params.get("version") or 3),
        })
        if not stash:
            entry["udp"] = bool(params.get("udp", True))
        if params.get("obfs"):
            entry["obfs-opts"] = {
                "mode": params["obfs"],
                "host": params.get("obfs_host", ""),
            }
    elif protocol == "anytls":
        entry["password"] = params.get("password", "")
        if not stash:
            entry["udp"] = bool(params.get("udp", True))
        _common_tls(entry, params, sni_field="sni", sni_key="sni")
    elif protocol == "custom":
        if not entry.get("type"):
            entry["type"] = "http"

    extra = parse_extra(node.get("extra_yaml", ""))
    if extra:
        entry.update(extra)
    return entry
