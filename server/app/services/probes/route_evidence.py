"""记录探测连接的实际节点；无控制器证据时查询同域出口。"""
import ipaddress
import os
import time
from pathlib import Path

import httpx

from .base import Detector


def _ip(value) -> str:
    try:
        return str(ipaddress.ip_address(str(value)))
    except ValueError:
        return ""


def matching_chain(connections: list, host: str, source_ips: set[str], port: str) -> list[str]:
    """只接受唯一的 TCP 连接；同域其他设备和旧连接不能冒充本次请求。"""
    matches = []
    for connection in connections:
        meta = connection.get("metadata") or {}
        if (str(meta.get("network") or "").lower() == "tcp"
                and str(meta.get("host") or "").lower().rstrip(".") == host.rstrip(".")
                and _ip(meta.get("sourceIP")) in source_ips
                and str(meta.get("sourcePort") or "") == port
                and str(meta.get("destinationPort") or "") == "443"):
            matches.append(connection.get("chains"))
    if len(matches) != 1 or not isinstance(matches[0], list):
        return []
    chain = matches[0]
    return chain if chain and all(isinstance(part, str) and part for part in chain) else []


class ConnectionReader:
    """可选的局域网只读控制器。配置或连接不可用时直接降级。"""

    def __init__(self, *, endpoint: str | None = None, isolated: bool = False):
        self.nat_source = "" if isolated else _ip(os.environ.get("MAGICPANEL_ROUTE_SOURCE_IP"))
        self.isolated = isolated
        self.endpoint = ""
        self.headers = {}
        try:
            base = httpx.URL(endpoint or os.environ.get("MAGICPANEL_ROUTE_CONTROLLER", ""))
            addr = ipaddress.ip_address(base.host)
            if (base.scheme not in {"http", "https"} or not (addr.is_private or addr.is_loopback)
                    or base.userinfo or base.path not in ("", "/") or base.query or base.fragment):
                return
            secret_file = None if isolated else os.environ.get("MAGICPANEL_ROUTE_TOKEN_FILE")
            if secret_file:
                token = Path(secret_file).read_text(encoding="utf-8").strip()
                if token:
                    self.headers["Authorization"] = f"Bearer {token}"
            self.endpoint = str(base.copy_with(path="/connections"))
        except (ValueError, OSError, httpx.InvalidURL):
            pass

    def observe(self, response: httpx.Response) -> list[str]:
        if not self.endpoint or response.url.scheme != "https" or response.url.port not in (None, 443):
            return []
        stream = response.extensions.get("network_stream")
        if stream is None:
            return []
        try:
            local = stream.get_extra_info("client_addr")
            if not local or not _ip(local[0]):
                return []
            with httpx.Client(trust_env=False, timeout=0.75, headers=self.headers) as client:
                snapshot = client.get(self.endpoint)
                snapshot.raise_for_status()
                connections = snapshot.json().get("connections") or []
            return matching_chain(connections, response.url.host, {_ip(local[0]), self.nat_source} - {""},
                                  str(local[1]))
        except (httpx.HTTPError, ValueError, OSError, TypeError, AttributeError):
            return []


def trace_exit(client: httpx.Client, url: httpx.URL) -> dict:
    """只读取同域的公开诊断响应；不拿通用 IP 查询结果填充服务出口。"""
    if url.scheme != "https" or url.port not in (None, 443):
        return {}
    target = url.copy_with(path="/cdn-cgi/trace", query=None, fragment=None)
    try:
        with client.stream("GET", target, follow_redirects=False, timeout=2.5) as response:
            if response.status_code != 200 or "text/plain" not in response.headers.get("content-type", ""):
                return {}
            body = next(response.iter_bytes(chunk_size=2048), b"")
        item = dict(line.split("=", 1) for line in body.decode(errors="replace").splitlines() if "=" in line)
        ip = _ip(item.get("ip"))
        if ip and item.get("h", "").lower() == url.host.lower():
            return {"ip": ip, "country": item.get("loc", "")[:2].upper(), "domain": url.host,
                    "source": "domain_trace"}
    except (httpx.HTTPError, ValueError):
        pass
    return {}


class RoutedDetector(Detector):
    """只用于管理端服务器网络检测；不加重周期节点检测。"""

    def __init__(self, detector: Detector, reader: ConnectionReader):
        self.detector = detector
        self.reader = reader
        self.platform_id = detector.platform_id
        self.timeout = detector.timeout

    def probe(self, client: httpx.Client):
        observations = []
        def observe(response):
            observations.append((response.url, self.reader.observe(response)))
        hooks = client.event_hooks["response"]
        hooks.append(observe)
        started = time.monotonic()
        try:
            result = self.detector.probe(client)
        finally:
            hooks.pop()
        result.latency_ms = int((time.monotonic() - started) * 1000)
        if observations:
            domain = observations[-1][0]
            routes = [chain for _, chain in observations]
            # 跳转或多样本均有相同路径证据才显示节点；取同域出口时注明域名。
            if routes[0] and all(chain == routes[0] for chain in routes):
                result.extra["route"] = {"node": routes[0][0], "chain": routes[0],
                                         "domain": domain.host, "source": ("probe_connection" if self.reader.isolated
                                                                           else "router_connection")}
            else:
                route = trace_exit(client, domain)
                if route:
                    result.extra["route"] = route
        return result
