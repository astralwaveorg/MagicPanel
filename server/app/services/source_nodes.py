"""节点来源的节点定义：只取 proxies 段，渲染时供内联模式展开。

机场订阅本身是一份完整的 Clash 配置（含它自己的 rules / dns / proxy-groups），
面板只取其中的 proxies：其余内容与面板自己的策略无关，
留着既撑大快照，也会让内联模式把机场的规则和策略组混进产物。

过滤与后缀的语义对齐客户端：
* 来源自身的过滤正则作用在**原始节点名**上（provider 的 filter 先于 override）；
* 策略组的过滤正则作用在**加过后缀的节点名**上（客户端的组过滤跑在 provider 之后）。
"""
import base64
import json
import re
import urllib.parse

import yaml


class SourceError(Exception):
    """订阅内容不合法。"""


def extract(body: bytes) -> list[dict]:
    """从订阅内容里取出节点定义（保留完整定义：类型、地址、凭据等）。

    两种常见格式都认：
      * Clash YAML —— `proxies:` 列表（面板默认 UA 取到的就是这种）；
      * base64 编码的 URI 列表 —— `ss://` / `trojan://` / `vmess://` /
        `vless://` 每行一条（机场按客户端 UA 下发的那种）。
    两者都认不出来时，错误信息要指出内容像什么，别只说"格式错误"。
    """
    text = body.decode("utf-8", errors="replace").strip()
    if text.startswith("proxies:") or "\nproxies:" in text[:4096]:
        return _extract_clash_yaml(body)
    uris = _decode_uri_list(text)
    if uris:
        return _from_uris(uris)
    raise SourceError(_describe_unparsable(text))


def _extract_clash_yaml(body: bytes) -> list[dict]:
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise SourceError(f"YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise SourceError("内容不含 proxies 列表，不是有效的节点订阅")
    nodes = [dict(item) for item in data["proxies"]
             if isinstance(item, dict) and item.get("name") and item.get("type")]
    if not nodes:
        raise SourceError("订阅中没有可用节点")
    return nodes


def _describe_unparsable(text: str) -> str:
    """给一句能照着做的提示：认不出来的内容大多是哪一类。"""
    if text.startswith("<") or "<html" in text[:200].lower():
        return ("内容是网页而不是节点订阅（多半是机场的验证页或风控页）；"
                "带上正确的 Cookie / User-Agent 再试")
    if text.startswith("{"):
        return "内容是 JSON，不是受支持的节点订阅格式"
    if re.fullmatch(r"[A-Za-z0-9+/=\s]+", text):
        return ("内容是 base64，但解码后不是节点 URI 列表；"
                "这类机场的加密订阅面板无法解析，"
                "请在客户端导出成 Clash YAML 后再上传")
    return "内容既不是 Clash YAML，也不是 base64 的节点 URI 列表"


def _decode_uri_list(text: str) -> list[str]:
    """尝试把 base64 内容解成 URI 列表；不是就返回空。"""
    compact = "".join(text.split())
    if len(compact) < 16 or not re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
        return []
    try:
        raw = base64.b64decode(compact + "=" * (-len(compact) % 4), validate=False)
    except Exception:
        return []
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    lines = [ln.strip() for ln in decoded.splitlines()]
    uris = [ln for ln in lines if "://" in ln]
    return uris if uris else []


def _from_uris(uris: list[str]) -> list[dict]:
    """把 URI 列表转成 Clash 的节点定义。"""
    nodes: list[dict] = []
    errors: list[str] = []
    for uri in uris:
        try:
            node = _uri_to_node(uri)
        except SourceError as exc:
            errors.append(str(exc))
            continue
        if node:
            nodes.append(node)
    if not nodes:
        raise SourceError(
            "节点 URI 列表解析失败"
            + (f"：{errors[0]}" if errors else ""))
    return nodes


def _q(query: str, key: str, default: str = "") -> str:
    values = urllib.parse.parse_qs(query, keep_blank_values=True)
    got = values.get(key)
    return got[0] if got else default


def _flag(value: str) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


def _uri_to_node(uri: str) -> dict:
    scheme, _, rest = uri.partition("://")
    scheme = scheme.lower()
    if scheme not in ("ss", "trojan", "vmess", "vless"):
        raise SourceError(f"暂不支持的节点协议：{scheme}")
    body, _, frag = rest.partition("#")
    name = urllib.parse.unquote(frag).strip() or "未命名节点"
    if scheme == "vmess":
        return _vmess_to_node(body, name)
    main, _, query = body.partition("?")
    cred, _, hostport = main.rpartition("@")
    host, _, port_s = hostport.partition(":")
    if not host or not port_s:
        raise SourceError("节点地址不完整")
    try:
        port = int(port_s)
    except ValueError:
        raise SourceError("节点端口不是数字")
    if scheme == "ss":
        return _ss_to_node(cred, host, port, name, query)
    if scheme == "trojan":
        return _trojan_to_node(cred, host, port, name, query)
    return _vless_to_node(cred, host, port, name, query)


def _ss_to_node(cred: str, host: str, port: int, name: str, query: str) -> dict:
    # SIP002：ss://BASE64(method:password)@host:port
    # 旧格式：ss://BASE64(method:password@host:port)
    if "@" in cred:
        userinfo, _, hostpart = cred.partition("@")
        if not hostpart:
            userinfo = cred
        decoded = _b64_text(userinfo)
    else:
        decoded = _b64_text(cred)
    if ":" not in decoded:
        raise SourceError("ss 节点缺少加密方式或密码")
    cipher, _, password = decoded.partition(":")
    node = {"name": name, "type": "ss", "server": host, "port": port,
            "cipher": cipher, "password": password, "udp": True}
    plugin = _q(query, "plugin")
    if plugin:
        node["plugin"] = plugin
    return node


def _trojan_to_node(cred: str, host: str, port: int, name: str, query: str) -> dict:
    node = {"name": name, "type": "trojan", "server": host, "port": port,
            "password": urllib.parse.unquote(cred), "udp": True}
    sni = _q(query, "sni") or _q(query, "peer")
    if sni:
        node["sni"] = sni
    if _flag(_q(query, "allowInsecure")) or _flag(_q(query, "insecure")):
        node["skip-cert-verify"] = True
    return node


def _vless_to_node(cred: str, host: str, port: int, name: str, query: str) -> dict:
    node = {"name": name, "type": "vless", "server": host, "port": port,
            "uuid": urllib.parse.unquote(cred), "udp": True}
    sni = _q(query, "sni") or _q(query, "peer")
    security = _q(query, "security", "none").lower()
    if security in ("tls", "reality"):
        node["tls"] = True
    if sni:
        node["servername"] = sni
    flow = _q(query, "flow")
    if flow:
        node["flow"] = flow
    if security == "reality":
        node["reality-opts"] = {
            "public-key": _q(query, "pbk"),
            "short-id": _q(query, "sid"),
        }
        node["client-fingerprint"] = _q(query, "fp", "chrome")
    if _flag(_q(query, "allowInsecure")) or _flag(_q(query, "insecure")):
        node["skip-cert-verify"] = True
    network = _q(query, "type", "tcp").lower()
    if network in ("ws", "http"):
        node["network"] = "ws"
        path = _q(query, "path", "/")
        node["ws-opts"] = {"path": path}
        if _q(query, "host"):
            node["ws-opts"]["headers"] = {"Host": _q(query, "host")}
    elif network == "grpc":
        node["network"] = "grpc"
        node["grpc-opts"] = {"grpc-service-name": _q(query, "serviceName")}
    return node


def _vmess_to_node(body: str, name: str) -> dict:
    raw = _b64_text(body)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(f"vmess 节点内容不是 JSON：{exc}") from exc
    port = data.get("port")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise SourceError("vmess 节点端口不是数字")
    node = {
        "name": name or str(data.get("ps") or "未命名节点"),
        "type": "vmess",
        "server": str(data.get("add") or ""),
        "port": port,
        "uuid": str(data.get("id") or ""),
        "alterId": int(data.get("aid") or 0),
        "cipher": str(data.get("scy") or "auto"),
        "udp": True,
    }
    if str(data.get("tls") or "").lower() in ("tls", "true"):
        node["tls"] = True
        if data.get("sni"):
            node["servername"] = str(data["sni"])
        if data.get("alpn"):
            node["alpn"] = [x for x in str(data["alpn"]).split(",") if x]
    if str(data.get("verify_cert") or "").lower() in ("false", "0"):
        node["skip-cert-verify"] = True
    nettype = str(data.get("net") or "tcp").lower()
    if nettype == "ws":
        node["network"] = "ws"
        host = data.get("host")
        node["ws-opts"] = {"path": str(data.get("path") or "/")}
        if host:
            node["ws-opts"]["headers"] = {"Host": str(host)}
    elif nettype == "grpc":
        node["network"] = "grpc"
        node["grpc-opts"] = {"grpc-service-name": str(data.get("path") or "")}
    return node


def _b64_text(value: str) -> str:
    compact = value.strip().replace("-", "+").replace("_", "/")
    try:
        raw = base64.b64decode(compact + "=" * (-len(compact) % 4))
    except Exception as exc:
        raise SourceError(f"base64 解码失败：{exc}") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError(f"base64 内容不是文本：{exc}") from exc


def dump(nodes: list[dict]) -> str:
    """只含 proxies 段的 YAML 文本（快照与 provider 文件都用它）。"""
    return yaml.safe_dump({"proxies": nodes}, allow_unicode=True,
                          sort_keys=False, width=4096)


def parse(text: str) -> list[dict]:
    """从已存快照里取回节点定义；内容坏了就当没有节点。"""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        return []
    return [dict(item) for item in data["proxies"]
            if isinstance(item, dict) and item.get("name") and item.get("type")]


def match(pattern: str, name: str) -> bool:
    """过滤正则是否命中节点名（与客户端一致：不要求整串匹配）。"""
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, name))
    except re.error:
        return True     # 正则无效时不过滤：保存来源时已经拦过一次
