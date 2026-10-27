"""基础配置：多级联动的顶层键文档。

层级（后者覆盖前者）：
① 引擎默认配置：引擎内置的能力基线，随程序发布，可直接改；
② 引擎平台配置：按「引擎 + 平台」维护（与"引擎平台"一一对应，如 Stash-macOS）；
③ 设备独立配置：按设备维护，只对该设备的最终配置生效。

每层只存"与上层不同"的差异（overlay），因此上层默认值变化时，
没有被显式改过的键会自动跟随；"恢复默认"= 清空本层差异。

结构化内容（proxies / proxy-groups / rules 等）由各自的业务页面维护，
基础配置各层都不允许覆盖。
"""
from copy import deepcopy

import yaml
from deepmerge import Merger
from deepmerge.strategy import dict as DictStrategy
from deepmerge.strategy import fallback as FallbackStrategy
from deepmerge.strategy import list as ListStrategy
from deepmerge.strategy import type_conflict as TypeConflictStrategy

ENGINES = ("stash", "mihomo")

# 结构化内容由业务页面维护，基础配置与平台扩展都不允许覆盖
PROTECTED_KEYS = {
    "proxies": "节点由“节点来源 / 本地单节点”维护",
    "proxy-providers": "远程代理集由“节点来源”维护",
    "proxy-groups": "策略组由“策略组”页维护",
    "rule-providers": "规则集合由“规则来源”维护",
    "rules": "分流规则由“分流策略”页维护",
}

# 设备配置作用域额外禁止的键：控制面相关。
# 设备层只用于"这台设备的个性化"，写上对外控制端口等于
# 把管理接口暴露到局域网，客户端侧也没有对应的鉴权配置。
# dns 同样禁止：DNS 段固化在引擎默认配置（约束 31/33），
# 设备层的 dns: 覆盖会静默盖过基线（历史上出过 vpn.jiek.top 残留）。
DEVICE_FORBIDDEN_KEYS = {
    "external-controller": "设备配置不能开启对外控制端口",
    "external-ui": "设备配置不能指定外部控制器界面",
    "secret": "设备配置不能设置控制端口密钥",
    "listeners": "设备配置不能新增监听器",
}

# 产物中固定出现的顶层键（顺序固定，保证产物排版稳定）
CORE_KEYS = (
    "mixed-port", "socks-port", "redir-port", "tproxy-port", "port",
    "allow-lan", "bind-address", "mode", "log-level", "ipv6",
    "external-controller", "secret", "profile",
)

MODE_VALUES = ("rule", "global", "direct")
LOG_LEVELS = ("silent", "error", "warning", "info", "debug")
PORT_KEYS = ("mixed-port", "socks-port", "redir-port", "tproxy-port", "port")
BOOL_KEYS = ("allow-lan", "ipv6")

# 应用级伪键：不写入产物，只控制面板内置行为
PANEL_DIRECT_KEY = "_panel_direct_rule"
DIRECT_DOMAINS_KEY = "_direct_domains"      # 个人直连域名 → 置顶 DOMAIN-SUFFIX 规则
FAKE_IP_FILTER_KEY = "_fake_ip_filter"      # Fake-IP 过滤域名 → dns.fake-ip-filter

# ---- 引擎默认配置（按官方文档补全）----
#
# 依据：
#   Stash  —— https://stash.wiki/configuration/example-config
#   Mihomo —— MetaCubeX/mihomo 的 docs/config.yaml
#
# 取舍：
#   * 只收"客户端通用能力"类键，让下层（引擎平台配置 / 设备独立配置）不必重复；
#   * 对外控制端口（external-controller / external-ui / secret）不进默认——
#     那是服务端行为，客户端配置里带上等于把管理口开到局域网；
#   * MitM（http.ca）、脚本与定时任务需要用户内容，也不进默认；
#   * DNS 段给出通用取值，个人的 nameserver-policy 与 fake-ip-filter 留在下层。

_COMMON_DEFAULTS = {
    "mode": "rule",
    "log-level": "warning",
    # 全部引擎平台的实测取值都是 true（TUN 模式处理 v6），2026-10-28 从
    # 各平台层固化到这里，平台层不再重复
    "ipv6": True,
    "allow-lan": False,
    "bind-address": "127.0.0.1",
    # 客户端记忆：手动选中的节点与 Fake-IP 映射要跨重启保留（原先只在
    # Mihomo 默认与各平台层出现，现固化为通用基线）
    "profile": {"store-selected": True, "store-fake-ip": True},
    # 真实延迟（而非握手延迟）、并发拨号、长连接保活
    "unified-delay": True,
    "tcp-concurrent": True,
    "keep-alive-interval": 30,
    "find-process-mode": "strict",
    # Geo 数据：交给内核自动更新，规则里的 geosite/geoip 才不会命中过期数据
    "geodata-mode": True,
    "geo-auto-update": True,
    "geo-update-interval": 24,
    # 嗅探真实域名：应用走 IP 直连时也能命中分流规则。
    # 注意：`sniffing` 是 mihomo 官方已废弃的键（官方示例原文「已废弃，
    # 若 sniffer.sniff 配置则此项无效」），只保留在 Stash 基线里（历史
    # 配置一直在用，Stash 侧无害），mihomo 一律不写。
    "sniffer": {
        "enable": True,
        "force-dns-mapping": True,
        "parse-pure-ip": True,
        "override-destination": False,
        "sniff": {
            # 8080-8081 为各平台层多年的实测取值（2026-10-28 固化）；
            # 官方示例的 8080-8880 覆盖面更宽但没有必要
            "HTTP": {"ports": [80, "8080-8081"], "override-destination": True},
            "TLS": {},
            "QUIC": {},
        },
    },
    PANEL_DIRECT_KEY: True,
}

# ---- 家用个人清单（2026-10-28 从引擎平台配置层固化）----
#
# 此前 8 个引擎平台层各自维护同一份清单（逐字一致），属于典型的
# 「共有内容」，按分层原则上收到引擎默认配置；设备层仍可追加
# （设备层列表语义是 append）。
_PERSONAL_DIRECT_DOMAINS = [
    "magichub.top", "jiek.top", "homehub.stream",
    "astralwave.org", "233netcloud.com", "ghfast.top",
]
# Fake-IP 排除清单。Stash 与 mihomo 各一份，仅差一个条目：
# * `geosite:private` 只给 Stash——mihomo 官方文档（wiki.metacubex.one
#   /config/dns/）明确 fake-ip-filter 的 blacklist 模式「仅支持域名通配
#   以及引入域名集合」，GEOSITE/RuleSet 语法只在 fake-ip-filter-mode:
#   rule 下可用；mihomo 里写了会被当字面域名，无效。
# * +.captive.apple.com 两边都有；+.dnscli.top 来自设备层追加收编
#   （见约束 31，设备层不许写 dns: 键）。
# **注意**：清单里的海外域与上方 _OVERSEAS_SENSITIVE 一一对应，
# 两边要一起改。
_PERSONAL_FAKE_IP_FILTER = [
    "+.lan", "+.local", "+.home.arpa", "+.ts.net", "localhost",
    "localhost.ptlogin2.qq.com",
    "+.msftconnecttest.com", "+.msftncsi.com",
    "+.captive.apple.com",
    "time.*.com", "+.ntp.org", "+.ntp.org.cn", "+.pool.ntp.org",
    "stun.*.*", "stun.*.*.*", "+.stun.*.*", "+.stun.*.*.*",
    "+.srv.nintendo.net", "+.stun.playstation.net",
    "+.xboxlive.com", "+.logon.battle.net", "+.battlenet.com.cn",
    "+.magichub.top", "+.jiek.top", "+.homehub.stream",
    "+.eoysky.com", "+.astralwave.org", "+.233netcloud.com", "+.ghfast.top",
    "geosite:private",
    "+.microsoft.com", "+.microsoftstore.com", "+.s-microsoft.com",
    "+.windows.com", "+.windows.net", "+.windowsupdate.com",
    "+.msftauth.net", "+.msauth.net", "+.live.com",
    "lens.l.google.com",
    "*.tailscale.com", "*.tailscale.io",
    "+.market.xiaomi.com", "*.arpa",
    "+.dnscli.top",
]

# ---- DNS 段取值（2026-10-27 重构：默认国内直连，海外敏感域走代理）----
#
# 背景（2026-10-25 / 10-27 两次国内网络实测）：
#   * 国内解析器（alidns / doh.pub / 1.12.12.12 等）解析海外被墙域名返回假 IP，
#     是解析器服务端行为，链路加密挡不住；对国内域名则给出正确的国内 CDN 节点；
#   * 境外 DoH（1.1.1.1 / 8.8.8.8 …）国内直连不通，只能走代理出口；
#   * 明文 UDP 全程可被链路注入，一律不用。
#
# 设计原则：本地解析结果只在两种场合真正被使用——
#   1) 命中 Fake-IP 排除清单的域名（应用拿到真实 IP，答案必须干净）；
#   2) 走 DIRECT 的连接（必须拿到国内视角的正确 CDN 节点）。
# 其余域名（海外、走代理）由代理节点在出口侧远程解析，本地答案无关紧要。
# 因此：
#   * 默认 nameserver 用国内 DoH 直连（裸 IP）——快、国内视角正确，
#     且不依赖代理存活；它对海外域名的污染答案反正不会被使用；
#   * 海外敏感域名（Fake-IP 排除清单里的海外域、走直连的海外集合）
#     的 nameserver-policy 已整体固化在本文件（2026-10-27 定稿），
#     指到境外 DoH 走代理；平台层/设备层/拓展模块一律不得再写 dns: 键；
#   * 不配 fallback / fallback-filter：配置 fallback 会默认启用 geoip CN
#     过滤（mihomo 文档明示），多一个 geo 数据依赖，且没有"污染值"可筛；
#   * DNS 服务器一律裸 IP 形式（官方要求，避免引导解析与递归查询）。
#
# 出口配套规则（缺任何一组 DNS 都会断）：
#   * IP-CIDR,1.1.1.1/32 等 → 🚀 默认代理：境外 DoH 经代理可达
#     （Stash follow-rule 依赖这组规则；Mihomo 平台层用 "#策略组" 后缀）；
#   * IP-CIDR,120.53.53.53/32 / 223.5.5.5/32 → DIRECT：国内 DoH 保持直连。

_DNS_COMMON = {
    "fake-ip-range": "198.18.0.1/16",
    # 节点域名解析：独立链路，不跟随规则，必须国内可达（裸 IP 国内 DoH）
    "proxy-server-nameserver": ["https://120.53.53.53/dns-query",
                                "https://223.5.5.5/dns-query"],
}

# 国内 DoH（裸 IP）：默认解析器。120.53.53.53 = 腾讯 DNSPod（doh.pub），
# 223.5.5.5 = 阿里 alidns——两家运营商互为冗余。alidns 对海外域名有污染，
# 但本设计里默认解析器的海外答案永远不会被使用（fake-ip 由节点远程解析、
# 海外敏感域显式走境外 DoH），它的国内答案与 doh.pub 实测一致。
_CN_DOH = ["https://120.53.53.53/dns-query", "https://223.5.5.5/dns-query"]
# 境外 DoH（裸 IP）：海外敏感域名策略的目标，经代理出口。
_FOREIGN_DOH = ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"]

# 海外敏感域：Fake-IP 排除清单（`_fake_ip_filter` 伪键）里的海外域，
# 应用拿到的是真实 IP，答案必须干净 → 指到境外 DoH（经代理出口）。
# 两份清单要一起改：这里加一个域，`_fake_ip_filter` 里也要有它，反之亦然。
_OVERSEAS_SENSITIVE = [
    "+.microsoft.com", "+.microsoftstore.com", "+.s-microsoft.com",
    "+.windows.com", "+.windows.net", "+.windowsupdate.com",
    "+.msftauth.net", "+.msauth.net", "+.live.com", "lens.l.google.com",
]
# 「直连但服务器在境外」的规则集合：同样需要干净答案。**这三个集合被 DNS
# 策略引用（rule-set: 键），删了它们策略就悬空**——改名或删除前先改这里。
_OVERSEAS_DIRECT_SETS = ["mirror-accelerate", "pt", "trackers"]


def _dns_policy(foreign: list) -> dict:
    """nameserver-policy：内网走 system，海外敏感域走境外 DoH（经代理出口）。"""
    p = {"+.lan": "system", "+.local": "system", "+.home.arpa": "system",
         "+.ts.net": "system", "localhost": "system"}
    for k in _OVERSEAS_SENSITIVE:
        p[k] = list(foreign)
    for r in _OVERSEAS_DIRECT_SETS:
        p[f"rule-set:{r}"] = list(foreign)
    return p

# Stash 官方内置 DNS 服务支持的键（https://stash.wiki/features/dns-server）：
#   nameserver / default-nameserver / proxy-server-nameserver / nameserver-policy
#   fake-ip-range / fake-ip-filter / ipv6 / fallback / follow-rule / hosts
# 注意：Stash 常驻 Fake-IP，没有 enhanced-mode，也没有 enable；
# 跟随规则用 follow-rule（Mihomo 才叫 respect-rules）。
# follow-rule 必须开：海外敏感域名的策略服务器是境外 DoH 裸 IP，
# 靠 IP-CIDR 出口规则送进代理；国内 DoH 裸 IP 靠直连 IP 规则保持直连。
# DNS 段整体固化在引擎默认配置（本文件），平台层/平台扩展/设备层/拓展模块
# 一律不再写 dns: 键（家用 Fake-IP 清单用伪键 `_fake_ip_filter` 维护，
# 2026-10-28 起固化在引擎默认配置，设备层仍可追加）。
STASH_DNS = {
    **_DNS_COMMON,
    "nameserver": list(_CN_DOH),
    "follow-rule": True,
    "ipv6": False,
    "nameserver-policy": _dns_policy(_FOREIGN_DOH),
}

# Google 中国站重定向（Stash HTTP 引擎）：
#   MitM 列表 + url-rewrite 一起用；HTTPS 重写需要设备信任 Stash 的 CA 证书
#   （Stash 首页 → MitM → CA 证书 → 安装并信任），否则这些域名会证书报错。
#   列表只收 Google 中国站域名，范围小、可控。
STASH_HTTP = {
    "ca": "",
    "ca-passphrase": "",
    "mitm": ["g.cn", "*.google.cn"],
    "url-rewrite": [
        # 谷歌地图（旧域名 ditu.google.cn 一并带上）
        "^https?://(maps|ditu)\\.google\\.cn https://www.google.com/maps 302",
        # 谷歌中国站其余子域
        "^https?://([\\w-]+\\.)?google\\.cn https://www.google.com 302",
        # 明文 HTTP 的 g.cn：透明改写，不改变客户端可见的 IP
        "^http://(www\\.)?g\\.cn https://www.google.com transparent",
    ],
}

# Stash：DNS 段与 HTTP 引擎按官方文档给全；个人清单伪键一并固化。
# `sniffing` 是 Stash 历史配置一直在用的嗅探协议清单（mihomo 已废弃该键，
# 两引擎的 sniffer 在这里分叉）。
STASH_OFFICIAL = {
    **_COMMON_DEFAULTS,
    "sniffer": {
        **deepcopy(_COMMON_DEFAULTS["sniffer"]),
        "sniffing": ["tls", "http", "quic"],
    },
    "dns": deepcopy(STASH_DNS),
    "http": deepcopy(STASH_HTTP),
    DIRECT_DOMAINS_KEY: list(_PERSONAL_DIRECT_DOMAINS),
    FAKE_IP_FILTER_KEY: list(_PERSONAL_FAKE_IP_FILTER),
}

# Mihomo：DNS 由内核接管，需要显式 enable；端口与 profile 由内核读取
# （profile 已上收到 _COMMON_DEFAULTS）。mihomo 特有：客户端 TLS 指纹、
# sniffer 的 TLS 端口与跳过域名清单（Mijia Cloud 是 mihomo 嗅探的已知误匹配）。
MIHOMO_OFFICIAL = {
    **_COMMON_DEFAULTS,
    "mixed-port": 7890,
    "global-client-fingerprint": "chrome",
    # Geo 数据下载走官方示例同款 jsdelivr 镜像：客户端 geo-auto-update
    # 若用默认 GitHub 直连地址，国内环境经常超时失败，geo 文件停留在旧版
    "geox-url": {
        "geoip": "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.dat",
        "geosite": "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat",
        "mmdb": "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb",
    },
    "sniffer": {
        **deepcopy(_COMMON_DEFAULTS["sniffer"]),
        "sniff": {
            **deepcopy(_COMMON_DEFAULTS["sniffer"]["sniff"]),
            "TLS": {"ports": [443, 8443]},
        },
        "skip-domain": [
            "Mijia Cloud", "+.push.apple.com",
            "+.lan", "+.local", "+.home.arpa",
        ],
    },
    "dns": {
        **deepcopy(_DNS_COMMON),
        "enable": True,
        "ipv6": False,
        "enhanced-mode": "fake-ip",
        "fake-ip-filter-mode": "blacklist",
        "prefer-h3": False,
        # DNS 连接遵守路由规则（官方要求配 proxy-server-nameserver，已配）：
        # 境外 DoH 裸 IP 靠 IP-CIDR 出口规则走代理，国内 DoH 裸 IP 靠直连 IP 规则
        # 保持直连——引擎默认层因此不用写死策略组名（"#策略组" 后缀留给平台层
        # 需要指定别的出口时用）。官方文档不建议与 prefer-h3 同用，prefer-h3 为 False。
        "respect-rules": True,
        "nameserver": list(_CN_DOH),
        # 内网走系统 DNS；海外敏感域与直连海外集合走境外 DoH（经代理出口）
        "nameserver-policy": _dns_policy(_FOREIGN_DOH),
        "use-hosts": True,
        # fake-ip-filter 由伪键 _fake_ip_filter 统一维护（渲染时覆盖写回），
        # 这里不再重复一份
    },
    DIRECT_DOMAINS_KEY: list(_PERSONAL_DIRECT_DOMAINS),
    # mihomo 的 blacklist 模式不支持 GEOSITE 语法（见上），剔除该条目
    FAKE_IP_FILTER_KEY: [
        x for x in _PERSONAL_FAKE_IP_FILTER if x != "geosite:private"
    ],
}

# 兼容现状（补全前的旧默认，保留作预设与迁移基准）
COMPAT = {
    "mixed-port": 7890,
    "allow-lan": False,
    "mode": "rule",
    "log-level": "warning",
    "ipv6": False,
    "profile": {"store-selected": True, "store-fake-ip": True},
    PANEL_DIRECT_KEY: True,
}

# MTProto 代理（Telegram）——Stash 官方文档 https://stash.wiki/features/mtproto
# 放在「设备独立配置」里：哪台设备要用就给它加一份，不想用了删掉即可。
# secret 是客户端连接的唯一凭证，{{mtproto_secret}} 由前端在套用时替换成
# 现场生成的 32 位十六进制密钥（官方建议 openssl rand -hex 16）。
MTPROTO = {
    "mtproto": {
        "port": 5753,
        "secret": "{{mtproto_secret}}",
        "ipv6": False,
    },
}

PRESETS = {
    "stash": {
        "official": ("Stash 官方完整默认", deepcopy(STASH_OFFICIAL)),
        "compat": ("兼容现状（精简）", deepcopy(COMPAT)),
        "mtproto": ("MTProto 代理（Telegram）", deepcopy(MTPROTO)),
    },
    "mihomo": {
        "official": ("Mihomo 官方完整默认", deepcopy(MIHOMO_OFFICIAL)),
        "compat": ("兼容现状（精简）", deepcopy(COMPAT)),
    },
}

DEFAULT_ENGINE = "stash"


def default_doc(engine: str) -> dict:
    """引擎默认配置：按官方文档补全的完整基线。"""
    return deepcopy(PRESETS[engine]["official"][1])


# ---- 多级联动：合并、差异、来源 ----

# 多级联动的合并策略（用成熟库 deepmerge 实现，避免手写合并出纰漏）：
# - 字典：递归合并（并集，逐键覆盖）
# - 列表：默认整体替换（不拼接，避免配置语义含糊）；设备层用"追加"（个性化语义）
# - 标量 / 类型冲突：后者覆盖前者
_MERGER = Merger(
    [(list, ListStrategy.ListStrategies.strategy_override),
     (dict, DictStrategy.DictStrategies.strategy_merge)],
    FallbackStrategy.FallbackStrategies.strategy_override,
    TypeConflictStrategy.TypeConflictStrategies.strategy_override,
)

# 设备独立配置层用追加语义：这一层表达的是"这台设备的个性化"，
# 典型场景是给 DNS 过滤列表再加一条，而不是重写整份列表。
_MERGER_APPEND = Merger(
    [(list, ListStrategy.ListStrategies.strategy_append),
     (dict, DictStrategy.DictStrategies.strategy_merge)],
    FallbackStrategy.FallbackStrategies.strategy_override,
    TypeConflictStrategy.TypeConflictStrategies.strategy_override,
)

# 列表的两种语义
LIST_REPLACE = "replace"   # 整体替换（引擎默认配置 / 引擎平台配置）
LIST_APPEND = "append"     # 追加（设备独立配置）


def merge_docs(base: dict, overlay: dict, lists: str = LIST_REPLACE) -> dict:
    """合并一层覆盖：键级并集，同键后者覆盖前者。

    字典递归合并、列表按 lists 指定（替换 / 追加）、标量覆盖——
    语义由 deepmerge 的策略显式声明。
    """
    if not overlay:
        return deepcopy(base or {})
    if not base:
        return deepcopy(overlay)
    merger = _MERGER_APPEND if lists == LIST_APPEND else _MERGER
    return merger.merge(deepcopy(base), deepcopy(overlay))


def diff_overlay(base: dict, effective: dict, lists: str = LIST_REPLACE) -> dict:
    """比较"上层生效值"与"本层编辑后的值"，得出本层真正需要覆盖的差异。

    字典递归比较；列表按 lists 指定：
    * replace —— 列表整体比较，不同就存整份（配合替换语义还原"用户写的那份"）；
    * append  —— 只存新增的条目（配合追加语义，删除上层条目做不到，
      要回到上层默认值请用「恢复继承」）。
    """
    overlay: dict = {}
    for key, value in (effective or {}).items():
        if key not in (base or {}):
            overlay[key] = deepcopy(value)
            continue
        old = base[key]
        if isinstance(value, dict) and isinstance(old, dict):
            sub = diff_overlay(old, value, lists)
            if sub:
                overlay[key] = sub
        elif isinstance(value, list) and isinstance(old, list) and lists == LIST_APPEND:
            added = [item for item in value if item not in old]
            if added:
                overlay[key] = deepcopy(added)
        elif value != old:
            overlay[key] = deepcopy(value)
    return overlay


def cascade(layers: list[tuple[str, dict]]) -> tuple[dict, dict]:
    """按层级顺序合并，返回 (生效文档, 每个键的来源层级)。

    layers 形如 [("引擎默认配置", {...}), ("引擎平台配置", {...}), ("设备独立配置", {...})]，
    来源记录到最后一次改写该键的层（顶层键粒度），便于界面展示"这个值来自哪一层"。
    """
    effective: dict = {}
    sources: dict = {}
    for label, doc in layers:
        # 设备独立配置层用追加语义（个性化 = 在上层基础上加东西）
        lists = LIST_APPEND if label == "设备独立配置" else LIST_REPLACE
        for key, value in (doc or {}).items():
            if isinstance(value, dict) and isinstance(effective.get(key), dict):
                effective[key] = merge_docs(effective[key], value, lists)
            elif (lists == LIST_APPEND and isinstance(value, list)
                  and isinstance(effective.get(key), list)):
                # 顶层级列表键（_fake_ip_filter 等伪键）同样追加：
                # 之前只有嵌在字典里的列表（dns.fake-ip-filter）能追加，
                # 顶层级列表会被静默替换，与「设备层 = 追加」的文档语义不符
                effective[key] = list(effective[key]) + [
                    item for item in value if item not in effective[key]]
            else:
                effective[key] = deepcopy(value)
            # 后面的层级优先：来源记录最后一次改写该键的层
            sources[key] = label
    return effective, sources


def leaf_sources(layers: list[tuple[str, dict]]) -> dict[str, str]:
    """每个叶子路径的来源层级（点号路径，如 "dns.nameserver"）。

    顶层来源不足以说明"dns 里的 nameserver 来自哪一层"——引擎平台配置改了
    dns.nameserver、引擎默认配置改了 dns.enable，两者来源不同。界面按叶子
    展示来源，这里给出对应的点号路径映射。
    """
    sources: dict[str, str] = {}

    def mark(path: str, value, label: str) -> None:
        if isinstance(value, dict) and value:
            for k, v in value.items():
                mark(f"{path}.{k}", v, label)
        else:
            sources[path] = label

    for label, doc in layers:
        for key, value in (doc or {}).items():
            mark(key, value, label)
    return sources


def scope_layers(engine: str, platform: str = "", device_id: int = 0,
                 docs: dict | None = None) -> list[tuple[str, dict]]:
    """按作用域取出各层文档（从低到高：引擎默认配置 → 引擎平台配置 → 设备独立配置）。

    返回的列表**包含当前作用域自己那一层**，因此：
    - layers[:-1] 是当前层的"继承值"（上层合并结果）；
    - layers 是完整链路，合并结果即"生效值"。

    引擎默认配置本身也可以被覆盖：用户改的是"默认值之上的差异"，
    差异存在 (engine, "", 0) 这条记录里；不覆盖时就是源码里的默认值，
    随时可以删掉这条记录恢复默认。
    """
    docs = docs or {}
    # 默认值 = 源码内置内容 + 用户对默认值的覆盖（存 (engine, "", 0)）
    base = deepcopy(default_doc(engine))
    override = docs.get((engine, "", 0))
    if override:
        base = merge_docs(base, override)
    layers: list[tuple[str, dict]] = [("引擎默认配置", base)]
    if platform:
        # 当前作用域自己那一层始终参与（没有覆盖时为空层），
        # 这样 layers[:-1] 才是"继承自上层的值"。
        layers.append(("引擎平台配置", deepcopy(docs.get((engine, platform, 0)) or {})))
    if device_id:
        layers.append(("设备独立配置", deepcopy(docs.get((engine, platform, int(device_id))) or {})))
    return layers


def parse_content(content: str) -> dict:
    """解析 YAML 文本；必须是映射。"""
    if content is None or not content.strip():
        raise ValueError("基础配置不能为空")
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败：{exc}") from exc
    if data is None:
        raise ValueError("基础配置不能为空")
    if not isinstance(data, dict):
        raise ValueError("基础配置必须是键值映射")
    return data


def validate_doc(doc: dict, device_scope: bool = False,
                 allow_dns: bool = False) -> None:
    """校验基础配置；不合法时抛 ValueError（中文提示）。

    allow_dns 仅引擎默认配置层为 True：DNS 段固化在源码基线（约束 31），
    平台层/设备层的 dns: 覆盖会静默盖过基线（曾出过 vpn.jiek.top 残留），
    一律拒绝；Fake-IP 清单走 `_fake_ip_filter` 伪键。
    """
    for key in doc:
        if key in PROTECTED_KEYS:
            raise ValueError(f"基础配置不能包含“{key}”：{PROTECTED_KEYS[key]}")
        if device_scope and key in DEVICE_FORBIDDEN_KEYS:
            raise ValueError(DEVICE_FORBIDDEN_KEYS[key])
        if key == "dns" and not allow_dns:
            raise ValueError(
                "DNS 段固化在引擎默认配置，平台/设备层不能写 dns: 键"
                "（Fake-IP 过滤清单请用 _fake_ip_filter 伪键）")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("基础配置的键名非法")
    if "mode" in doc and doc["mode"] not in MODE_VALUES:
        raise ValueError(f"mode 仅支持：{'、'.join(MODE_VALUES)}")
    if "log-level" in doc and doc["log-level"] not in LOG_LEVELS:
        raise ValueError(f"log-level 仅支持：{'、'.join(LOG_LEVELS)}")
    for key in BOOL_KEYS:
        if key in doc and not isinstance(doc[key], bool):
            raise ValueError(f"{key} 必须是布尔值")
    for key in PORT_KEYS:
        if key in doc:
            value = doc[key]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} 必须是整数端口")
            if not 1 <= value <= 65535:
                raise ValueError(f"{key} 需在 1-65535 之间")
    if PANEL_DIRECT_KEY in doc and not isinstance(doc[PANEL_DIRECT_KEY], bool):
        raise ValueError("面板域名强制直连开关必须是布尔值")
    for key, label in ((DIRECT_DOMAINS_KEY, "个人直连域名"),
                       (FAKE_IP_FILTER_KEY, "Fake-IP 过滤域名")):
        if key in doc:
            value = doc[key]
            if value is None:
                continue
            if not isinstance(value, list) or any(
                    not isinstance(item, str) for item in value):
                raise ValueError(f"{label}必须是字符串列表")
    if "profile" in doc and not isinstance(doc["profile"], dict):
        raise ValueError("profile 必须是键值映射")
    if "dns" in doc and not isinstance(doc["dns"], dict):
        raise ValueError("dns 必须是键值映射")
    for key in ("proxy-server-nameserver",):
        if key in doc and not isinstance(doc[key], list):
            raise ValueError(f"{key} 必须是列表")


def to_yaml(doc: dict) -> str:
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=4096)


def normalize_domains(values) -> list[str]:
    """个人直连域名归一化：去空白、转小写、去掉通配前缀、去重。"""
    result: list[str] = []
    for item in values or []:
        text = str(item).strip().lower()
        for prefix in ("+.", "*."):
            if text.startswith(prefix):
                text = text[len(prefix):]
        text = text.strip()
        if not text or "/" in text or ":" in text or " " in text:
            continue
        if text not in result:
            result.append(text)
    return result


def normalize_filter(values) -> list[str]:
    """Fake-IP 过滤条目归一化：保留 geosite:/rule-set:/通配写法。"""
    result: list[str] = []
    for item in values or []:
        text = str(item).strip()
        if not text or text in result:
            continue
        result.append(text)
    return result


def normalize(doc: dict) -> dict:
    """规范化后进快照：空 dns 视为未配置；其余保持原样。"""
    result = deepcopy(doc)
    if isinstance(result.get("dns"), dict) and not result["dns"]:
        result.pop("dns")
    return result


def ordered(doc: dict) -> dict:
    """按固定顺序输出：核心键在前，其余用户键按字母序。"""
    result: dict = {}
    for key in CORE_KEYS:
        if key in doc:
            result[key] = doc[key]
    for key in sorted(k for k in doc if k not in CORE_KEYS):
        result[key] = doc[key]
    return result


# ---- 结构化表单 schema（前端据此渲染，与本地节点同样的数据驱动风格） ----

def _field(key, label, kind="text", **kwargs):
    data = {"key": key, "label": label, "type": kind}
    data.update(kwargs)
    return data


SCHEMA = [
    _field(PANEL_DIRECT_KEY, "面板域名强制直连（置顶规则）", "switch", group="basic",
           default=True, engines=["stash", "mihomo"]),
    _field("mode", "运行模式", "select", group="basic",
           options=[{"value": v, "label": v} for v in MODE_VALUES],
           default="rule", engines=["stash", "mihomo"]),
    _field("log-level", "日志级别", "select", group="basic",
           options=[{"value": v, "label": v} for v in LOG_LEVELS],
           default="warning", engines=["stash", "mihomo"]),
    _field("ipv6", "IPv6", "switch", group="basic", default=False,
           engines=["stash", "mihomo"]),
    _field("mixed-port", "混合端口", "number", group="basic", default=7890,
           engines=["mihomo"]),
    _field("socks-port", "SOCKS 端口", "number", group="basic",
           engines=["mihomo"]),
    _field("redir-port", "透明端口", "number", group="basic",
           engines=["mihomo"]),
    _field("tproxy-port", "TProxy 端口", "number", group="basic",
           engines=["mihomo"]),
    _field("allow-lan", "允许局域网连接", "switch", group="basic",
           default=False, engines=["mihomo"]),
    _field("bind-address", "监听地址", "text", group="basic",
           placeholder="留空表示不限制", engines=["mihomo"]),
    _field("profile.store-selected", "记住策略组选择", "switch",
           group="profile", default=True, engines=["mihomo"]),
    _field("profile.store-fake-ip", "记住 Fake-IP 映射", "switch",
           group="profile", default=True, engines=["mihomo"]),
    # DNS
    _field("dns.enable", "启用 DNS", "switch", group="dns", default=True,
           engines=["mihomo"]),
    _field("dns.enhanced-mode", "解析模式", "select", group="dns",
           options=[{"value": "fake-ip", "label": "fake-ip"},
                    {"value": "redir-host", "label": "redir-host"}],
           default="fake-ip", engines=["mihomo"]),
    _field("dns.fake-ip-range", "Fake-IP 网段", "text", group="dns",
           default="198.18.0.1/16", engines=["mihomo"]),
    _field("dns.default-nameserver", "引导 DNS（每行一个）", "list",
           group="dns", engines=["stash", "mihomo"]),
    _field("dns.nameserver", "主 DNS（每行一个）", "list", group="dns",
           engines=["stash", "mihomo"]),
    _field("dns.proxy-server-nameserver", "代理服务器 DNS（每行一个）", "list",
           group="dns", engines=["stash", "mihomo"]),
    _field("dns.skip-cert-verify", "跳过 DNS 证书校验", "switch", group="dns",
           engines=["stash", "mihomo"]),
    _field("dns.follow-rule", "DNS 跟随分流规则", "switch", group="dns",
           engines=["stash"]),
    _field("dns.respect-rules", "DNS 跟随分流规则", "switch", group="dns",
           engines=["mihomo"]),
    _field("dns.prefer-h3", "并发尝试 HTTP/3", "switch", group="dns",
           engines=["mihomo"]),
    _field("dns.fake-ip-filter", "不返回 Fake-IP 的域名（每行一个）", "list",
           group="dns", engines=["stash", "mihomo"]),
    # MTProto 代理（Telegram）——只在设备独立配置里用
    _field("mtproto.port", "MTProto 监听端口", "number", group="mtproto",
           default=5753, engines=["stash"]),
    _field("mtproto.secret", "MTProto 密钥（32 位十六进制）", "text",
           group="mtproto", engines=["stash"],
           placeholder="openssl rand -hex 16 生成；客户端填写时要带 dd 前缀"),
    _field("mtproto.ipv6", "只连接数据中心 IPv6", "switch", group="mtproto",
           default=False, engines=["stash"]),
    _field("mtproto.dc-config-url", "数据中心地址表来源（可选）", "text",
           group="mtproto", engines=["stash"],
           placeholder="https://example.com/mtproto-dc-config.json"),
    # 个人配置
    _field(DIRECT_DOMAINS_KEY, "个人直连域名（每行一个）", "list",
           group="personal", engines=["stash", "mihomo"],
           placeholder="例如：example.com"),
    _field(FAKE_IP_FILTER_KEY, "Fake-IP 过滤域名（每行一个）", "list",
           group="personal", engines=["stash", "mihomo"],
           placeholder="例如：+.lan 或 geosite:private"),
]


def schema(engine: str) -> list[dict]:
    return [deepcopy(f) for f in SCHEMA if engine in f.get("engines", [])]


GROUP_LABELS = {
    "basic": "基础",
    "profile": "配置文件存储",
    "dns": "DNS",
    "mtproto": "MTProto 代理（Telegram）",
    "personal": "个人配置（直连域名 / Fake-IP 过滤）",
}
