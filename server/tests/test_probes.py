"""精细化平台探测器矩阵的单元测试。

全部用 ``httpx.MockTransport`` 注入假响应，不发真实网络请求。
覆盖三块：

* 框架：并发执行、超时隔离、失败隔离、重试策略、状态判定辅助；
* 平台：重点平台各有「正常路径 + 判定路径」用例，Netflix 覆盖
  「自制剧 / 全库 / 封锁 / 地区码」四种情形；
* 注册表：平台数量、分类齐全、id 唯一。
"""
import httpx

from app.services.probes import (
    ALL_DETECTORS,
    CATEGORY_NAMES,
    DETECTORS_BY_CATEGORY,
    Detector,
    ProbeResult,
    STATE_BLOCKED,
    STATE_ERROR,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
    STATE_REACHABLE,
    classify,
    detect_platforms,
    detector_by_id,
    platform_ids,
)
from app.services.probes.base import Markers


# ---------------------------------------------------------------- 辅助工具

def _factory(routes: dict, calls: list | None = None):
    """按 URL 返回假响应的客户端工厂。

    ``routes`` 的值可以是 ``httpx.Response``，也可以是接收 request 的可调用对象
    （用于模拟超时等异常）。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        item = routes.get(url)
        if item is None:
            return httpx.Response(404, text="mock: no route")
        if callable(item):
            return item(request)
        return item

    transport = httpx.MockTransport(handler)

    def factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)

    return factory


def _probe(detector, routes: dict, calls: list | None = None) -> ProbeResult:
    """跑单个探测器（绕开并发框架，便于逐条断言）。"""
    from app.services.probes.base import _run_detector

    return _run_detector(detector, _factory(routes, calls), 5.0, 0)


# ---------------------------------------------------------------- 框架

class _OkDetector(Detector):
    platform_id = "ok"
    display_name = "OK"
    category = "streaming"
    url = "https://ok.example/"

    def probe(self, client):
        resp = self.fetch(client, self.url)
        return ProbeResult(self.platform_id, STATE_UNLOCKED, resp.status)


class _BoomDetector(Detector):
    platform_id = "boom"
    display_name = "Boom"
    category = "streaming"
    url = "https://boom.example/"

    def probe(self, client):
        raise RuntimeError("探测器炸了")


class _TimeoutDetector(Detector):
    platform_id = "slow"
    display_name = "Slow"
    category = "streaming"
    url = "https://slow.example/"

    def probe(self, client):
        self.fetch(client, self.url)
        return ProbeResult(self.platform_id, STATE_UNLOCKED, 200)


class _FlakyDetector(Detector):
    """把 5xx 如实报成 error（框架据此决定要不要重试）。"""

    platform_id = "flaky"
    display_name = "Flaky"
    category = "streaming"
    url = "https://flaky.example/"

    def probe(self, client):
        resp = self.fetch(client, self.url)
        state = STATE_ERROR if resp.status >= 500 else STATE_UNLOCKED
        return ProbeResult(self.platform_id, state, resp.status)


def _timeout_route(request):
    raise httpx.ConnectTimeout("连接超时")


def test_detect_platforms_runs_concurrently_and_keeps_order():
    """并发执行 + 结果顺序与传入顺序一致。"""
    detectors = [_OkDetector(), _BoomDetector(), _TimeoutDetector()]
    results = detect_platforms(detectors=detectors,
                               client_factory=_factory({
                                   "https://ok.example/": httpx.Response(200),
                                   "https://slow.example/": _timeout_route,
                               }),
                               timeout=5.0, retry=0)
    assert [r.platform for r in results] == ["ok", "boom", "slow"]
    assert results[0].state == STATE_UNLOCKED
    # 失败隔离：炸掉的平台只影响自己
    assert results[1].state == STATE_ERROR
    assert "RuntimeError" in results[1].detail
    # 超时隔离：超时平台判 error，其它平台照常
    assert results[2].state == STATE_ERROR
    assert "超时" in results[2].detail


def test_detect_platforms_timeout_is_error_not_blocked():
    """超时属于网络层失败 → error，不能当成被地区拒绝。"""
    def _boom(request):
        raise httpx.ConnectTimeout("连接超时")

    results = detect_platforms(
        detectors=[_TimeoutDetector()],
        client_factory=_factory({"https://slow.example/": _boom}),
        timeout=1.0, retry=0)
    assert results[0].state == STATE_ERROR
    assert results[0].status is None
    assert "超时" in results[0].detail


def test_detect_platforms_retries_only_timeout_and_5xx():
    """重试只针对超时 / 5xx；403 不重试。"""
    calls: list = []
    routes = {"https://flaky.example/": httpx.Response(503, text="oops")}
    results = detect_platforms(detectors=[_FlakyDetector()],
                               client_factory=_factory(routes, calls),
                               timeout=1.0, retry=1)
    assert results[0].state == STATE_ERROR
    assert len(calls) == 2, "5xx 应重试一次"

    calls403: list = []

    class _Forbidden(_OkDetector):
        platform_id = "forbidden"
        url = "https://ok.example/"

        def probe(self, client):
            resp = self.fetch(client, self.url)
            return ProbeResult(self.platform_id, STATE_BLOCKED, resp.status)

    detect_platforms(detectors=[_Forbidden()],
                     client_factory=_factory({"https://ok.example/": httpx.Response(403)}, calls403),
                     timeout=1.0, retry=2)
    assert len(calls403) == 1, "403 不该重试"


def test_classify_cloudflare_challenge_is_unknown():
    """403 + Cloudflare 特征 → unknown（不是 blocked）。"""
    cls = classify(403, "Just a moment... challenge-platform verification",
                   Markers(block_requires_marker=False))
    assert cls.state == STATE_UNKNOWN
    assert "人机校验" in cls.detail


def test_classify_429_is_error():
    """429 是限流，不是地区问题 → error。"""
    assert classify(429, "Too Many Requests").state == STATE_ERROR


def test_classify_region_marker_is_blocked():
    """403 + 地区特征 → blocked。"""
    cls = classify(403, "Claude is not available in your region.",
                   Markers(region_markers=("not available in your region",)))
    assert cls.state == STATE_BLOCKED
    assert "地区限制" in cls.detail


def test_classify_2xx_without_ok_marker_stays_unlocked():
    """没有声明 ok_markers 时，2xx 即 unlocked。"""
    assert classify(200, "<html>ok</html>").state == STATE_UNLOCKED


def test_classify_2xx_missing_ok_marker_is_unknown():
    """声明了 ok_markers 却没命中 → unknown（宁可说拿不准）。"""
    cls = classify(200, "<html>hello</html>", Markers(ok_markers=("__never__",)))
    assert cls.state == STATE_UNKNOWN


def test_classify_without_response_is_error():
    assert classify(None, "").state == STATE_ERROR


def test_probe_result_to_dict():
    result = ProbeResult("netflix", STATE_UNLOCKED, 200, region="US",
                         detail="Netflix 全库可用", latency_ms=12,
                         extra={"full_library": True})
    data = result.to_dict()
    assert data["platform"] == "netflix"
    assert data["state"] == STATE_UNLOCKED
    assert data["status"] == 200
    assert data["region"] == "US"
    assert data["extra"]["full_library"] is True
    assert set(data) == {"platform", "state", "status", "region", "detail",
                         "latency_ms", "extra"}


# ---------------------------------------------------------------- Netflix

NETFLIX_TITLE = "https://www.netflix.com/title/81280792"
NETFLIX_ORIGINAL = "https://www.netflix.com/title/80057281"


def test_netflix_confirms_two_samples_but_not_playback():
    result = _probe(detector_by_id("netflix"), {
        NETFLIX_TITLE: httpx.Response(200, text='{"isAvailable":true,"isOriginal":false}'),
        NETFLIX_ORIGINAL: httpx.Response(200, text='{"isAvailable":true,"isOriginal":true,"countryCode":"US"}'),
    })
    assert result.state == STATE_UNLOCKED, result.detail
    assert result.extra["licensed_sample"] and result.extra["originals"]
    assert result.extra["playback"] == "unverified"
    assert result.region == "US"


def test_netflix_only_original_sample_confirmed():
    result = _probe(detector_by_id("netflix"), {
        NETFLIX_TITLE: httpx.Response(404),
        NETFLIX_ORIGINAL: httpx.Response(200, text='{"isAvailable":true,"isOriginal":true,"countryCode":"JP"}'),
    })
    assert result.state == STATE_UNLOCKED
    assert result.extra["originals"] and not result.extra["licensed_sample"]
    assert result.extra["catalog"] == "originals_sample"


def test_netflix_both_samples_report_restriction():
    result = _probe(detector_by_id("netflix"), {
        NETFLIX_TITLE: httpx.Response(403, text="Not Available in your country"),
        NETFLIX_ORIGINAL: httpx.Response(403, text="Not Available in your country"),
    })
    assert result.state == STATE_BLOCKED
    assert result.extra["catalog"] == "blocked"


def test_netflix_waf_header_is_unknown():
    result = _probe(detector_by_id("netflix"), {
        NETFLIX_TITLE: httpx.Response(403, headers={"cf-mitigated": "challenge"}),
    })
    assert result.state == STATE_UNKNOWN
    assert result.extra["reason"] == "challenge"


def test_netflix_homepage_without_catalog_evidence_is_unknown():
    result = _probe(detector_by_id("netflix"), {
        NETFLIX_TITLE: httpx.Response(200, text="<html>Netflix</html>"),
        NETFLIX_ORIGINAL: httpx.Response(200, text="<html>Netflix</html>"),
    })
    assert result.state == STATE_UNKNOWN
    assert result.extra["catalog"] == "unconfirmed"


# ---------------------------------------------------------------- Disney+

def test_disney_reachable_with_region():
    result = _probe(detector_by_id("disney"), {
        "https://www.disneyplus.com/": httpx.Response(200, text='{"countryCode":"US"}'),
    })
    assert result.state == STATE_REACHABLE, result.detail
    assert result.region == "US"


def test_disney_blocked_by_region_marker():
    result = _probe(detector_by_id("disney"), {
        "https://www.disneyplus.com/": httpx.Response(
            403, text="Sorry, this content is not available in your country"),
    })
    assert result.state == STATE_BLOCKED, result.detail


# ---------------------------------------------------------------- HBO Max

def test_max_reachable():
    result = _probe(detector_by_id("hbo"), {
        "https://play.max.com/": httpx.Response(200, text='{"countryCode":"US"}'),
    })
    assert result.state == STATE_REACHABLE, result.detail
    assert result.region == "US"
    assert result.extra["main_site"] == "ok"


def test_max_blocked_by_region():
    result = _probe(detector_by_id("hbo"), {
        "https://play.max.com/": httpx.Response(403, text="This title is not available in your region"),
    })
    assert result.state == STATE_BLOCKED, result.detail


def test_max_waf_is_unknown():
    """403 带 Cloudflare 特征 → 风控拦截，unknown 而不是 blocked。"""
    result = _probe(detector_by_id("hbo"), {
        "https://play.max.com/": httpx.Response(403, text="Just a moment... cf-chl"),
    })
    assert result.state == STATE_UNKNOWN, result.detail
    assert result.extra["risk_control"] is True


def test_max_bare_403_is_unknown():
    """没有地区特征也没有风控特征的 403 → 无法判定，unknown。"""
    result = _probe(detector_by_id("hbo"), {
        "https://play.max.com/": httpx.Response(403, text=""),
    })
    assert result.state == STATE_UNKNOWN, result.detail


# ---------------------------------------------------------------- YouTube Premium

def test_youtube_premium_reachable_with_region():
    result = _probe(detector_by_id("youtube_premium"), {
        "https://www.youtube.com/premium": httpx.Response(200, text='{"countryCode":"US"}'),
    })
    assert result.state == STATE_REACHABLE, result.detail
    assert result.region == "US"
    # 页面只给了一次 countryCode：不能确认 Premium 是否在该地区上架
    assert result.extra["premium_region_confirmed"] is False
    assert "未能确认" in result.detail


def test_youtube_premium_requires_explicit_eligibility():
    endpoint = "https://www.youtube.com/premium"
    duplicated_region = '{"countryCode":"US"},{"countryCode":"US"}'
    result = _probe(detector_by_id("youtube_premium"), {
        endpoint: httpx.Response(200, text=duplicated_region),
    })
    assert result.state == STATE_REACHABLE
    assert result.extra["premium_region_confirmed"] is False
    result = _probe(detector_by_id("youtube_premium"), {
        endpoint: httpx.Response(200, text='{"countryCode":"US","isPremiumAvailableCountry":true}'),
    })
    assert result.state == STATE_UNLOCKED
    assert result.extra["premium_region_confirmed"] is True



def test_youtube_premium_blocked():
    result = _probe(detector_by_id("youtube_premium"), {
        "https://www.youtube.com/premium": httpx.Response(
            403, text="Premium is not available in your country"),
    })
    assert result.state == STATE_BLOCKED, result.detail


# ---------------------------------------------------------------- TikTok

def test_tiktok_reachable_with_region():
    result = _probe(detector_by_id("tiktok"), {
        "https://www.tiktok.com/": httpx.Response(200, text='{"region":"US","countryCode":"US"}'),
    })
    assert result.state == STATE_REACHABLE, result.detail
    assert result.region == "US"
    # 直播 / 创作者限制：无头请求拿不到 → unknown 并写明原因
    assert result.extra["live_status"] == "unknown"
    assert result.extra["creator_status"] == "unknown"


def test_tiktok_bare_403_is_unknown():
    result = _probe(detector_by_id("tiktok"), {
        "https://www.tiktok.com/": httpx.Response(403, text=""),
    })
    assert result.state == STATE_UNKNOWN, result.detail


# ---------------------------------------------------------------- Spotify

def test_spotify_reachable_with_region():
    result = _probe(detector_by_id("spotify"), {
        "https://www.spotify.com/": httpx.Response(200, text='{"country":"SE"}'),
    })
    assert result.state == STATE_REACHABLE, result.detail
    assert result.region == "SE"
    assert result.extra["account_ip_match"] == "unknown"


def test_spotify_region_restricted():
    result = _probe(detector_by_id("spotify"), {
        "https://www.spotify.com/": httpx.Response(
            403, text="Spotify is not available in your country"),
    })
    assert result.state == STATE_BLOCKED, result.detail


# ---------------------------------------------------------------- ChatGPT

def test_chatgpt_reachable():
    result = _probe(detector_by_id("chatgpt"), {
        "https://chatgpt.com/": httpx.Response(200, text="<html>chatgpt</html>"),
    })
    assert result.state == STATE_REACHABLE, result.detail


def test_chatgpt_region_blocked():
    result = _probe(detector_by_id("chatgpt"), {
        "https://chatgpt.com/": httpx.Response(
            403, text='{"error":"unsupported_country"}'),
    })
    assert result.state == STATE_BLOCKED, result.detail


def test_chatgpt_waf_is_unknown_not_blocked():
    """Cloudflare 挑战 → unknown（不是 blocked）。"""
    result = _probe(detector_by_id("chatgpt"), {
        "https://chatgpt.com/": httpx.Response(
            403, text="Just a moment... cf-chl challenge-platform"),
    })
    assert result.state == STATE_UNKNOWN, result.detail
    assert result.state != STATE_BLOCKED


def test_chatgpt_bare_403_is_unknown():
    """403 但没有任何地区特征 → 无法区分地区拒绝与 WAF → unknown。"""
    result = _probe(detector_by_id("chatgpt"), {
        "https://chatgpt.com/": httpx.Response(403, text=""),
    })
    assert result.state == STATE_UNKNOWN, result.detail


def test_chatgpt_network_failure_is_error():
    def _boom(request):
        raise httpx.ConnectError("连不上")

    result = _probe(detector_by_id("chatgpt"), {"https://chatgpt.com/": _boom})
    assert result.state == STATE_ERROR, result.detail
    assert result.status is None


# ---------------------------------------------------------------- Claude

def test_claude_reachable():
    result = _probe(detector_by_id("claude"), {
        "https://claude.ai/": httpx.Response(200, text="<html>claude</html>"),
    })
    assert result.state == STATE_REACHABLE, result.detail


def test_claude_region_blocked():
    result = _probe(detector_by_id("claude"), {
        "https://claude.ai/": httpx.Response(403, text="Claude is not available in your region"),
    })
    assert result.state == STATE_BLOCKED, result.detail


# ---------------------------------------------------------------- Prime Video

def test_primevideo_reachable():
    result = _probe(detector_by_id("primevideo"), {
        "https://www.primevideo.com/": httpx.Response(200, text='{"countryCode":"US"}'),
    })
    assert result.state == STATE_REACHABLE, result.detail
    assert result.region == "US"
    assert result.extra["catalog"] == "unknown"


def test_primevideo_bare_403_is_unknown():
    """Prime Video 的 403 既可能是地区限制也可能是 WAF → unknown。"""
    result = _probe(detector_by_id("primevideo"), {
        "https://www.primevideo.com/": httpx.Response(403, text=""),
    })
    assert result.state == STATE_UNKNOWN, result.detail


# ---------------------------------------------------------------- Reddit

def test_reddit_reachable():
    result = _probe(detector_by_id("reddit"), {
        "https://www.reddit.com/": httpx.Response(200, text="<html>reddit</html>"),
    })
    assert result.state == STATE_REACHABLE, result.detail
    assert result.extra["ip_blocked"] is False


def test_reddit_ip_blocked():
    result = _probe(detector_by_id("reddit"), {
        "https://www.reddit.com/": httpx.Response(
            403, text="Whoa there, pardner! You've been blocked."),
    })
    assert result.state == STATE_BLOCKED, result.detail
    assert result.extra["ip_blocked"] is True


def test_reddit_captcha_wall_is_unknown():
    result = _probe(detector_by_id("reddit"), {
        "https://www.reddit.com/": httpx.Response(200, text="Please verify you are human"),
    })
    assert result.state == STATE_UNKNOWN, result.detail
    assert result.extra["captcha_wall"] is True


# ---------------------------------------------------------------- 注册表

def test_registry_has_enough_streaming_platforms():
    streaming = platform_ids("streaming")
    assert len(streaming) >= 20, streaming
    required = ["netflix", "disney", "youtube_premium", "spotify", "hbo", "primevideo",
                "hulu", "paramountplus", "peacock", "appletv", "abema", "tver", "nhkplus",
                "bahamut", "dazn", "crunchyroll", "viu", "dmm", "iqiyi", "wetv",
                "discoveryplus"]
    missing = [i for i in required if i not in streaming]
    assert not missing, missing


def test_registry_has_ai_platforms():
    ai = platform_ids("ai")
    required = ["chatgpt", "claude", "gemini", "google_ai", "perplexity", "grok"]
    missing = [i for i in required if i not in ai]
    assert not missing, missing


def test_registry_ids_are_unique():
    ids = platform_ids()
    assert len(ids) == len(set(ids))
    assert len(ids) == len(ALL_DETECTORS)


def test_twitch_and_iplayer_homepages_do_not_prove_playback():
    from app.services.routing_planner import verified_service_ids

    for pid in ("twitch", "bbc"):
        detector = ALL_DETECTORS[pid]
        result = _probe(detector, {detector.url: httpx.Response(200, text='{"locale":"en-GB"}')})
        assert (result.state, result.region) == (STATE_REACHABLE, "")
        row = {"qualified": True, "checked_at": 100, "probes": {pid: result.to_dict()}}
        assert not verified_service_ids(row, earliest=90, latest=110)

    bbc = ALL_DETECTORS["bbc"]
    denied = _probe(bbc, {bbc.url: httpx.Response(403, text="BBC iPlayer only works in the UK.")})
    assert denied.state == STATE_BLOCKED


def test_registry_entries_are_well_formed():
    for platform_id, detector in ALL_DETECTORS.items():
        assert detector.platform_id == platform_id
        assert detector.display_name
        assert detector.category in CATEGORY_NAMES, detector.category
        assert detector.url.startswith("https://"), detector.url
        assert detector_by_id(platform_id) is detector
    for category, detectors in DETECTORS_BY_CATEGORY.items():
        assert category in CATEGORY_NAMES
        assert detectors, category


def test_registry_ignores_unknown_ids():
    from app.services.probes.registry import detectors_for

    picked = detectors_for(["netflix", "不存在"])
    assert [d.platform_id for d in picked] == ["netflix"]
    assert len(detectors_for(None)) == len(ALL_DETECTORS)


def test_probes_package_does_not_import_unlock_check():
    """探测器包不能 import unlock_check（避免循环依赖与互相牵连）。"""
    import pathlib
    import re

    import app.services.probes as pkg

    root = pathlib.Path(pkg.__file__).parent
    pattern = re.compile(r"^\s*(?:from\s+[.\w]*\s*import\s+.*unlock_check"
                         r"|import\s+.*unlock_check)", re.MULTILINE)
    for path in root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not pattern.search(source), path.name


def test_404_does_not_prove_service_unsupported():
    """页面不存在不足以证明服务不支持。"""
    result = _probe(detector_by_id("wikipedia"), {
        "https://zh.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json":
            httpx.Response(404, text=""),
    })
    assert result.state == STATE_UNKNOWN, result.detail
