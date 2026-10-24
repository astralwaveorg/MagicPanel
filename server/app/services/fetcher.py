"""受限抓取：节点来源与规则来源的远程内容。

默认仅允许 http/https，拒绝环回与私网字面地址；确需内网资源时
在来源上显式开启 allow_private。失败不覆盖最近一次成功快照。
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
import yaml

from .. import config


class FetchError(Exception):
    pass


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    )


def _check_url(url: str, allow_private: bool) -> None:
    """校验 URL：协议、主机、以及主机名解析出来的实际地址。

    只看字面 IP 是不够的——域名同样可以解析到 127.0.0.1 或 169.254.169.254，
    所以这里把主机名解析一遍，逐个检查地址。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"不支持的协议：{parsed.scheme or '(缺失)'}")
    host = parsed.hostname
    if not host:
        raise FetchError("URL 缺少主机名")
    if allow_private:
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if _is_blocked_ip(ip):
            raise FetchError(
                f"目标为内网或保留地址：{host}（如需允许请在来源上开启内网访问）")
        return
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError(f"主机名解析失败：{exc}") from exc
    for info in infos:
        addr = info[4][0]
        try:
            resolved = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(resolved):
            raise FetchError(
                f"主机名 {host} 解析到内网或保留地址 {addr}"
                "（如需允许请在来源上开启内网访问）")


def fetch(url: str, ua: str = config.DEFAULT_UA, allow_private: bool = False,
          proxy: str = "") -> bytes:
    """抓取远程内容：逐跳校验重定向、流式限制体积。

    proxy 非空时经该代理出网（例如服务端出不去机场订阅站时走 Stash）。
    """
    current = url
    # 不继承进程环境中的代理变量，保证抓取路径确定（proxy 参数是显式指定的）
    with httpx.Client(
        timeout=config.FETCH_TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": ua},
        trust_env=False,
        proxy=proxy or None,
    ) as client:
        for _ in range(4):          # 最多 3 次跳转
            _check_url(current, allow_private)
            try:
                with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location", "")
                        if not location:
                            raise FetchError(f"HTTP {resp.status_code} 且缺少 Location")
                        current = urljoin(current, location)
                        continue
                    if resp.status_code != 200:
                        raise FetchError(f"HTTP {resp.status_code}")
                    # 流式读取并限长：避免超大响应先被完整读进内存
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > config.FETCH_MAX_BYTES:
                            raise FetchError(
                                "内容超过大小限制"
                                f"（{config.FETCH_MAX_BYTES // 1024 // 1024} MB）")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    break
            except httpx.HTTPError as exc:
                raise FetchError(f"请求失败：{exc}") from exc
        else:
            raise FetchError("重定向次数过多")
    if not body.strip():
        raise FetchError("内容为空")
    return body


def count_rules(body: bytes, behavior: str, fmt: str = "yaml") -> int:
    """统计规则条目数，支持 yaml(text/yaml) 与纯文本两种格式。

    MRS 是二进制索引文件，条目数无法从文件里数出来，只能返回 0。

    带注释头的 YAML 也要按 payload 条目算：直接把非注释行数一遍，
    会把 ``payload:`` 这行也算进去，显示的条数比实际多 1。
    """
    if fmt == "mrs":
        return 0
    text = body.decode("utf-8", errors="replace")
    stripped = text.strip()
    if stripped.startswith(("payload:", "behavior:")):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise FetchError(f"规则集 YAML 解析失败：{exc}") from exc
        count = _payload_count(data)
        if count is not None:
            return count
    elif stripped.startswith("#"):
        # 注释头 + payload：YAML 解析成功就按 payload 条目算，失败按行数算
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            data = None
        count = _payload_count(data)
        if count is not None:
            return count
    lines = [
        ln for ln in (line.strip() for line in text.splitlines())
        if ln and not ln.startswith("#")
    ]
    return len(lines)


def _payload_count(data) -> int | None:
    """规则集文档里的条目数；不是这种结构时返回 None。"""
    if not isinstance(data, dict):
        return None
    for key in ("payload", "behavior"):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return None
