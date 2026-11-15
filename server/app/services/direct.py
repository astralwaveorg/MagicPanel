"""直连保障：测速链路必须绕开系统代理。

背景：NAS 上的 Docker 配了代理（docker.service 的 HTTP_PROXY/HTTPS_PROXY 注入
容器），面板进程会继承这些变量；将来 NAS 自身也可能跑代理。测速衡量的是
"从本服务器所在网络直连节点服务器的延迟"，一旦被代理接管，这个数字就失去
意义（会变成代理出口的延迟，还会被代理的拥塞放大）。

三条防线：
  1. 面板自身的 HTTP 客户端一律 ``trust_env=False``（抓取、测速控制面、
     WebDAV、门户），环境里的代理变量对它们无效；
  2. Mihomo 核心子进程显式剥离代理变量（``direct_env``），不让"核心恰好
     不读环境变量"这种隐含前提承担直连责任；
  3. 应用层管不到透明代理／TUN；出口观测只提供线索，是否旁路必须用独立路径证据验证。
"""
from __future__ import annotations

import os
import math
import time
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any

import httpx

# 需要剥离的代理环境变量（含大小写两种写法）
PROXY_ENV_KEYS = (
    "http_proxy", "https_proxy", "all_proxy", "ftp_proxy", "no_proxy",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY", "NO_PROXY",
)

EGRESS_TIMEOUT = 6.0
CACHE_TTL = 600.0
_cache: dict[str, Any] = {"at": 0.0, "data": None}


def direct_env(base: dict | None = None) -> dict:
    """子进程环境：剥离全部代理变量，并写死 NO_PROXY=*。

    核心是 Go 写的，``net/http.ProxyFromEnvironment`` 会读这些变量；
    显式剥离比"依赖核心实现不读"可靠。
    """
    env = dict(os.environ if base is None else base)
    for key in PROXY_ENV_KEYS:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


# 真正指向代理的变量；NO_PROXY 是"绕过清单"，不配置代理时不算代理
PROXY_ENDPOINT_KEYS = (
    "http_proxy", "https_proxy", "all_proxy", "ftp_proxy",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY",
)


def env_proxies() -> dict:
    """当前进程里指向代理的环境变量（面板自身会忽略它们，仅用于展示）。"""
    return {k: v for k, v in os.environ.items() if k in PROXY_ENDPOINT_KEYS and v}


def _fetch_egress() -> dict:
    """直连查询出口 IP 与归属地（trust_env=False，不走环境代理）。"""
    headers = {"User-Agent": "MagicPanel/1.0 (self-check)"}
    urls = ("https://api.ip.sb/geoip", "https://ipapi.co/json/")
    for url in urls:
        try:
            with httpx.Client(timeout=EGRESS_TIMEOUT, follow_redirects=True,
                              trust_env=False, headers=headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            continue
        ip = str(data.get("ip") or "").strip()
        if not ip:
            continue
        return {
            "ip": ip,
            "country": str(data.get("country") or data.get("country_name") or "").strip(),
            "country_code": str(data.get("country_code") or "").strip().upper(),
            "org": str(data.get("organization") or data.get("org") or "").strip(),
        }
    return {}


def egress(refresh: bool = False) -> dict:
    """出口检测结果，缓存 10 分钟。"""
    now = time.monotonic()
    if not refresh and _cache["data"] and now - _cache["at"] < CACHE_TTL:
        return _cache["data"]
    data = _fetch_egress()
    _cache["at"] = now
    _cache["data"] = data
    _cache["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return data


def last_observation() -> dict:
    """只读安全摘要；出口归属地不能证明透明代理旁路。"""
    raw = _cache.get("data")
    eg = {}
    if isinstance(raw, dict):
        try:
            eg["ip"] = str(ip_address(raw.get("ip", "")))
        except ValueError:
            pass
        for field in ("country", "country_code", "org"):
            value = raw.get(field)
            if isinstance(value, str) and value:
                eg[field] = value[:160]
    freshness = "unknown"
    if eg.get("ip"):
        at = _cache.get("at")
        if isinstance(at, (float, int)) and not isinstance(at, bool) and math.isfinite(at):
            age = time.monotonic() - at
            if age >= 0:
                freshness = "fresh" if age < CACHE_TTL else "stale"
    proxies = sorted(env_proxies())
    notes = ["出口地址只是最近观测，不能证明 NAS 已绕过路由器透明代理。"]
    if proxies:
        notes.append("检测到代理环境变量（" + "、".join(proxies) + "）；应用请求忽略这些变量。")
    return {
        "state": "unknown",
        "source_kind": "egress_reported",
        "freshness": freshness,
        "notes": notes,
        "egress": eg,
        "env_proxies": proxies,
        "checked_at": _cache.get("checked_at", "") if eg.get("ip") else "",
    }


def check(refresh: bool = False) -> dict:
    """兼容显式内部诊断；HTTP GET 只能调用 last_observation。"""
    egress(refresh)
    return last_observation()
