"""各平台的精细化探测器。

一个平台一个类，继承 ``probes.base.Detector``。每个类的 docstring 写清
**判定规则与理由**，代码只负责把规则实现出来。

设计原则（与旧的一刀切实现最大的区别）：

* **拿不准就说拿不准**：人机校验、风控页、无特征 403 一律 ``unknown``，
  绝不臆断成「被地区拒绝」——猜错的代价是节点能力徽章错标。
* **状态之外再给结构化信息**：地区码放在 ``region``，平台特有结论放在
  ``extra``（如 Netflix 的 ``originals`` / ``full_library``）。
* **只用正文里真实存在的特征**做判定，不臆造页面结构；页面结构变了就
  降级成 ``unknown`` 并在 ``detail`` 里说明。
"""
import re

import httpx

from .base import (
    STATE_BLOCKED,
    STATE_ERROR,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
    Detector,
    Markers,
    ProbeResponse,
    ProbeResult,
    classify,
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
        cls = classify(resp.status, resp.text, self.markers)
        region = self.extract_region(resp.text, self.region_patterns)
        detail = cls.detail
        if cls.state == STATE_UNLOCKED:
            detail = self.detail_unlocked or ("可访问，但未能识别地区码" if not region else "")
        elif cls.state == STATE_BLOCKED and self.detail_blocked:
            detail = self.detail_blocked
        return ProbeResult(platform=self.platform_id, state=cls.state, status=resp.status,
                           region=region, detail=detail, extra=self.build_extra(resp))


# =============================================================== 流媒体 · Netflix


class NetflixDetector(Detector):
    """Netflix：区分「可看自制剧 / 可看全库 / 完全封锁」，并尽量取到地区码。

    两个入口（社区解锁检测的通用做法）：

    * ``https://www.netflix.com/title/81280792`` —— 目录里的一条内容页。
      页面内嵌 JSON 里有 ``"isAvailable"``（这条内容在当前出口能不能看）
      与 ``"isOriginal"``（这条是不是 Netflix 自制剧）。
    * ``https://www.netflix.com/regions`` —— Netflix 服务覆盖的国家清单。

    判定规则（每条都写清理由）：

    1. 标题页 200 且 ``"isAvailable":true`` → 该出口在服务范围内（unlocked）。
       再看 ``"isOriginal"``：
       * ``false`` 说明这条是**授权片库**内容 → 该出口拿到的是完整片库，
         ``full_library=true``；
       * ``true``（或该字段缺失）只能证明自制剧可用，片库完整性从这一个
         入口证明不了 → ``originals=true``、``full_library=false``，
         状态仍是 unlocked，detail 写明「仅自制剧可用」。
    2. 标题页 200 但 ``"isAvailable":false`` → 这条内容在当前出口不可用，
       是 Netflix 按地区裁剪目录的结果 → blocked。
    3. 标题页 404（内容不在当前目录）而 ``/regions`` 可访问且带国家清单 →
       该地区有 Netflix 服务、目录被裁剪 → 「仅自制剧」→ unlocked + originals。
    4. 标题页 403 → Netflix 对拒绝的出口返回 403；带地区特征时 blocked，
       带 Cloudflare 特征时 unknown（人机校验不是地区问题）。
    5. 标题页 200 却读不出 ``isAvailable`` → unknown（页面结构变了，
       不能冒充解锁）。

    地区码：只从标题页的上下文 JSON 取（``"countryCode"`` 优先）。
    ``/regions`` 是「服务覆盖国家清单」，不是出口所在国家，直接取第一个
    国家会得到无关国家，所以不拿它当地区码来源。
    """

    platform_id = "netflix"
    display_name = "Netflix"
    category = "streaming"
    title_url = "https://www.netflix.com/title/81280792"
    regions_url = "https://www.netflix.com/regions"
    # Netflix 握手慢（TLS + 地理跳转），给更长超时
    timeout = 14.0
    url = title_url

    region_markers = (
        "not available in your country",
        "not available in your region",
        "not available",
        "该国家或地区不可用",
    )

    def probe(self, client: httpx.Client) -> ProbeResult:
        title = self.fetch(client, self.title_url)
        regions = self.fetch(client, self.regions_url)

        available = _json_flag(title.text, "isAvailable")
        original = _json_flag(title.text, "isOriginal")
        served = bool(re.search(r'"country"\s*:\s*"[A-Za-z]{2}"', regions.text or ""))
        region = self.extract_region(title.text)

        extra = {
            "originals": False,
            "full_library": False,
            "title_available": available,
            "title_is_original": original,
            "regions_reachable": regions.status == 200,
        }

        cls = classify(title.status, title.text, Markers(
            blocked_status=(403,),
            unsupported_status=(404,),
            region_markers=self.region_markers,
            block_requires_marker=False,
        ))

        if cls.state == STATE_UNKNOWN:
            return ProbeResult(self.platform_id, STATE_UNKNOWN, title.status, region=region,
                               detail=cls.detail, extra=extra)

        if title.status == 200:
            if available is True:
                full = original is False
                extra["originals"] = True
                extra["full_library"] = full
                detail = ("Netflix 全库可用" if full
                          else "Netflix 仅自制剧可用（完整片库未能确认）")
                return ProbeResult(self.platform_id, STATE_UNLOCKED, title.status,
                                   region=region, detail=detail, extra=extra)
            if available is False:
                extra["catalog"] = "trimmed"
                return ProbeResult(self.platform_id, STATE_BLOCKED, title.status, region=region,
                                   detail="Netflix 目录中不含该内容（地区限制）", extra=extra)
            return ProbeResult(self.platform_id, STATE_UNKNOWN, title.status, region=region,
                               detail="Netflix 标题页未给出 isAvailable 标志，无法判定目录可用性",
                               extra=extra)

        if title.status == 404:
            if regions.status == 200 and served:
                extra["originals"] = True
                extra["catalog"] = "trimmed"
                return ProbeResult(self.platform_id, STATE_UNLOCKED, title.status, region=region,
                                   detail="Netflix 仅自制剧可用（该地区目录已裁剪）", extra=extra)
            return ProbeResult(self.platform_id, STATE_BLOCKED, title.status, region=region,
                               detail="Netflix 不可用（标题页与服务国家清单均未通过）", extra=extra)

        if title.status == 403:
            return ProbeResult(self.platform_id, STATE_BLOCKED, title.status, region=region,
                               detail="Netflix 完全封锁：" + (cls.detail or "HTTP 403"), extra=extra)

        return ProbeResult(self.platform_id, STATE_ERROR, title.status, region=region,
                           detail=f"Netflix 返回 HTTP {title.status}", extra=extra)


# =============================================================== 流媒体 · Disney+


class DisneyPlusDetector(_WebDetector):
    """Disney+：能否访问 + 国家 / 地区码。

    判定规则：

    1. 200 → unlocked；地区码优先取 ``"countryCode"``，其次 ``"country"``，
       取不到留空并在 detail 里说明。
    2. 403 且正文含地区限制措辞 → blocked。
    3. 其它 403 → blocked：Disney+ 对未上线地区返回的就是 403
       （与「有地区特征」相比少了证据，但这是该站稳定的封锁响应）。
    4. 429 → error（限流，不是地区问题）。
    5. 404 → unsupported。
    """

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
    """HBO Max（现 Max）：是否被地区限制 / 风控拦截，能否访问主站。

    判定规则：

    1. 200 → unlocked（主站可达）；地区码取正文里的 ``"countryCode"`` / ``"region"``。
    2. 403 且正文含地区限制措辞 → blocked（明确的地区限制）。
    3. 403 且正文含 Cloudflare / 风控特征 → unknown（风控拦截，不是地区问题）。
    4. 403 且两者都没有 → unknown：Max 的 403 既可能是地区限制也可能是 WAF
       拦截，无头请求分不出来，如实说「无法判定」。
    5. 404 → unsupported。
    """

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
    """YouTube Premium：出口地区 + 该地区是否开通 Premium。

    判定规则：

    1. 200 且正文含 ``"countryCode":"XX"`` → unlocked，region=XX。
    2. 200 但没有 countryCode → unlocked，region 留空，detail 说明「未能识别地区码」。
    3. 正文出现「Premium 在当地不可用」的措辞
       （``premium is not available in your country`` /
       ``isn't available in your country``）→ blocked。
    4. 403 → blocked（YouTube Premium 对未开通地区直接拒绝）。
    5. 「该地区是否开通 Premium」：Premium 页会带一份「可开通 Premium 的国家清单」，
       若出口国家的 countryCode 在正文里出现两次以上（一次是当前国家上下文、
       一次在清单里）→ 认定已开通；找不到证据就填 ``premium_region_confirmed=false``，
       detail 写明「Premium 是否在该地区上架未能确认」，不臆断。
    """

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
        cls = classify(resp.status, resp.text, self.markers)
        region = self.extract_region(resp.text)
        confirmed = self._premium_confirmed(resp.text, region)
        extra = {"premium_region_confirmed": confirmed}
        detail = cls.detail
        if cls.state == STATE_UNLOCKED:
            if region and confirmed:
                detail = f"YouTube Premium 在 {region} 可用"
            elif region:
                detail = (f"出口地区 {region}；Premium 是否在该地区上架未能确认"
                          "（页面未给出可开通国家清单证据）")
            else:
                detail = "可访问，但未能识别地区码"
        return ProbeResult(self.platform_id, cls.state, resp.status, region=region,
                           detail=detail, extra=extra)

    @staticmethod
    def _premium_confirmed(body: str, region: str) -> bool:
        """出口国家是否出现在「可开通 Premium 的国家清单」里。

        判据：同一 countryCode 在正文出现两次以上（上下文一次 + 清单一次）。
        这是启发式判断，拿不准时返回 False 让 detail 说明「未能确认」。
        """
        if not region:
            return False
        count = len(re.findall(rf'"countryCode"\s*:\s*"{region}"', body or "", re.IGNORECASE))
        if count >= 2:
            return True
        return bool(re.search(r'"isPremiumAvailable(?:Country)?"\s*:\s*true', body or "",
                              re.IGNORECASE))


# =============================================================== 流媒体 · TikTok


class TikTokDetector(_WebDetector):
    """TikTok：能否访问、出口地区、直播 / 创作者限制的可见信号。

    判定规则：

    1. 200 → unlocked；地区码取正文里的 ``"region"`` / ``"countryCode"``。
    2. 403 → blocked（TikTok 对受限地区的典型响应）；403 带 Cloudflare 特征
       → unknown。
    3. 直播 / 创作者限制：无头请求拿不到真实直播间与创作者后台，
       只能从正文提示语里读出**是否存在限制提示**
       （``livestream is not available`` / ``直播间不可用`` 等），
       读不到就填 ``unknown`` 并在 detail 里说明原因，不臆断。
    """

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
        cls = classify(resp.status, resp.text, self.markers)
        region = self.extract_region(resp.text)
        extra = self.build_extra(resp)
        detail = cls.detail
        if cls.state == STATE_UNLOCKED:
            detail = "可访问；直播与创作者限制未能确认" if not region else "可访问"
        return ProbeResult(self.platform_id, cls.state, resp.status, region=region,
                           detail=detail, extra=extra)


# =============================================================== 流媒体 · Spotify


class SpotifyDetector(_WebDetector):
    """Spotify：区域限制状态 + 账号与出口 IP 的一致性。

    判定规则：

    1. 200 → unlocked；地区码取正文里的 ``"country"`` / ``"countryCode"``。
    2. 正文出现 ``not available in your country`` 一类措辞 → blocked。
    3. 403 → blocked（Spotify 对未上线地区返回 403）。
    4. 「账号与出口 IP 不匹配」是登录态提示，无头请求拿不到，
       固定填 ``account_ip_match="unknown"``，detail 里说明需要登录态复核。
    """

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
        cls = classify(resp.status, resp.text, self.markers)
        region = self.extract_region(resp.text)
        extra = self.build_extra(resp)
        detail = cls.detail
        if cls.state == STATE_UNLOCKED:
            detail = ("主站可达" + (f"，区域 {region}" if region else "，未能识别区域归属"))
            detail += "；片源完整性未判定"
        return ProbeResult(self.platform_id, cls.state, resp.status, region=region,
                           detail=detail, extra=extra)


# =============================================================== 流媒体 · Reddit


class RedditDetector(_WebDetector):
    """Reddit：可访问 / IP 封锁 / 验证码风控 / 异常。

    判定规则：

    1. 200 且无风控特征 → unlocked。
    2. 403 且正文含 Reddit 的 IP 封锁文案（``whoa there`` /
       ``you've been blocked`` / ``blocked by network security``）→ blocked（IP 被封）。
    3. 200 / 403 但正文含验证码特征（``captcha`` / ``verify you are human`` /
       ``are you a robot``）→ unknown（风控，不是地区问题）。
    4. 429 → error（限流）。
    5. 其它状态码按 classify 的口径归到 error / unknown。
    """

    platform_id = "reddit"
    display_name = "Reddit"
    category = "social_other"
    url = "https://www.reddit.com/"

    markers = Markers(
        blocked_status=(403,),
        unsupported_status=(404,),
        region_markers=("whoa there", "you've been blocked", "you have been blocked",
                        "blocked by network security", "your network has been blocked"),
        challenge_markers=("captcha", "verify you are human", "are you a robot",
                           "press and hold"),
        block_requires_marker=False,
    )

    def build_extra(self, resp: ProbeResponse) -> dict:
        blocked = _has(resp.text, self.markers.region_markers)
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
    """ChatGPT（chatgpt.com）：区分四种情形。

    1. 网络不通（超时 / 连接失败）→ error，由框架统一处理。
    2. 正常可用 → 200 → unlocked。
    3. 地区不支持 → 正文含 ``unsupported_country`` /
       ``not available in your country`` /
       ``country, region, or territory not supported`` → blocked。
    4. WAF 风控拦截 → 403 且含 Cloudflare 特征，或 403 且没有任何地区特征
       → unknown（**不是** blocked）：数据中心 IP 被 Cloudflare 拦是常态，
       与地区拒绝在无头请求下无法区分。
    """

    platform_id = "chatgpt"
    display_name = "ChatGPT"
    category = "ai"
    url = "https://chatgpt.com/"
    markers = Markers(blocked_status=(403,), unsupported_status=(404,),
                       region_markers=AI_REGION_MARKERS, block_requires_marker=True)
    detail_blocked = "ChatGPT 在该出口被地区限制"
    detail_unlocked = "ChatGPT 可访问"


class ClaudeDetector(_WebDetector):
    """Claude（claude.ai）：与 ChatGPT 同口径的四种情形。

    Claude 对无头请求几乎一律返回 403 + Cloudflare 挑战页，
    因此这里的 403 基本都判 unknown，只有正文明确说「本地区不可用」才判 blocked。
    """

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
