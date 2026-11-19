"""平台探测器矩阵（精细化解锁判定）。

这个包解决什么问题：把「某个节点能不能用某平台」从「200/403 二分」升级成
**每个平台一套判定规则 + 结构化结论**（状态、地区码、平台特有信息）。

典型用法::

    from app.services.probes import detect_platforms, make_client_factory

    results = detect_platforms(["netflix", "chatgpt"],
                               make_client_factory(proxy="http://127.0.0.1:7890"))
    for r in results:
        print(r.to_dict())

框架能力：

* 并发执行、失败隔离（一个平台异常不影响其它平台）；
* 每请求超时控制；
* 重试策略：只对超时与 5xx 重试，403 不重试（重试只会加重风控）。

状态语义见 ``base.py`` 的模块说明：``unlocked`` / ``blocked`` / ``unknown`` /
``error`` / ``unsupported`` / ``reachable``。
"""
from .base import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_RETRY,
    DEFAULT_TIMEOUT,
    MAX_BODY_CHARS,
    STATE_BLOCKED,
    STATE_ERROR,
    STATE_REACHABLE,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
    STATE_UNSUPPORTED,
    USER_AGENT,
    VALID_STATES,
    Classification,
    Detector,
    Markers,
    ProbeResponse,
    ProbeResult,
    classify,
    detect_platforms,
    make_client_factory,
)
from .registry import (
    ALL_DETECTORS,
    CATEGORY_NAMES,
    DETECTORS_BY_CATEGORY,
    detector_by_id,
    detectors_for,
    platform_ids,
)

__all__ = [
    "ALL_DETECTORS",
    "CATEGORY_NAMES",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_RETRY",
    "DEFAULT_TIMEOUT",
    "DETECTORS_BY_CATEGORY",
    "Classification",
    "Detector",
    "Markers",
    "MAX_BODY_CHARS",
    "ProbeResponse",
    "ProbeResult",
    "STATE_BLOCKED",
    "STATE_ERROR",
    "STATE_REACHABLE",
    "STATE_UNKNOWN",
    "STATE_UNLOCKED",
    "STATE_UNSUPPORTED",
    "USER_AGENT",
    "VALID_STATES",
    "classify",
    "detect_platforms",
    "detector_by_id",
    "detectors_for",
    "make_client_factory",
    "platform_ids",
]
