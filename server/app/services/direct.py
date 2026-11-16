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
import re
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


# 境内回显服务：服务器在国内（CN IP），路由器规则命中 cn-ip → DIRECT，
# 面板访问它拿到的必然是家宽公网 IP——这是「直连路径」的独立证据。
# 注意：ipip.net 已被 magic-proxy 规则代理（会拿到代理出口 IP），不能用作境内回显
DOMESTIC_ECHO_URLS = ("https://cip.cc", "http://members.3322.org/dyndns/getip")


def _fetch_domestic_egress() -> dict:
    """境内回显：拿家宽公网 IP。两个服务都失败时返回空。"""
    for url in DOMESTIC_ECHO_URLS:
        try:
            with httpx.Client(timeout=EGRESS_TIMEOUT, follow_redirects=True,
                              trust_env=False,
                              headers={"User-Agent": "curl/8.0"}) as client:
                resp = client.get(url)
                resp.raise_for_status()
                text = resp.text
        except Exception:
            continue
        m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", text)
        if m:
            return {"ip": m.group(1), "via": url}
    return {}


def _is_china_egress(info: dict) -> bool:
    code = str(info.get("country_code") or "").upper()
    country = str(info.get("country") or "")
    return code == "CN" or ("中国" in country and "台湾" not in country)


def observe() -> dict:
    """主动路径观测：用「境外回显 + 境内回显」差分证明真实路径。

    出口归属地本身不能区分「透明代理接管」和「本地网络就在那个地区」；
    但境内回显（cn 规则必然直连）拿到的是家宽公网 IP，把它与境外回显
    对比就能得出路径结论：

    * 两边 IP 一致 → 境外流量也直连出去了（透明代理未接管，测速已旁路）；
    * 两边不一致、境外出口非中国 → 境外流量经透明代理转发（测速拨号
      同样会被接管，面板的三条防线只保证不叠加环境代理）。
    """
    foreign = _fetch_egress()
    domestic = _fetch_domestic_egress()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _cache["at"] = time.monotonic()
    _cache["data"] = foreign
    _cache["checked_at"] = checked_at

    evidence = {"foreign": foreign, "domestic": domestic, "checked_at": checked_at}
    f_ip, d_ip = foreign.get("ip"), domestic.get("ip")
    if f_ip and d_ip and f_ip == d_ip:
        evidence["transparent_proxy"] = "bypassed"
        evidence["conclusion"] = "境外与境内回显同源（家宽公网 IP）：透明代理未接管境外流量，测速已旁路。"
    elif f_ip and d_ip and not _is_china_egress(foreign):
        evidence["transparent_proxy"] = "active"
        evidence["conclusion"] = (
            f"境外回显为 {foreign.get('country_code') or '境外'} 出口（{f_ip}），"
            f"境内回显为家宽公网 IP（{d_ip}）：境外流量经路由器透明代理转发，"
            "测速拨号同样会被接管。")
    elif f_ip and d_ip:
        evidence["transparent_proxy"] = "active"
        evidence["conclusion"] = "境外与境内回显不同源但境外出口显示中国归属，路径判定存疑，请结合路由器连接列表复核。"
    else:
        evidence["transparent_proxy"] = "unknown"
        evidence["conclusion"] = "回显服务不可达，无法判定路径；请稍后重试。"

    observation = last_observation()
    observation["state"] = "observed"
    observation["source_kind"] = "path_probe"
    observation["path_evidence"] = evidence
    observation["notes"] = [
        evidence["conclusion"],
        "境内回显走 cn-ip 直连规则，是独立于出口归属地的路径证据。",
    ]
    _cache["observation"] = observation
    return observation


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
    cached_obs = _cache.get("observation")
    if isinstance(cached_obs, dict) and cached_obs.get("path_evidence"):
        cached_obs["env_proxies"] = proxies
        return cached_obs
    notes = ["尚未发起主动路径检测；出口地址只是被动观测。点击「发起检测」获取路径证据。"]
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
