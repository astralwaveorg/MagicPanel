"""探测器框架：把「节点能不能用某平台」从二元判定升级成可扩展的精细化探测器矩阵。

解决的问题
----------
旧实现（``services/unlock_check.py``）用「HTTP 状态码 + 几个关键词」一刀切，
平台之间的差异被抹平：

* Netflix 只看 200/403，分不出「只给自制剧」和「完整片库」；
* ChatGPT / Claude 的 403 与「地区拒绝」「Cloudflare 风控」混为一谈，
  误判会直接反映到节点能力徽章上。

本模块给出统一的状态语义与执行框架：

======================  ====================================================
状态                    含义（判定必须要有证据，不许臆断）
======================  ====================================================
``unlocked``            有明确证据表明该出口可用；
``blocked``             有明确证据表明该出口被服务按地区 / 账号拒绝；
``unknown``             证据不足（人机校验、风控页、无特征 403），
                        **既不能**当成解锁，**也不能**当成拒绝；
``error``               网络层失败（超时、连接错误、5xx、429 限流）；
``unsupported``         服务本身不支持该出口（标题不在目录、地区未上线）。
======================  ====================================================

框架负责并发执行、失败隔离、超时控制与重试；平台差异写在各平台的
``Detector`` 子类里（见 ``platforms.py``）。
"""
import logging
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Sequence

import httpx

logger = logging.getLogger("magicpanel.probes")

# 浏览器 UA：多数流媒体站点会对明显不是浏览器的 UA 直接 403。
# 与 unlock_check 保持同一思路，但常量独立定义，避免包之间互相 import。
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DEFAULT_TIMEOUT = 8.0
DEFAULT_RETRY = 1
DEFAULT_MAX_WORKERS = 6
# 正文截断长度：足够覆盖标题页里的内嵌 JSON，又不至于把几十 MB 的页面读进内存。
MAX_BODY_CHARS = 60000

# 状态常量（ProbeResult.state 只允许这些值）
STATE_UNLOCKED = "unlocked"
STATE_BLOCKED = "blocked"
STATE_UNKNOWN = "unknown"
STATE_ERROR = "error"
STATE_UNSUPPORTED = "unsupported"
VALID_STATES = frozenset({STATE_UNLOCKED, STATE_BLOCKED, STATE_UNKNOWN,
                           STATE_ERROR, STATE_UNSUPPORTED})

# 人机校验 / 风控挑战特征：命中即判 unknown（不能据此说节点被地区拒绝）
CF_CHALLENGE_PATTERN = re.compile(
    r"Just a moment|challenge-platform|cf-chl|Attention Required|请完成以下操作",
    re.IGNORECASE)

# 通用地区限制特征：平台没有单独声明时用它兜底。
# 只在非 2xx/3xx 响应上比对，避免把 200 页面里的文案误判成地区拒绝。
GENERIC_REGION_PATTERNS = (
    r"not available in your country",
    r"not available in your region",
    r"isn'?t available in your (?:country|region)",
    r"unavailable in your (?:country|region)",
    r"unsupported country",
    r"country, region, or territory not supported",
    r"该(?:国家|地区)不(?:支持|可用)",
    r"在您所在(?:国家|地区)不可用",
)


@dataclass
class ProbeResult:
    """单个平台对一个节点的探测结论。"""

    platform: str          # 平台 id，如 "netflix"
    state: str             # unlocked / blocked / unknown / error / unsupported
    status: int | None     # HTTP 状态码
    region: str = ""       # 识别出的地区码（US/HK/JP…），没有则空
    detail: str = ""       # 人类可读说明（如 "Netflix 仅自制剧可用"）
    latency_ms: int = 0
    extra: dict = field(default_factory=dict)   # 平台特有信息（如 netflix 的 originals/full_library）

    def to_dict(self) -> dict:
        """转成可 JSON 序列化的字典（写缓存 / 传给前端都走这个）。"""
        return {
            "platform": self.platform,
            "state": self.state,
            "status": self.status,
            "region": self.region,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
            "extra": dict(self.extra),
        }


@dataclass
class Classification:
    """classify() 的结论：状态 + 依据说明 + 命中的特征名。"""

    state: str
    detail: str = ""
    matched: str = ""


@dataclass(frozen=True)
class Markers:
    """某个平台的正文 / 状态码特征配置。

    * ``ok_markers``：命中才算「确实可用」的特征。为空时只看状态码；
    * ``region_markers``：命中即判定「被地区限制」的特征；
    * ``challenge_markers``：命中即判定「人机校验 / 风控」的特征（与通用 CF 特征并用）；
    * ``block_requires_marker``：True 表示「光有 403 不算拒绝」——
      没有地区特征时按 unknown 处理（AI 站点与风控重的站点需要这个口径）。
    """

    unlock_status: tuple[int, ...] = (200, 301, 302, 303, 307, 308)
    blocked_status: tuple[int, ...] = (403,)
    unsupported_status: tuple[int, ...] = (404,)
    ok_markers: tuple[str, ...] = ()
    region_markers: tuple[str, ...] = ()
    challenge_markers: tuple[str, ...] = ()
    block_requires_marker: bool = False


@dataclass
class ProbeResponse:
    """一次 HTTP 取回的最小快照（只保留判定需要的字段）。"""

    status: int
    text: str
    url: str = ""
    headers: dict = field(default_factory=dict)


def _first_match(text: str, patterns: Sequence[str]) -> str:
    """返回第一个命中的特征名（用于 detail 里写清依据）。"""
    for pattern in patterns:
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return pattern
        except re.error:  # 特征写错时不该让整个探测崩掉
            logger.warning("无效的特征正则：%s", pattern)
    return ""


def classify(status: int | None, body: str, markers: Markers | None = None) -> Classification:
    """统一的状态判定。

    规则顺序（顺序本身就是语义）：

    1. 没有响应 → ``error``（网络层失败）；
    2. 正文含人机校验 / 风控特征 → ``unknown``（**任何状态码**下都算，
       Cloudflare 挑战页偶尔也回 200）；
    3. 2xx / 3xx → ``unlocked``（若平台声明了 ``ok_markers``，则还要命中它，
       否则判 ``unknown``，宁可说「拿不准」也不冒充解锁）；
    4. 正文含地区限制特征 → ``blocked``；
    5. 命中平台声明的拒绝状态码 → ``blocked``
       （``block_requires_marker=True`` 时改为 ``unknown``）；
    6. 命中不支持状态码（404 等）→ ``unsupported``；
    7. 429 / 5xx → ``error``（限流与服务端错误都不是地区问题）。
    """
    markers = markers or Markers()
    text = body or ""

    if status is None:
        return Classification(STATE_ERROR, "无响应（网络层失败）")

    hit = _first_match(text, tuple(markers.challenge_markers) + (CF_CHALLENGE_PATTERN.pattern,))
    if hit:
        return Classification(STATE_UNKNOWN, f"命中人机校验 / 风控特征（{hit}），无法判定是否地区限制", hit)

    if 200 <= status < 400:
        if markers.ok_markers:
            hit = _first_match(text, markers.ok_markers)
            if not hit:
                return Classification(STATE_UNKNOWN,
                                     f"HTTP {status} 但正文缺少平台可用特征，无法确认")
        return Classification(STATE_UNLOCKED, "")

    hit = _first_match(text, tuple(markers.region_markers) + GENERIC_REGION_PATTERNS)
    if hit:
        return Classification(STATE_BLOCKED, f"命中地区限制特征（{hit}）", hit)

    if status in markers.blocked_status:
        if markers.block_requires_marker:
            return Classification(STATE_UNKNOWN,
                                 f"HTTP {status} 且无地区特征，无法区分地区拒绝与风控拦截")
        return Classification(STATE_BLOCKED, f"HTTP {status} 被服务拒绝")

    if status in markers.unsupported_status:
        return Classification(STATE_UNSUPPORTED, f"HTTP {status}：该内容 / 服务在此出口不存在")

    if status == 429:
        return Classification(STATE_ERROR, "HTTP 429 限流（非地区问题）")

    if 500 <= status < 600:
        return Classification(STATE_ERROR, f"HTTP {status} 服务端错误")

    return Classification(STATE_ERROR, f"HTTP {status}")


class Detector(ABC):
    """探测器基类：一个平台一个子类。

    子类必须给出 ``platform_id`` / ``display_name`` / ``category`` / ``url``，
    并实现 ``probe()``。``category`` 取值：``streaming`` / ``ai`` / ``social_other``。
    """

    platform_id: str = ""
    display_name: str = ""
    category: str = ""
    url: str = ""
    # 需要跟随重定向的平台在 fetch() 里显式传 follow_redirects；
    # 默认跟随（与浏览器一致），否则 301/302 会让所有平台都判成 error。
    follow_redirects: bool = True

    # ---------------------------------------------------------------- 工具方法

    def fetch(self, client: httpx.Client, url: str | None = None,
              timeout: float | None = None, follow_redirects: bool | None = None) -> ProbeResponse:
        """取回状态码与正文。异常直接抛给框架，由框架做失败隔离。"""
        target = url or self.url
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        # 默认跟随重定向（与浏览器一致），否则 301/302 会让所有平台都判成 error。
        kwargs["follow_redirects"] = self.follow_redirects if follow_redirects is None else follow_redirects
        resp = client.get(target, **kwargs)
        text = resp.text or ""
        return ProbeResponse(status=resp.status_code, text=text[:MAX_BODY_CHARS],
                             url=str(resp.url), headers=dict(resp.headers))

    def extract_region(self, text: str,
                       patterns: Sequence[str] | None = None) -> str:
        """从正文里取地区码（US/HK/JP…）；取不到就返回空串。

        默认模式覆盖常见几种写法：``"countryCode":"US"`` / ``"country":"US"`` /
        ``"countryIso":"US"`` / ``"isoCode":"US"``。
        """
        from .platforms import REGION_PATTERNS  # 延迟导入避免循环依赖

        for pattern in (patterns if patterns is not None else REGION_PATTERNS):
            try:
                match = re.search(pattern, text, re.IGNORECASE)
            except re.error:
                continue
            if not match:
                continue
            code = match.group(1).upper() if match.groups() else match.group(0).upper()
            if len(code) == 2 and code.isalpha():
                return code
        return ""

    # ---------------------------------------------------------------- 探测入口

    @abstractmethod
    def probe(self, client: httpx.Client) -> ProbeResult:
        """执行本平台的探测，返回结论。异常会被框架捕获成 error 结果。"""
        raise NotImplementedError


def make_client_factory(proxy: str | None = None, *, headers: dict | None = None,
                         follow_redirects: bool = True,
                         user_agent: str = USER_AGENT) -> Callable[[float], httpx.Client]:
    """生成客户端工厂：``factory(timeout) -> httpx.Client``。

    传给 ``detect_platforms`` 时，框架按超时值创建客户端；
    ``proxy`` 非空时请求经该代理（节点检测场景）。
    """

    def factory(timeout: float) -> httpx.Client:
        base_headers = {"User-Agent": user_agent}
        base_headers.update(headers or {})
        return httpx.Client(trust_env=False, timeout=timeout,
                            follow_redirects=follow_redirects,
                            proxy=proxy or None, headers=base_headers)

    return factory


def _should_retry(result: ProbeResult) -> bool:
    """只在超时 / 5xx 时重试；403 一律不重试（重试也不会变，且会加重风控）。"""
    if result.state != STATE_ERROR:
        return False
    if result.status is None:
        return True          # 超时 / 连接失败
    return result.status >= 500


def _normalize_result(result: object, platform_id: str) -> ProbeResult:
    """把探测器的返回值规整成本模块的 ``ProbeResult``。

    探测器可能来自另一个模块实例（应用重载、测试里重建模块），
    ``isinstance`` 会误判成「非法返回值」，这里按字段取值重新包一层。
    """
    if isinstance(result, ProbeResult):
        return result
    state = getattr(result, "state", None)
    if not isinstance(state, str) or state not in VALID_STATES:
        return ProbeResult(platform=platform_id, state=STATE_ERROR, status=None,
                           detail="探测器返回值非法")
    return ProbeResult(
        platform=getattr(result, "platform", "") or platform_id,
        state=state,
        status=getattr(result, "status", None),
        region=getattr(result, "region", "") or "",
        detail=getattr(result, "detail", "") or "",
        latency_ms=int(getattr(result, "latency_ms", 0) or 0),
        extra=dict(getattr(result, "extra", {}) or {}),
    )


def _run_detector(detector: Detector, client_factory: Callable[[float], httpx.Client],
                  timeout: float, retry: int) -> ProbeResult:
    """跑一个探测器：失败隔离 + 重试。"""
    started = time.monotonic()
    last: ProbeResult | None = None
    for attempt in range(max(0, retry) + 1):
        try:
            client = client_factory(timeout)
        except Exception as exc:  # 客户端都建不出来，后面就不用试了
            logger.warning("探测器 %s 客户端创建失败：%s", detector.platform_id, exc)
            return ProbeResult(platform=detector.platform_id, state=STATE_ERROR,
                               status=None, detail=f"客户端创建失败：{type(exc).__name__}: {exc}")

        result: object
        try:
            if hasattr(client, "__enter__"):
                with client:
                    result = detector.probe(client)
            else:
                result = detector.probe(client)
        except httpx.TimeoutException as exc:
            result = ProbeResult(platform=detector.platform_id, state=STATE_ERROR,
                                 status=None, detail=f"请求超时（{type(exc).__name__}）")
        except Exception as exc:
            # 失败隔离：一个平台炸了不影响其它平台。
            logger.warning("探测器 %s 执行失败：%s", detector.platform_id, exc)
            result = ProbeResult(platform=detector.platform_id, state=STATE_ERROR,
                                 status=None, detail=f"{type(exc).__name__}: {exc}")

        result = _normalize_result(result, detector.platform_id)

        if attempt < retry and _should_retry(result):
            last = result
            logger.info("探测器 %s 第 %s 次失败，准备重试", detector.platform_id, attempt + 1)
            continue

        if result.latency_ms <= 0:
            result.latency_ms = int((time.monotonic() - started) * 1000)
        if not result.platform:
            result.platform = detector.platform_id
        return result

    return last or ProbeResult(platform=detector.platform_id, state=STATE_ERROR,
                                status=None, detail="重试后仍未取得结果")


def detect_platforms(ids: Sequence[str] | None = None,
                      client_factory: Callable[[float], httpx.Client] | None = None,
                      timeout: float = DEFAULT_TIMEOUT,
                      retry: int = DEFAULT_RETRY,
                      *,
                      max_workers: int = DEFAULT_MAX_WORKERS,
                      detectors: Sequence[Detector] | None = None) -> list[ProbeResult]:
    """并发执行一批平台探测。

    * ``ids`` 为 None 时跑全部平台；未知 id 直接忽略（不报错，便于前端传旧缓存里的 id）。
    * ``client_factory`` 形如 ``factory(timeout) -> httpx.Client``；
      传 None 时用默认工厂（不挂代理直连）。
    * 一个平台抛异常只影响它自己（结果为 error），其余平台照常跑完。
    * 重试只针对超时与 5xx，403 不重试。
    * 返回顺序与传入顺序一致。
    """
    if detectors is None:
        from .registry import detectors_for  # 延迟导入避免循环依赖

        detectors = detectors_for(ids)
    else:
        detectors = list(detectors)

    if not detectors:
        return []

    factory = client_factory or make_client_factory()
    workers = max(1, min(max_workers, len(detectors)))
    results: list[ProbeResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_detector, d, factory, timeout, retry) for d in detectors]
        for future in futures:
            results.append(future.result())
    return results
