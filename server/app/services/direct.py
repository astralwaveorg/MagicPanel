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
  3. 应用层管不到透明代理／TUN：那种情况下只能靠 NAS 侧的路由规则绕开，
     所以这里提供一个直连自检，把出口地址与结论暴露出来。
"""
from __future__ import annotations

import os
import time
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


def env_proxies() -> dict:
    """当前进程里的代理环境变量（面板自身会忽略它们，仅用于展示）。"""
    return {k: v for k, v in os.environ.items() if k in PROXY_ENV_KEYS and v}


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
    return data


def check(refresh: bool = False) -> dict:
    """直连自检：出口地址 + 代理环境变量 + 结论。"""
    proxies = env_proxies()
    eg = egress(refresh)
    notes: list[str] = []
    state = "unknown"
    code = (eg.get("country_code") or "").upper()
    if eg.get("ip"):
        where = eg.get("country") or code or "未知地区"
        if code and code != "CN":
            state = "risk"
            notes.append(
                f"面板直连出口 {eg['ip']}（{where}）不在中国大陆："
                "如果 NAS 后续启用了透明代理／TUN，测速会被代理接管，此项需要复核")
        else:
            state = "ok"
            notes.append(f"面板直连出口 {eg['ip']}（{where}）：测速走本机直连，未经过代理")
    else:
        notes.append("出口检测失败（网络不通或查询接口不可用），无法判断是否被代理接管")
    if proxies:
        keys = "、".join(sorted(proxies))
        notes.append(
            f"检测到系统代理环境变量（{keys}）：面板自身的请求与核心子进程都不使用它们")
    return {
        "state": state,
        "notes": notes,
        "egress": eg,
        "env_proxies": proxies,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
