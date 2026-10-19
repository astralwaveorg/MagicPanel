"""受限抓取：节点来源与规则来源的远程内容。

默认仅允许 http/https，拒绝环回与私网字面地址；确需内网资源时
在来源上显式开启 allow_private。失败不覆盖最近一次成功快照。
"""
import ipaddress
from urllib.parse import urlparse

import httpx
import yaml

from .. import config


class FetchError(Exception):
    pass


def _check_url(url: str, allow_private: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"不支持的协议：{parsed.scheme or '(缺失)'}")
    host = parsed.hostname
    if not host:
        raise FetchError("URL 缺少主机名")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if not allow_private and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    ):
        raise FetchError(f"目标为内网或保留地址：{host}（如需允许请在来源上开启内网访问）")


def fetch(url: str, ua: str = config.DEFAULT_UA, allow_private: bool = False) -> bytes:
    _check_url(url, allow_private)
    try:
        # 不继承进程环境中的代理变量，保证抓取路径确定
        with httpx.Client(
            timeout=config.FETCH_TIMEOUT,
            follow_redirects=True,
            max_redirects=3,
            headers={"User-Agent": ua},
            trust_env=False,
        ) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        raise FetchError(f"请求失败：{exc}") from exc
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code}")
    body = resp.content
    if len(body) > config.FETCH_MAX_BYTES:
        raise FetchError(f"内容超过大小限制（{config.FETCH_MAX_BYTES // 1024 // 1024} MB）")
    if not body.strip():
        raise FetchError("内容为空")
    return body


def parse_nodes(body: bytes) -> list[dict]:
    """解析节点订阅，返回 [{name, type}]；不接受不含 proxies 的内容。"""
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise FetchError(f"YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise FetchError("内容不含 proxies 列表，不是有效的节点订阅")
    nodes = []
    for item in data["proxies"]:
        if isinstance(item, dict) and item.get("name") and item.get("type"):
            nodes.append({"name": str(item["name"]), "type": str(item["type"])})
    if not nodes:
        raise FetchError("订阅中没有可用节点")
    return nodes


def count_rules(body: bytes, behavior: str) -> int:
    """统计规则条目数，支持 yaml(text/yaml) 与纯文本两种格式。"""
    text = body.decode("utf-8", errors="replace")
    stripped = text.strip()
    if stripped.startswith("payload:") or stripped.startswith("behavior:"):
        try:
            data = yaml.safe_load(text)
            payload = (data or {}).get("payload") or []
            return len(payload)
        except yaml.YAMLError as exc:
            raise FetchError(f"规则集 YAML 解析失败：{exc}") from exc
    lines = [
        ln for ln in (line.strip() for line in text.splitlines())
        if ln and not ln.startswith("#")
    ]
    return len(lines)
