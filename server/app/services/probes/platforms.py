"""各平台的精细化探测器。

一个平台一个类，继承 ``probes.base.Detector``。每个类的 docstring 写清
**判定规则与理由**，代码只负责把规则实现出来。

设计原则（与旧的一刀切实现最大的区别）：

* **拿不准就说拿不准**：人机校验、风控页、无特征 403 一律 ``unknown``，
  绝不臆断成「被地区拒绝」——猜错的代价是节点能力徽章错标。
* **状态之外再给结构化信息**：地区码放在 ``region``，平台特有结论放在
  ``extra``（如 Netflix 的 ``originals`` / ``licensed_sample``）。
* **只用正文里真实存在的特征**做判定，不臆造页面结构；页面结构变了就
  降级成 ``unknown`` 并在 ``detail`` 里说明。
"""
import json
import re
from urllib.parse import urlsplit

import httpx

from .base import (
    STATE_BLOCKED,
    STATE_ERROR,
    STATE_REACHABLE,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
    Detector,
    Markers,
    ProbeResponse,
    ProbeResult,
    classify_page,
)

# 地区码的通用提取模式：按可靠度排序（countryCode 语义最明确）。
REGION_PATTERNS = (
    r'"countryCode"\s*:\s*"([A-Za-z]{2})"',
    r'"country"\s*:\s*"([A-Za-z]{2})"',
    r'"countryIso"\s*:\s*"([A-Za-z]{2})"',
    r'"isoCode"\s*:\s*"([A-Za-z]{2})"',
    r'"country_id"\s*:\s*"([A-Za-z]{2})"',
    r'"region"\s*:\s*"([A-Za-z]{2})"',
    r'"locale"\s*:\s*"[a-z]{2}[-_]([A-Za-z]{2})"',
)

# AI 类站点通用的地区拒绝措辞（403 正文里出现即判 blocked）。
AI_REGION_MARKERS = (
    "unsupported_country",
    "unsupported country",
    "not available in your country",
    "not available in your region",
    "unavailable in your region",
    "country, region, or territory not supported",
    "无法在您所在地区使用",
    "在您所在的国家或地区不可用",
)


def _json_flag(text: str, name: str) -> bool | None:
    """读页面内嵌 JSON 里的布尔标记（如 ``"isAvailable":true``）。

    读不到返回 None（页面结构变了 / 没有这个字段），由调用方决定怎么降级。
    """
    match = re.search(rf'"{re.escape(name)}"\s*:\s*(true|false)', text or "", re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower() == "true"


def _has(text: str, markers: tuple[str, ...]) -> str:
    """返回第一个命中的特征名（没命中返回空串）。"""
    for marker in markers:
        if marker.lower() in (text or "").lower():
            return marker
    return ""


class _WebDetector(Detector):
    """通用网页型平台：一次 GET + 状态码 / 正文特征判定。

    子类只声明差异（``markers``、地区码模式、附加信息），规则写在子类 docstring。
    """

    markers: Markers = Markers()
    region_patterns: tuple[str, ...] | None = None
    detail_unlocked: str = ""
    detail_blocked: str = ""

    def build_extra(self, resp: ProbeResponse) -> dict:
        """平台特有信息（默认没有）。"""
        return {}

    def probe(self, client: httpx.Client) -> ProbeResult:
        resp = self.fetch(client, self.url)
        cls = classify_page(resp, self.markers)
        region = self.extract_region(resp.text, self.region_patterns)
        extra = {**self.build_extra(resp), "reason": cls.reason}
        if extra.get("ip_blocked") and cls.reason != "challenge":
            cls.state, cls.detail = STATE_BLOCKED, "服务明确拦截了该出口 IP"
            extra["reason"] = "ip_block"
        return ProbeResult(self.platform_id, cls.state, resp.status, region=region,
                           detail=cls.detail, extra=extra)


# =============================================================== 流媒体 · Netflix


class NetflixDetector(Detector):
    """分别检查自制剧和外部版权样本。样本通过也不等同于播放成功。"""

    platform_id = "netflix"
    display_name = "Netflix"
    category = "streaming"
    title_url = "https://www.netflix.com/title/81280792"
    original_url = "https://www.netflix.com/title/80057281"
    url = title_url
    timeout = 14.0
    body_limit = 1_500_000
    markers = Markers(region_markers=(r"you seem to be using a vpn or proxy",))

    @staticmethod
    def sample(resp: ProbeResponse, url: str) -> tuple[bool | None, bool | None, str]:
        """只读目标片名的公开目录对象；语言或其它影片的标记不作证据。"""
        title_id = int(url.rsplit("/", 1)[-1])
        final = urlsplit(resp.url)
        match = re.fullmatch(r"(?:/([a-z]{2})(?:-[a-z]{2})?)?/title/(\d+)/?", final.path)
        if final.scheme != "https" or final.hostname != "www.netflix.com" or not match or int(match[2]) != title_id:
            return None, None, ""
        matches = set()
        decoder = json.JSONDecoder()
        # Netflix 的内嵌对象使用 JS 的十六进制转义；转成 JSON 转义后纯解析，不执行脚本。
        text = re.sub(r"\\(?:x([a-fA-F0-9]{2})|[^\r\n])",
                      lambda m: r"\u00" + m[1] if m[1] else m[0], resp.text)
        for marker in re.finditer(r'"metaData"\s*:\s*(?=\{)', text):
            try:
                item, _ = decoder.raw_decode(text, marker.end())
            except (ValueError, RecursionError):
                continue
            if (item.get("videoId") == title_id and item.get("topLevelVideoId") == title_id
                    and type(item.get("isAvailable")) is bool and type(item.get("isOriginal")) is bool):
                matches.add((item["isAvailable"], item["isOriginal"]))
        if len(matches) != 1:
            return None, None, ""
        available, original = matches.pop()
        # /title/... 没有地区信息，不能自行推断是美国。
        return available, original, (match[1] or "").upper()

    def probe(self, client: httpx.Client) -> ProbeResult:
        title = self.fetch(client, self.title_url)
        title_status = classify_page(title, self.markers)
        if title_status.reason in {"challenge", "rate_limit", "upstream"}:
            return ProbeResult(self.platform_id, title_status.state, title.status,
                               detail=title_status.detail, extra={"reason": title_status.reason})
        original = self.fetch(client, self.original_url)
        original_status = classify_page(original, self.markers)
        title_available, title_is_original, title_region = self.sample(title, self.title_url)
        original_available, original_is_original, original_region = self.sample(original, self.original_url)
        has_original = (original_status.state == STATE_REACHABLE
                        and original_available is True and original_is_original is True)
        has_licensed = (title_status.state == STATE_REACHABLE
                        and title_available is True and title_is_original is False)
        region = (title_region if title_region == original_region else "") if has_licensed else original_region
        limited = (title_status.state == STATE_BLOCKED or
                   (title_status.state == STATE_REACHABLE and title_available is False))
        extra = {"originals": has_original, "licensed_sample": has_licensed,
                 "catalog": "unconfirmed", "playback": "unverified"}
        if has_original and has_licensed:
            extra["catalog"] = "licensed_sample"
            return ProbeResult(self.platform_id, STATE_UNLOCKED, title.status, region,
                               "自制剧和非自制剧样本均可见，未验证播放", extra=extra)
        if has_original:
            extra["catalog"] = "originals_sample"
            return ProbeResult(self.platform_id, STATE_UNLOCKED, original.status, region,
                               "自制剧样本可见；非自制剧样本受限" if limited
                               else "自制剧样本可见；非自制剧未确认", extra=extra)
        if title_status.state == original_status.state == STATE_BLOCKED:
            extra.update(catalog="blocked", reason="region")
            return ProbeResult(self.platform_id, STATE_BLOCKED, original.status, region,
                               "两个样本均返回限制", extra=extra)
        if original_status.reason in {"challenge", "rate_limit", "upstream"}:
            extra["reason"] = original_status.reason
            return ProbeResult(self.platform_id, original_status.state, original.status, region,
                               original_status.detail, extra=extra)
        return ProbeResult(self.platform_id, STATE_UNKNOWN, title.status, region,
                           "未取得足够的目录证据", extra=extra)


# =============================================================== 流媒体 · Disney+


class DisneyPlusDetector(_WebDetector):
    """Disney+：读取网页证据和地区码；不推断播放权限。"""

    platform_id = "disney"
    display_name = "Disney+"
    category = "streaming"
    body_limit = 1_200_000
    url = "https://www.disneyplus.com/"

    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        region_markers=("not available in your country", "not available in your region",
                        "isn't available in your country", "unavailable in your region",
                        "该国家或地区不可用"),
        block_requires_marker=False,
    )


# =============================================================== 流媒体 · HBO Max


class MaxDetector(_WebDetector):
    """HBO Max：分别记录主站响应、地区限制与风控。"""

    platform_id = "hbo"
    display_name = "HBO Max"
    category = "streaming"
    body_limit = 1_200_000
    url = "https://play.max.com/"

    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        region_markers=("not available in your region", "not available in your country",
                        "isn't available in your region", "unavailable in your region",
                        "该国家或地区不可用"),
        challenge_markers=("access denied", "are you a robot", "verify you are human"),
        block_requires_marker=True,
    )

    def build_extra(self, resp: ProbeResponse) -> dict:
        challenge = _has(resp.text, ("just a moment", "attention required", "cf-chl",
                                     "challenge-platform"))
        return {
            "main_site": "ok" if resp.status == 200 else ("blocked" if resp.status == 403 else "unknown"),
            "risk_control": True if challenge else (False if resp.status == 200 else None),
        }


# =============================================================== 流媒体 · YouTube Premium


class YouTubePremiumDetector(_WebDetector):
    """YouTube Premium：只用明确的地区可用字段，账号权益另计。"""

    platform_id = "youtube_premium"
    display_name = "YouTube Premium"
    category = "streaming"
    # countryCode 在页面尾部（~1MB 处），60KB 默认上限取不到
    body_limit = 2_000_000
    url = "https://www.youtube.com/premium"

    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        region_markers=("premium is not available in your country",
                        "isn't available in your country",
                        "not available in your country",
                        "not available in your region",
                        "unavailable in your country"),
        block_requires_marker=False,
    )

    def probe(self, client: httpx.Client) -> ProbeResult:
        resp = self.fetch(client, self.url)
        cls = classify_page(resp, self.markers)
        region = self.extract_region(resp.text)
        confirmed = cls.state == STATE_REACHABLE and self._premium_confirmed(resp.text, region)
        extra = {"premium_region_confirmed": confirmed, "playback": "unverified", "reason": cls.reason}
        detail = cls.detail
        if cls.state == STATE_REACHABLE:
            if region and confirmed:
                detail = f"页面显示 {region} 支持 Premium；未验证账号权益或免广告"
            elif region:
                detail = (f"出口地区 {region}；Premium 是否在该地区上架未能确认"
                          "（页面未给出明确的地区支持标记）")
            else:
                detail = "可访问，但未能识别地区码"
        return ProbeResult(self.platform_id, STATE_UNLOCKED if confirmed else cls.state,
                           resp.status, region=region, detail=detail, extra=extra)

    @staticmethod
    def _premium_confirmed(body: str, region: str) -> bool:
        return bool(region and _json_flag(body, "isPremiumAvailableCountry") is True)


# =============================================================== 流媒体 · TikTok


class TikTokDetector(_WebDetector):
    """TikTok：记录访问、出口地区和可识别的限制。"""

    platform_id = "tiktok"
    display_name = "TikTok"
    category = "streaming"
    body_limit = 1_200_000
    url = "https://www.tiktok.com/"

    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        region_markers=("not available in your region", "not available in your country",
                        "this service isn't available in your country",
                        "该国家或地区不可用"),
        block_requires_marker=False,
    )

    live_markers = ("livestream is not available", "live is not available",
                    "直播间不可用", "直播不可用", "this live has ended")
    creator_markers = ("account restricted", "your account has been restricted",
                       "账号受限", "已被限制")

    def build_extra(self, resp: ProbeResponse) -> dict:
        live_hit = _has(resp.text, self.live_markers)
        creator_hit = _has(resp.text, self.creator_markers)
        return {
            "live_status": "restricted" if live_hit else "unknown",
            "creator_status": "restricted" if creator_hit else "unknown",
            "live_note": "" if live_hit else "无头请求无法确认直播可用性（需要具体直播间地址）",
            "creator_note": "" if creator_hit else "无头请求无法确认创作者功能（需要登录态）",
        }

    def probe(self, client: httpx.Client) -> ProbeResult:
        resp = self.fetch(client, self.url)
        cls = classify_page(resp, self.markers)
        region = self.extract_region(resp.text)
        extra = {**self.build_extra(resp), "reason": cls.reason, "playback": "unverified"}
        detail = cls.detail
        if cls.state == STATE_REACHABLE:
            detail = "可访问；直播与创作者限制未能确认" if not region else "可访问"
        return ProbeResult(self.platform_id, cls.state, resp.status, region=region,
                           detail=detail, extra=extra)


# =============================================================== 流媒体 · Spotify


class SpotifyDetector(_WebDetector):
    """Spotify：检查地区限制和页面明确返回的账号提示。"""

    platform_id = "spotify"
    display_name = "Spotify"
    category = "streaming"
    body_limit = 1_200_000
    url = "https://www.spotify.com/"

    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        region_markers=("not available in your country", "not available in your region",
                        "isn't available in your country", "this service is not available",
                        "该国家或地区不可用"),
        block_requires_marker=False,
    )

    def build_extra(self, resp: ProbeResponse) -> dict:
        return {
            "account_ip_match": "unknown",
            "account_ip_note": "账号与出口 IP 一致性需登录态才能验证，无头请求未判定",
        }


# =============================================================== 流媒体 · Prime Video


class AmazonPrimeVideoDetector(_WebDetector):
    """Amazon Prime Video：主站可达、区域归属、是否仅部分片源。

    判定规则：

    1. 200 → unlocked；region 优先取正文里的 ``"countryCode"`` / ``"country"``。
    2. 403 且含地区措辞 → blocked；纯 403 → unknown：Prime Video 的 403
       既可能是地区限制也可能是 WAF 拦截，无头请求分不出来。
    3. 「是否仅部分片源」需要逐片核对目录，无头请求做不到，
       固定填 ``catalog="unknown"``，detail 里写明复核方式（客户端内逐片试播）。
    """

    platform_id = "primevideo"
    display_name = "Amazon Prime Video"
    category = "streaming"
    url = "https://www.primevideo.com/"

    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        region_markers=("not available in your country", "not available in your region",
                        "unavailable in your country", "该国家或地区不可用"),
        block_requires_marker=True,
    )

    def build_extra(self, resp: ProbeResponse) -> dict:
        return {
            "catalog": "unknown",
            "catalog_note": "片源完整性需逐片核对（客户端内试播），无头请求未判定",
        }

    def probe(self, client: httpx.Client) -> ProbeResult:
        resp = self.fetch(client, self.url)
        cls = classify_page(resp, self.markers)
        region = self.extract_region(resp.text)
        extra = {**self.build_extra(resp), "reason": cls.reason, "playback": "unverified"}
        detail = cls.detail
        if cls.state == STATE_REACHABLE:
            detail = ("主站可达" + (f"，区域 {region}" if region else "，未能识别区域归属"))
            detail += "；片源完整性未判定"
        return ProbeResult(self.platform_id, cls.state, resp.status, region=region,
                           detail=detail, extra=extra)


# =============================================================== 流媒体 · Reddit


class RedditDetector(_WebDetector):
    """Reddit：区分网页响应、已知出口拦截与人机校验。"""

    platform_id = "reddit"
    display_name = "Reddit"
    category = "social_other"
    url = "https://www.reddit.com/"

    ip_markers = ("blocked by network security", "your network has been blocked",
                  "you\'ve been blocked", "you have been blocked")
    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        challenge_markers=("captcha", "verify you are human", "are you a robot",
                           "press and hold"),
        block_requires_marker=False,
    )

    def build_extra(self, resp: ProbeResponse) -> dict:
        blocked = resp.status == 403 and _has(resp.text, self.ip_markers)
        captcha = _has(resp.text, self.markers.challenge_markers)
        return {
            "ip_blocked": bool(blocked),
            "captcha_wall": bool(captcha),
        }


# =============================================================== 流媒体 · 通用站点

class HuluDetector(_WebDetector):
    """Hulu：美国限定。403 为未上线地区的典型响应；正文含地区措辞时更明确。"""

    platform_id = "hulu"
    display_name = "Hulu"
    category = "streaming"
    url = "https://www.hulu.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your country", "not available in your region",
                                       "isn't available in your", "该国家或地区不可用"))
    detail_blocked = "Hulu 在该出口不可用（美国限定）"


class ParamountPlusDetector(_WebDetector):
    """Paramount+：美国限定。"""

    platform_id = "paramountplus"
    display_name = "Paramount+"
    category = "streaming"
    url = "https://www.paramountplus.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your country", "not available in your region",
                                       "isn't available in your", "该国家或地区不可用"))
    detail_blocked = "Paramount+ 在该出口不可用（美国限定）"


class PeacockDetector(_WebDetector):
    """Peacock：美国限定。"""

    platform_id = "peacock"
    display_name = "Peacock"
    category = "streaming"
    url = "https://www.peacocktv.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your country", "not available in your region",
                                       "isn't available in your", "该国家或地区不可用"))
    detail_blocked = "Peacock 在该出口不可用（美国限定）"


class AppleTVPlusDetector(_WebDetector):
    """Apple TV+：主站可达性 + 商店区线索。

    说明：Apple TV+ 的可播目录由**账号 / 商店区**决定，出口 IP 只作参考，
    因此地区码仅从页面里的 ``countryCode`` 线索读取，读不到就留空。
    """

    platform_id = "appletv"
    display_name = "Apple TV+"
    category = "streaming"
    url = "https://tv.apple.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your country", "not available in your region",
                                       "isn't available in your", "该国家或地区不可用"))
    detail_blocked = "Apple TV+ 在该出口不可用"

    def build_extra(self, resp: ProbeResponse) -> dict:
        return {"storefront_note": "目录由账号 / 商店区决定，出口 IP 仅供参考"}


class AbemaTVDetector(_WebDetector):
    """AbemaTV：日本限定。海外访问返回 403 或日文提示页。"""

    platform_id = "abema"
    display_name = "AbemaTV"
    category = "streaming"
    url = "https://abema.tv/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("海外", "視聴できません", "not available in your country",
                                       "not available in your region", "this service is not available"))
    detail_blocked = "AbemaTV 在该出口不可用（日本限定）"


class TVerDetector(_WebDetector):
    """TVer：日本限定。"""

    platform_id = "tver"
    display_name = "TVer"
    category = "streaming"
    url = "https://tver.jp/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("日本以外", "地域外", "not available in your country",
                                       "not available in your region", "this service is not available"))
    detail_blocked = "TVer 在该出口不可用（日本限定）"


class NHKPlusDetector(_WebDetector):
    """NHK+：日本限定。"""

    platform_id = "nhkplus"
    display_name = "NHK+"
    category = "streaming"
    url = "https://www.nhkplus.jp/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("日本以外", "海外", "地域外", "not available in your country",
                                       "not available in your region", "this service is not available"))
    detail_blocked = "NHK+ 在该出口不可用（日本限定）"


class BahamutDetector(_WebDetector):
    """动画疯（Bahamut）：台湾限定。"""

    platform_id = "bahamut"
    display_name = "动画疯"
    category = "streaming"
    url = "https://ani.bahamut.com.tw/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("台灣", "台湾", "僅限", "仅限", "not available in your region",
                                       "not available in your country"))
    detail_blocked = "动画疯在该出口不可用（台湾限定）"


class DAZNDetector(_WebDetector):
    """DAZN：按订阅地区开放，境外可能落到落地页。"""

    platform_id = "dazn"
    display_name = "DAZN"
    category = "streaming"
    url = "https://www.dazn.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your country", "not available in your region",
                                       "isn't available in your", "该国家或地区不可用"))
    detail_blocked = "DAZN 在该出口不可用"


class CrunchyrollDetector(_WebDetector):
    """Crunchyroll：部分内容按地区限制。"""

    platform_id = "crunchyroll"
    display_name = "Crunchyroll"
    category = "streaming"
    url = "https://www.crunchyroll.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your region", "not available in your country",
                                       "isn't available in your", "该国家或地区不可用"))
    detail_blocked = "Crunchyroll 在该出口不可用"


class ViuDetector(_WebDetector):
    """Viu：按地区开放，境外会跳到「本服务在你所在位置不可用」。"""

    platform_id = "viu"
    display_name = "Viu"
    category = "streaming"
    url = "https://www.viu.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("service not available in your location",
                                       "not available in your country", "not available in your region",
                                       "该国家或地区不可用"))
    detail_blocked = "Viu 在该出口不可用"


class DMMDetector(_WebDetector):
    """DMM（DMM TV / FANZA）：日本限定，日文提示页含「海外」字样。"""

    platform_id = "dmm"
    display_name = "DMM"
    category = "streaming"
    url = "https://www.dmm.co.jp/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("日本以外", "海外", "not available in your country",
                                       "not available in your region", "this service is not available"))
    detail_blocked = "DMM 在该出口不可用（日本限定）"


class IQIYIDetector(_WebDetector):
    """爱奇艺国际版（iQIYI）：部分内容按地区限制。"""

    platform_id = "iqiyi"
    display_name = "爱奇艺国际版"
    category = "streaming"
    url = "https://www.iqiyi.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your region", "not available in your country",
                                       "this content isn't available", "该内容在您所在地区不可用"))
    detail_blocked = "爱奇艺国际版在该出口不可用"


class WeTVDetector(_WebDetector):
    """WeTV（腾讯视频国际版）：部分内容按地区限制。"""

    platform_id = "wetv"
    display_name = "WeTV"
    category = "streaming"
    url = "https://www.wetv.vip/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your region", "not available in your country",
                                       "isn't available in your region", "该内容在您所在地区不可用"))
    detail_blocked = "WeTV 在该出口不可用"


class DiscoveryPlusDetector(_WebDetector):
    """Discovery+：美国限定（含部分国际版本）。"""

    platform_id = "discoveryplus"
    display_name = "Discovery+"
    category = "streaming"
    url = "https://www.discoveryplus.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your country", "not available in your region",
                                       "this service is not available in your location",
                                       "该国家或地区不可用"))
    detail_blocked = "Discovery+ 在该出口不可用"


class BilibiliIntlDetector(_WebDetector):
    """哔哩哔哩国际版（bilibili.tv）：部分内容按地区限制。"""

    platform_id = "bilibili_intl"
    display_name = "哔哩哔哩国际版"
    category = "streaming"
    url = "https://www.bilibili.tv/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your region", "not available in your country",
                                       "isn't available in your region", "该国家或地区不可用"))
    detail_blocked = "哔哩哔哩国际版在该出口不可用"


class TwitchDetector(_WebDetector):
    """检查 Twitch 网页响应；直播和点播均需播放器确认。"""

    platform_id = "twitch"
    display_name = "Twitch"
    category = "streaming"
    url = "https://www.twitch.tv/"
    markers = Markers(block_requires_marker=True)

    def build_extra(self, _resp: ProbeResponse) -> dict:
        return {"playback": "unverified"}

    def extract_region(self, *_args) -> str:
        return ""


class BBCDetector(_WebDetector):
    """检查 BBC iPlayer 入口；BBC 新闻页可访问不代表 iPlayer 能播放。"""

    platform_id = "bbc"
    display_name = "BBC iPlayer"
    category = "streaming"
    url = "https://www.bbc.co.uk/iplayer"
    markers = Markers(
        block_requires_marker=True,
        region_markers=("bbc iplayer only works in the uk",
                        "bbc iplayer is only available in the uk",
                        "bbc iplayer is not available outside the uk"),
    )

    def build_extra(self, _resp: ProbeResponse) -> dict:
        return {"playback": "unverified"}

    def extract_region(self, *_args) -> str:
        return ""


class TVBAnywhereDetector(_WebDetector):
    """TVBAnywhere：香港地区服务。"""

    platform_id = "tvbanywhere"
    display_name = "TVBAnywhere"
    category = "streaming"
    url = "https://www.tvbanywhere.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=("not available in your region", "not available in your country",
                                       "isn't available in your", "该国家或地区不可用"))
    detail_blocked = "TVBAnywhere 在该出口不可用"


# =============================================================== 国际 AI 平台

class ChatGPTDetector(_WebDetector):
    """ChatGPT：区分网页响应、地区限制、风控及连接错误。"""

    platform_id = "chatgpt"
    display_name = "ChatGPT"
    category = "ai"
    url = "https://chatgpt.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS, block_requires_marker=True)
    detail_blocked = "ChatGPT 在该出口被地区限制"
    detail_unlocked = "ChatGPT 可访问"


class ClaudeDetector(_WebDetector):
    """Claude：区分网页响应、地区限制、风控及连接错误。"""

    platform_id = "claude"
    display_name = "Claude"
    category = "ai"
    url = "https://claude.ai/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS, block_requires_marker=True)
    detail_blocked = "Claude 在该出口被地区限制"
    detail_unlocked = "Claude 可访问"


class GeminiDetector(_WebDetector):
    """Google Gemini（gemini.google.com）。

    说明：Gemini 对数据中心 IP 经常直接 403（Cloudflare），这类响应判 unknown；
    只有正文明确写出「该国家/地区不支持」才判 blocked。
    """

    platform_id = "gemini"
    display_name = "Google Gemini"
    category = "ai"
    url = "https://gemini.google.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS + (
                           "you are accessing gemini from an unsupported country",
                           "your country is not supported"),
                       block_requires_marker=True)
    detail_blocked = "Gemini 在该出口被地区限制"
    detail_unlocked = "Gemini 可访问"


class GoogleAIDetector(_WebDetector):
    """Google AI Studio（aistudio.google.com）：开发者入口。

    与 Gemini 同口径：403 多为风控，只有明确的地区措辞才判 blocked。
    """

    platform_id = "google_ai"
    display_name = "Google AI Studio"
    category = "ai"
    url = "https://aistudio.google.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS + (
                           "your country is not supported",
                           "not available in your country"),
                       block_requires_marker=True)
    detail_blocked = "Google AI Studio 在该出口被地区限制"
    detail_unlocked = "Google AI Studio 可访问"


class PerplexityDetector(_WebDetector):
    """Perplexity：与 AI 类同口径；无头请求常被 Cloudflare 拦（unknown）。"""

    platform_id = "perplexity"
    display_name = "Perplexity"
    category = "ai"
    url = "https://www.perplexity.ai/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS, block_requires_marker=True)
    detail_blocked = "Perplexity 在该出口被地区限制"
    detail_unlocked = "Perplexity 可访问"


class GrokDetector(_WebDetector):
    """Grok（grok.com）：与 AI 类同口径。"""

    platform_id = "grok"
    display_name = "Grok"
    category = "ai"
    url = "https://grok.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS, block_requires_marker=True)
    detail_blocked = "Grok 在该出口被地区限制"
    detail_unlocked = "Grok 可访问"


class CopilotDetector(_WebDetector):
    """Microsoft Copilot：与 AI 类同口径。"""

    platform_id = "copilot"
    display_name = "Copilot"
    category = "ai"
    url = "https://copilot.microsoft.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS, block_requires_marker=True)
    detail_blocked = "Copilot 在该出口被地区限制"
    detail_unlocked = "Copilot 可访问"


# =============================================================== 社交 / 其他

class WikipediaDetector(_WebDetector):
    """维基百科可编辑性：作为「基础连通 + 可写权限」参照。

    只判可达性，不涉及地区限制；403 视为异常（error）。
    """

    platform_id = "wikipedia"
    display_name = "维基百科"
    category = "social_other"
    url = "https://zh.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json"
    markers = Markers(blocked_status=(), unsupported_status=(404,))
    detail_unlocked = "维基百科 API 可访问"


# 全部探测器（registry.py 会再做一次分组与去重校验）
ALL_PLATFORM_DETECTORS: tuple[Detector, ...] = (
    NetflixDetector(),
    DisneyPlusDetector(),
    MaxDetector(),
    YouTubePremiumDetector(),
    TikTokDetector(),
    SpotifyDetector(),
    AmazonPrimeVideoDetector(),
    RedditDetector(),
    HuluDetector(),
    ParamountPlusDetector(),
    PeacockDetector(),
    AppleTVPlusDetector(),
    AbemaTVDetector(),
    TVerDetector(),
    NHKPlusDetector(),
    BahamutDetector(),
    DAZNDetector(),
    CrunchyrollDetector(),
    ViuDetector(),
    DMMDetector(),
    IQIYIDetector(),
    WeTVDetector(),
    DiscoveryPlusDetector(),
    BilibiliIntlDetector(),
    TwitchDetector(),
    BBCDetector(),
    TVBAnywhereDetector(),
    ChatGPTDetector(),
    ClaudeDetector(),
    GeminiDetector(),
    GoogleAIDetector(),
    PerplexityDetector(),
    GrokDetector(),
    CopilotDetector(),
    WikipediaDetector(),
)
