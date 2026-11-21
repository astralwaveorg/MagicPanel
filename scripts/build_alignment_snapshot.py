"""构造 MagicPanel-默认 对齐目标形态的策略快照（schema 2）。

从 before-alignment.json 出发转换：
- 默认方案（variant 0）：按 brief 目标形态重建 59 组 + 81 条规则
- 移动网络方案（variant 2）：原样保留
- rule_providers：保留新表引用 + DNS 引用的集合，新增 30 个来源，
  不再引用的旧来源 enabled=0（停用不删除，约束 35）
"""
import json
from datetime import datetime, timedelta, timezone

SRC = "policy/snapshots/2026-11-21-before-alignment.json"
OUT = "policy/snapshots/2026-11-21-target-alignment.json"
NOW = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")

snap = json.load(open(SRC, encoding="utf-8"))
GURL = "https://www.gstatic.com/generate_204"
JS = "https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@meta/geo/geosite/%s.mrs"
COR = "https://cdn.jsdelivr.net/gh/Aethersailor/Custom_OpenClash_Rules@main/rule/"

# ---------- 节点池与候选链 ----------
REGION_POOLS = {  # 名 -> filter（照抄目标模板）
    "🇭🇰 香港自动": r"(🇭🇰|港|\bHK(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|hk|Hong Kong|Hongkong|Hong kong|HongKong|hongkong|HONG KONG|HONGKONG|深港|HKG|九龙|Kowloon|新界|沙田|荃湾|葵涌)",
    "🇺🇸 美国自动": r"(🇺🇸|美|波特兰|达拉斯|俄勒冈|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥|纽约|纽纽|亚特兰大|迈阿密|华盛顿|\bUS(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|United States|UnitedStates|UNITED STATES|USA|America|AMERICA|JFK|EWR|IAD|ATL|ORD|MIA|NYC|LAX|SFO|SEA|DFW|SJC)",
    "🇯🇵 日本自动": r"(🇯🇵|日本|川日|东京|大阪|泉日|埼玉|沪日|深日|(?<!尼|-)日|\bJP(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Japan|JAPAN|JPN|NRT|HND|KIX|TYO|OSA|关西|Kansai|KANSAI)",
    "🇸🇬 新加坡自动": r"(🇸🇬|新加坡|坡|狮城|\bSG(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Singapore|SINGAPORE|SIN)",
    "🇼🇸 台湾自动": r"(🇹🇼|🇼🇸|台|新北|彰化|\bTW(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Taiwan|TAIWAN|TWN|TPE|ROC)",
    "🇰🇷 韩国自动": r"(🇰🇷|\bKR(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Korea|KOREA|KOR|首尔|韩|韓|春川|Chuncheon|ICN)",
    "🇨🇦 加拿大自动": r"(🇨🇦|加拿大|\bCA(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Canada|CANADA|CAN|渥太华|温哥华|卡尔加里|蒙特利尔|Montreal|YVR|YYZ|YUL)",
    "🇬🇧 英国自动": r"(🇬🇧|英国|Britain|United Kingdom|UNITED KINGDOM|England|伦敦|曼彻斯特|Manchester|\bUK(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|GBR|LHR|MAN)",
    "🇩🇪 德国自动": r"(🇩🇪|德国|Germany|GERMANY|\bDE(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|DEU|柏林|法兰克福|慕尼黑|Munich|MUC)",
    "🇹🇷 土耳其自动": r"(🇹🇷|土耳其|Turkey|TURKEY|Türkiye|\bTR(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|TUR|IST|ANK)",
}
OTHER_FILTER = r"(^(?!.*(港|\bHK(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|hk|Hong Kong|Hongkong|Hong kong|HongKong|hongkong|HONG KONG|HONGKONG|深港|HKG|🇭🇰|九龙|Kowloon|新界|沙田|荃湾|葵涌|美|波特兰|达拉斯|俄勒冈|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥|纽约|纽纽|亚特兰大|迈阿密|华盛顿|\bUS(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|United States|UnitedStates|UNITED STATES|USA|America|AMERICA|JFK|EWR|IAD|ATL|ORD|MIA|NYC|LAX|SFO|SEA|DFW|SJC|🇺🇸|日本|川日|东京|大阪|泉日|埼玉|沪日|深日|(?<!尼|-)日|\bJP(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Japan|JAPAN|JPN|NRT|HND|KIX|TYO|OSA|🇯🇵|关西|Kansai|KANSAI|新加坡|坡|狮城|\bSG(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Singapore|SINGAPORE|SIN|🇸🇬|台|新北|彰化|\bTW(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Taiwan|TAIWAN|TWN|TPE|ROC|🇹🇼|\bKR(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Korea|KOREA|KOR|首尔|韩|韓|春川|Chuncheon|ICN|🇰🇷|加拿大|\bCA(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|Canada|CANADA|CAN|渥太华|温哥华|卡尔加里|蒙特利尔|Montreal|YVR|YYZ|YUL|🇨🇦|英国|Britain|United Kingdom|UNITED KINGDOM|England|伦敦|曼彻斯特|Manchester|\bUK(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|GBR|LHR|MAN|🇬🇧|德国|Germany|GERMANY|\bDE(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|DEU|柏林|法兰克福|慕尼黑|Munich|MUC|🇩🇪|土耳其|Turkey|TURKEY|Türkiye|\bTR(?:[-_ ]?\d+(?:[-_ ]?[A-Za-z]{2,})?)?\b|TUR|IST|ANK|🇹🇷|家宽|家庭宽带|住宅|Residential|路由|[Ww]ire[Gg]uard|[Mm]ieru|[Jj]uicity|[Tt]ailscale)).*)"
ALL_FILTER = r"^(?!.*(路由|[Ww]ire[Gg]uard|[Mm]ieru|[Jj]uicity|[Tt]ailscale)).*"
HOME_FILTER = r"(家宽|家庭宽带|住宅|Residential)"
WG_FILTER = r"([Ww]ire[Gg]uard|[Mm]ieru|[Jj]uicity|[Tt]ailscale|路由)"
SELF_JP = r"(?=.*(日本|(?<![a-zA-Z])[jJ][pP][nN]?(?![a-zA-Z])))(?=.*自建)"
SELF_US = r"(?=.*(美国|(?<![a-zA-Z])[uU][sS][aA]?(?![a-zA-Z])))(?=.*自建)"
SELF_SG = r"(?=.*(新加坡|(?<![a-zA-Z])[sS][gG][pP]?(?![a-zA-Z])))(?=.*自建)"

REGIONS = ["🇭🇰 香港自动", "🇺🇸 美国自动", "🇯🇵 日本自动", "🇸🇬 新加坡自动",
           "🇼🇸 台湾自动", "🇰🇷 韩国自动", "🇨🇦 加拿大自动", "🇬🇧 英国自动",
           "🇩🇪 德国自动", "🇹🇷 土耳其自动"]
TAIL = [*REGIONS[3:], "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择"]  # 新加坡之后的地区链
STANDARD = ["🇭🇰 香港自动", "🇺🇸 美国自动", "🇯🇵 日本自动", "🇸🇬 新加坡自动", *TAIL]  # 13 级标准链
DIRECT_FIRST = ["🎯 全球直连", *STANDARD]
SELF_SG_US_JP = ["🇸🇬 新加坡自建测速", "🇺🇸 美国自建测速", "🇯🇵 日本自建测速"]
AI_CHAIN = ["🇺🇸 美国自建测速", "🏠 家宽自动", "🇯🇵 日本自建测速", "🇸🇬 新加坡自动",
            "🇯🇵 日本自动", "🇭🇰 香港自动", "🇺🇸 美国自动", *REGIONS[4:8],
            "🇩🇪 德国自动", "🇹🇷 土耳其自动", "🌐 其他地区自动", "♻️ 自动选择"]

# 组定义：(名称, 类型, 候选链, filter)——按客户端显示顺序排列
DEFS = [
    ("🚀 故障转移", "fallback", [*SELF_SG_US_JP, *STANDARD], ""),
    ("♻️ 自动选择", "url-test", [], ALL_FILTER),
    ("📨 Telegram", "fallback", ["🎯 全球直连", *REGIONS, "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择"], ""),
    ("🎧 Discord", "fallback", STANDARD, ""),
    ("📞 Talkatone", "fallback", STANDARD, ""),
    ("📹 Zoom", "fallback", [*STANDARD, "🎯 全球直连"], ""),
    ("💬 即时通讯", "fallback", STANDARD, ""),
    ("🌐 社交媒体", "fallback", STANDARD, ""),
    ("🚀 GitHub", "fallback", [*SELF_SG_US_JP[::-1][:1], "🇯🇵 日本自建测速", "🇺🇸 美国自建测速", *REGIONS[3:6], *STANDARD[:1], *REGIONS[4:], "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择", "🎯 全球直连"], ""),
    ("📦 容器服务", "fallback", ["🇸🇬 新加坡自建测速", "🇯🇵 日本自建测速", "🇺🇸 美国自建测速", *REGIONS[3:6], *STANDARD[:1], *REGIONS[4:], "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择", "🎯 全球直连"], ""),
    ("💻 开发者服务", "fallback", ["🇺🇸 美国自建测速", "🇯🇵 日本自建测速", *STANDARD, "🎯 全球直连"], ""),
    ("📚 学术资源", "fallback", [*STANDARD, "🎯 全球直连"], ""),
    ("🤖 ChatGPT", "fallback", AI_CHAIN, ""),
    ("🤖 Copilot", "fallback", AI_CHAIN, ""),
    ("🤖 Claude", "fallback", AI_CHAIN, ""),
    ("🤖 Grok", "fallback", AI_CHAIN, ""),
    ("🤖 国外AI服务", "fallback", AI_CHAIN, ""),
    ("🤖 国内AI服务", "select", ["🎯 全球直连", "🚀 故障转移", "♻️ 自动选择", *STANDARD], ""),
    ("🎶 TikTok", "fallback", [*SELF_SG_US_JP, *REGIONS[3:6], *STANDARD, "🏠 家宽自动", "♻️ 自动选择"], ""),
    ("🇸🇬 新加坡媒体", "select", ["🇸🇬 新加坡自建测速", "🇸🇬 新加坡自动"], ""),
    ("🎥 AppleTV+", "fallback", ["🇸🇬 新加坡自动", "🇯🇵 日本自动", *STANDARD[:1], "🇺🇸 美国自动", *REGIONS[4:], "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择"], ""),
    ("🎥 Emby", "fallback", ["🇸🇬 新加坡自动", "🇯🇵 日本自动", *STANDARD[:1], "🇺🇸 美国自动", *REGIONS[4:], "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择"], ""),
    ("🎻 Spotify", "fallback", ["🇸🇬 新加坡自动", "🇯🇵 日本自动", *STANDARD[:1], "🇺🇸 美国自动", *REGIONS[4:], "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择"], ""),
    ("📺 Bahamut", "fallback", ["🇼🇸 台湾自动", "🇭🇰 香港自动", "🚀 故障转移", "🎯 全球直连"], ""),
    ("🌎 国外媒体", "fallback", STANDARD, ""),
    ("📰 新闻资讯", "fallback", STANDARD, ""),
    ("🛒 国外电商", "fallback", STANDARD, ""),
    ("🪙 加密货币", "fallback", STANDARD, ""),
    ("🇬 谷歌服务", "fallback", ["🇺🇸 美国自建测速", "🇺🇸 美国自动", "🇸🇬 新加坡自建测速", "🇯🇵 日本自建测速", "🇯🇵 日本自动", "🇸🇬 新加坡自动", *STANDARD[:1], *REGIONS[4:], "🌐 其他地区自动", "🏠 家宽自动", "♻️ 自动选择"], ""),
    ("🍎 苹果服务", "select", DIRECT_FIRST, ""),
    ("Ⓜ️ 微软服务", "select", DIRECT_FIRST, ""),
    ("💾 OneDrive", "select", DIRECT_FIRST, ""),
    ("🎮 游戏平台", "select", ["🎯 全球直连", "🇯🇵 游戏 UDP 候选", *STANDARD], ""),
    ("💳 PayPal", "select", ["🇺🇸 美国自建测速", "🇺🇸 美国自动", "🇼🇸 台湾自动", "🇯🇵 日本自动", "🇭🇰 香港自动", "🇬🇧 英国自动", "🎯 全球直连", "♻️ 自动选择"], ""),
    ("🎮 Steam", "select", DIRECT_FIRST, ""),
    ("⏬ PT站点", "fallback", ["🎯 全球直连", *STANDARD], ""),
    ("🚀 测速工具", "select", DIRECT_FIRST, ""),
    ("🌍 国外域名", "select", ["🎯 全球直连", "🚀 故障转移", "♻️ 自动选择", *STANDARD], ""),
    ("🐟 漏网之鱼", "fallback", STANDARD, ""),
    ("🔀 非标端口", "select", ["🎯 全球直连", "🐟 漏网之鱼"], ""),
    ("🚇 WireGuard", "select", ["🎯 全球直连"], WG_FILTER),
    ("🇭🇰 香港自动", "url-test", [], REGION_POOLS["🇭🇰 香港自动"]),
    ("🇺🇸 美国自动", "url-test", [], REGION_POOLS["🇺🇸 美国自动"]),
    ("🇯🇵 日本自动", "url-test", [], REGION_POOLS["🇯🇵 日本自动"]),
    ("🇸🇬 新加坡自动", "url-test", [], REGION_POOLS["🇸🇬 新加坡自动"]),
    ("🇼🇸 台湾自动", "url-test", [], REGION_POOLS["🇼🇸 台湾自动"]),
    ("🇰🇷 韩国自动", "url-test", [], REGION_POOLS["🇰🇷 韩国自动"]),
    ("🇨🇦 加拿大自动", "url-test", [], REGION_POOLS["🇨🇦 加拿大自动"]),
    ("🇬🇧 英国自动", "url-test", [], REGION_POOLS["🇬🇧 英国自动"]),
    ("🇩🇪 德国自动", "url-test", [], REGION_POOLS["🇩🇪 德国自动"]),
    ("🇹🇷 土耳其自动", "url-test", [], REGION_POOLS["🇹🇷 土耳其自动"]),
    ("🌐 其他地区自动", "url-test", [], OTHER_FILTER),
    ("🏠 家宽自动", "url-test", [], HOME_FILTER),
    ("🇯🇵 日本自建测速", "url-test", [], SELF_JP),
    ("🇺🇸 美国自建测速", "url-test", [], SELF_US),
    ("🇸🇬 新加坡自建测速", "url-test", [], SELF_SG),
    ("🎯 全球直连", "select", ["DIRECT"], ""),
]

# 修正 GitHub 链（SE→JP→US 自建顺序写反的一处）
DEFS[8] = ("🚀 GitHub", "fallback", ["🇸🇬 新加坡自建测速", "🇯🇵 日本自建测速", "🇺🇸 美国自建测速",
           "🇸🇬 新加坡自动", "🇯🇵 日本自动", "🇺🇸 美国自动", *STANDARD, "🎯 全球直连"], "")

# ---------- 规则表 ----------
RULES = [
    ("DOMAIN-SUFFIX", "magichub.top", "DIRECT", "面板域名直连"),
    ("DOMAIN-SUFFIX", "jiek.top", "DIRECT", "面板域名直连"),
    ("DOMAIN-SUFFIX", "homehub.stream", "DIRECT", "家庭服务直连"),
    ("DOMAIN-SUFFIX", "astralwave.org", "DIRECT", "自有域名直连"),
    ("DOMAIN-SUFFIX", "233netcloud.com", "DIRECT", "自有域名直连"),
    ("DOMAIN-SUFFIX", "ghfast.top", "DIRECT", "GitHub 加速直连"),
    ("IP-CIDR", "223.5.5.5/32", "DIRECT", "国内 DoH", 1),
    ("IP-CIDR", "120.53.53.53/32", "DIRECT", "国内 DoH", 1),
    ("IP-CIDR", "185.220.197.154/32", "DIRECT", "日本自建服务器直连", 1),
    ("IP-CIDR", "192.220.75.184/32", "DIRECT", "美国自建服务器直连", 1),
    ("IP-CIDR", "152.175.65.196/32", "DIRECT", "新加坡自建服务器直连", 1),
    ("IP-CIDR", "1.1.1.1/32", "🚀 故障转移", "境外 DoH", 1),
    ("IP-CIDR", "1.0.0.1/32", "🚀 故障转移", "境外 DoH", 1),
    ("IP-CIDR", "8.8.4.4/32", "🚀 故障转移", "境外 DoH", 1),
    ("IP-CIDR", "8.8.8.8/32", "🚀 故障转移", "境外 DoH", 1),
    ("IP-CIDR", "192.168.50.0/24", "🏠 路由回家", "LVSP 路由回家", 1),
    ("IP-CIDR", "10.6.0.0/24", "🏠 路由回家", "WireGuard 网段回家", 1),
    ("DOMAIN-REGEX", r"^shidongli[^.]*\.top$", "🚀 故障转移", "机场入口防污染"),
    ("DST-PORT", "22", "DIRECT", "SSH 直连"),
    ("RULE-SET", "magic-process", "DIRECT", "本地传输进程直连"),
    ("RULE-SET", "magic-reject", "REJECT", "最小广告域（零误杀）"),
    ("RULE-SET", "connectivity-check", "DIRECT", "连通性检测直连"),
    ("RULE-SET", "dns-direct", "DIRECT", "国内 DNS 域名直连"),
    ("RULE-SET", "lvsp-direct", "DIRECT", "LVSP 设备专属直连"),
    ("RULE-SET", "private", "🎯 全球直连", "私有域名"),
    ("RULE-SET", "Custom_Direct_Domain", "🎯 全球直连", "上游收录直连域名"),
    ("RULE-SET", "Custom_Direct_Classical_IP", "🎯 全球直连", "上游收录直连 IP"),
    ("RULE-SET", "Custom_Proxy_Domain", "🚀 故障转移", "上游收录代理域名"),
    ("RULE-SET", "Custom_Proxy_Classical_IP", "🚀 故障转移", "上游收录代理 IP"),
    ("RULE-SET", "games-cn", "🎯 全球直连", "国内游戏域名"),
    ("RULE-SET", "Steam_CDN_Classical", "🎯 全球直连", "Steam 下载 CDN"),
    ("RULE-SET", "category-game-platforms-download", "🎯 全球直连", "游戏平台下载域名"),
    ("RULE-SET", "trackers", "🎯 全球直连", "BT Tracker 直连"),
    ("RULE-SET", "zoom", "📹 Zoom", "Zoom 会议"),
    ("RULE-SET", "talkatone", "📞 Talkatone", "Talkatone 通话"),
    ("RULE-SET", "telegram", "📨 Telegram", "Telegram（直连优先）"),
    ("RULE-SET", "discord", "🎧 Discord", "Discord"),
    ("RULE-SET", "category-communication", "💬 即时通讯", "通用即时通讯"),
    ("RULE-SET", "ai-cn", "🤖 国内AI服务", "国内 AI（硬校验要求早于 openai/anthropic）"),
    ("RULE-SET", "xai", "🤖 Grok", "Grok"),
    ("RULE-SET", "social", "🌐 社交媒体", "海外社交媒体"),
    ("RULE-SET", "openai", "🤖 ChatGPT", "ChatGPT"),
    ("RULE-SET", "onedrive", "💾 OneDrive", "OneDrive"),
    ("RULE-SET", "bing", "🤖 Copilot", "Copilot"),
    ("RULE-SET", "anthropic", "🤖 Claude", "Claude"),
    ("RULE-SET", "google", "🇬 谷歌服务", "谷歌全家桶（须先于国外AI）"),
    ("RULE-SET", "category-ai-!cn", "🤖 国外AI服务", "国外 AI"),
    ("RULE-SET", "docker", "📦 容器服务", "容器注册表"),
    ("RULE-SET", "category-container", "📦 容器服务", "容器服务"),
    ("RULE-SET", "github", "🚀 GitHub", "GitHub"),
    ("RULE-SET", "category-dev", "💻 开发者服务", "开发者服务"),
    ("RULE-SET", "category-scholar-!cn", "📚 学术资源", "学术资源"),
    ("RULE-SET", "category-speedtest", "🚀 测速工具", "测速工具"),
    ("RULE-SET", "steam", "🎮 Steam", "Steam"),
    ("RULE-SET", "apple-tvplus", "🎥 AppleTV+", "AppleTV+（须先于 apple）"),
    ("RULE-SET", "apple", "🍎 苹果服务", "苹果服务（默认直连）"),
    ("RULE-SET", "microsoft", "Ⓜ️ 微软服务", "微软服务（默认直连）"),
    ("RULE-SET", "tiktok", "🎶 TikTok", "TikTok（SG 自建打头）"),
    ("RULE-SET", "netflix", "🇸🇬 新加坡媒体", "Netflix"),
    ("RULE-SET", "disney", "🇸🇬 新加坡媒体", "Disney+"),
    ("RULE-SET", "hbo", "🇸🇬 新加坡媒体", "HBO Max"),
    ("RULE-SET", "primevideo", "🇸🇬 新加坡媒体", "Prime Video"),
    ("RULE-SET", "dazn", "🇸🇬 新加坡媒体", "DAZN"),
    ("RULE-SET", "viu", "🇸🇬 新加坡媒体", "Viu"),
    ("RULE-SET", "category-emby", "🎥 Emby", "Emby"),
    ("RULE-SET", "spotify", "🎻 Spotify", "Spotify"),
    ("RULE-SET", "bahamut", "📺 Bahamut", "巴哈姆特动画疯"),
    ("RULE-SET", "games", "🎮 游戏平台", "游戏平台（默认直连，UDP 池可手选）"),
    ("RULE-SET", "media", "📰 新闻资讯", "海外媒体大集合"),
    ("RULE-SET", "category-entertainment", "🌎 国外媒体", "海外娱乐"),
    ("RULE-SET", "pt-domains", "⏬ PT站点", "PT 站点域名"),
    ("RULE-SET", "paypal", "💳 PayPal", "PayPal（固定出口）"),
    ("RULE-SET", "category-ecommerce", "🛒 国外电商", "国外电商"),
    ("RULE-SET", "category-cryptocurrency", "🪙 加密货币", "加密货币"),
    ("RULE-SET", "gfw", "🚀 故障转移", "GFW 列表"),
    ("GEOIP", "telegram", "📨 Telegram", "Telegram IP 段", 1),
    ("GEOIP", "twitter", "🌐 社交媒体", "Twitter IP 段", 1),
    ("GEOIP", "facebook", "🌐 社交媒体", "Facebook IP 段", 1),
    ("GEOIP", "google", "🇬 谷歌服务", "Google IP 段", 1),
    ("RULE-SET", "geolocation-!cn", "🌍 国外域名", "未分类国外域名（默认直连）"),
    # 尾块：cn → cn-ip → direct 位 → private-ip → QUIC → MATCH（硬校验序）
    ("RULE-SET", "cn", "🎯 全球直连", "国内域名兜底"),
    ("RULE-SET", "cn-ip", "🎯 全球直连", "国内 IP 兜底"),
    ("RULE-SET", "Custom_Port_Direct", "🔀 非标端口", "非标端口直连（BT/PT）"),
    ("RULE-SET", "private-ip", "🎯 全球直连", "私网 IP"),
    ("AND", "((NETWORK,udp),(DST-PORT,443))", "REJECT", "代理链路 QUIC 回退 TCP"),
    ("MATCH", "", "🐟 漏网之鱼", "兜底"),
]

# ---------- 来源清单 ----------
V2_SETS = {r["value"] for r in snap["rules"]
           if r["variant_id"] != 0 and r["type"] == "RULE-SET"}
KEEP = {"netflix", "disney", "spotify", "telegram", "cn", "cn-ip", "private-ip", "private",
        "ai-cn", "pt", "trackers", "apple", "games", "games-cn", "steam", "tiktok", "google",
        "microsoft", "social", "category-communication", "onedrive", "github", "docker",
        "anthropic", "openai", "media", "mirror-accelerate", "dns-direct", "connectivity-check",
        "lvsp-direct", "magic-process", "magic-reject", "telegram-ip", *V2_SETS}
NEW = {
    "Custom_Direct_Domain": ("domain", "mrs", COR + "Custom_Direct_Domain.mrs"),
    "Custom_Direct_Classical_IP": ("classical", "yaml", COR + "Custom_Direct_Classical_IP.yaml"),
    "Custom_Proxy_Domain": ("domain", "mrs", COR + "Custom_Proxy_Domain.mrs"),
    "Custom_Proxy_Classical_IP": ("classical", "yaml", COR + "Custom_Proxy_Classical_IP.yaml"),
    "Steam_CDN_Classical": ("classical", "yaml", COR + "Steam_CDN_Classical.yaml"),
    "Custom_Port_Direct": ("classical", "yaml", COR + "Custom_Port_Direct.yaml"),
    "pt-domains": ("domain", "mrs", "https://raw.githubusercontent.com/FUJIWARESHINE/pt-domains/refs/heads/main/pt-domains.mrs"),
    "discord": ("domain", "mrs", JS % "discord"),
    "zoom": ("domain", "mrs", JS % "zoom"),
    "talkatone": ("domain", "mrs", JS % "talkatone"),
    "xai": ("domain", "mrs", JS % "xai"),
    "bing": ("domain", "mrs", JS % "bing"),
    "category-ai-!cn": ("domain", "mrs", JS % "category-ai-%21cn"),
    "category-container": ("domain", "mrs", JS % "category-container"),
    "category-dev": ("domain", "mrs", JS % "category-dev"),
    "category-scholar-!cn": ("domain", "mrs", JS % "category-scholar-%21cn"),
    "category-speedtest": ("domain", "mrs", JS % "category-speedtest"),
    "category-game-platforms-download": ("domain", "mrs", JS % "category-game-platforms-download"),
    "apple-tvplus": ("domain", "mrs", JS % "apple-tvplus"),
    "hbo": ("domain", "mrs", JS % "hbo"),
    "primevideo": ("domain", "mrs", JS % "primevideo"),
    "dazn": ("domain", "mrs", JS % "dazn"),
    "viu": ("domain", "mrs", JS % "viu"),
    "category-emby": ("domain", "mrs", JS % "category-emby"),
    "bahamut": ("domain", "mrs", JS % "bahamut"),
    "category-entertainment": ("domain", "mrs", JS % "category-entertainment"),
    "paypal": ("domain", "mrs", JS % "paypal"),
    "category-ecommerce": ("domain", "mrs", JS % "category-ecommerce"),
    "category-cryptocurrency": ("domain", "mrs", JS % "category-cryptocurrency"),
    "gfw": ("domain", "mrs", JS % "gfw"),
    "geolocation-!cn": ("domain", "mrs", JS % "geolocation-%21cn"),
    "steam": ("domain", "mrs", JS % "steam"),
}

# ---------- 校验 ----------
group_names = {d[0] for d in DEFS}
RESERVED = {"🇯🇵 游戏 UDP 候选", "🏠 路由回家"}
known = group_names | RESERVED | {"DIRECT", "REJECT", "REJECT-DROP"}
problems = []
for name, gtype, chain, _f in DEFS:
    for ref in chain:
        if ref not in known:
            problems.append(f"{name} 引用不存在的组 {ref}")
rules_targets = group_names | RESERVED | {"DIRECT", "REJECT"}
for r in RULES:
    if r[2] not in rules_targets and r[2] not in {"🏠 路由回家"}:
        problems.append(f"规则 {r[0]},{r[1]} 目标组不存在 {r[2]}")
if problems:
    raise SystemExit("引用校验失败：\n" + "\n".join(problems))
used_sets = {r[1] for r in RULES if r[0] == "RULE-SET"}
missing_sets = used_sets - set(KEEP) - set(NEW)
if missing_sets:
    raise SystemExit("规则引用了未定义来源：" + str(missing_sets))

# ---------- 生成 ----------
gid = 1000
groups = []
for idx, (name, gtype, chain, filt) in enumerate(DEFS):
    use = '["*"]' if (filt or name.endswith("自动") or "自建测速" in name or name == "♻️ 自动选择") else "[]"
    groups.append({
        "id": gid, "variant_id": 0, "name": name, "type": gtype, "sort": idx,
        "hidden": 0, "filter": filt, "use_sources": use, "local_nodes": "[]",
        "proxies": json.dumps(chain, ensure_ascii=False), "url": GURL,
        "interval": 300, "timeout": 8000, "tolerance": 50, "lazy": 1,
        "strategy": "", "local_first": 0, "targets": '["*"]', "devices": '["*"]',
        "members_v2": "[]", "members_format": "legacy",
        "created_at": NOW, "updated_at": NOW,
    })
    gid += 1
# 保留组：游戏 UDP 池（机制保留）与路由回家（LVSP 专属）——从原快照搬运
for src in snap["proxy_groups"]:
    if src["variant_id"] == 0 and src["name"] in ("🇯🇵 游戏 UDP 候选", "🏠 路由回家"):
        row = dict(src)
        if row["name"] == "🏠 路由回家":
            # 旧成员引用已改名的本地节点，统一为 DIRECT + 本地 WireGuard 节点
            row["proxies"] = json.dumps(["DIRECT", "🏠 WireGuard [LVSP] (本地)"], ensure_ascii=False)
            row["members_v2"] = "[]"
            row["members_format"] = "legacy"
        row["id"] = gid
        row["sort"] = len(groups)
        row["created_at"] = row["updated_at"] = NOW
        groups.append(row)
        gid += 1

rid = 2000
rules = []
for idx, r in enumerate(RULES):
    rtype, value, target, note = r[0], r[1], r[2], r[3]
    no_resolve = r[4] if len(r) > 4 else 0
    rules.append({
        "id": rid, "variant_id": 0, "sort": idx, "type": rtype, "value": value,
        "target": target, "enabled": 1, "note": note,
        "created_at": NOW, "updated_at": NOW, "no_resolve": no_resolve,
        "targets": '["*"]', "devices": '["*"]', "no_track": 0, "pre_matching": 0,
    })
    rid += 1

# 来源：保留 + 停用 + 新增
old_providers = {p["name"]: p for p in snap["rule_providers"]}
providers = []
pid = max(p["id"] for p in old_providers.values()) + 10
for name, p in sorted(old_providers.items()):
    row = dict(p)
    if name in KEEP:
        row["enabled"] = 1
    elif name in NEW:
        continue  # 新表重建
    else:
        row["enabled"] = 0
    # 导入按第一行的键构造 INSERT 列集：所有行统一字段集，缺 created_at 会触发 NOT NULL 失败
    row.setdefault("created_at", NOW)
    row["updated_at"] = NOW
    providers.append(row)
for name, (behavior, fmt, url) in sorted(NEW.items()):
    providers.append({
        "id": pid, "name": name, "behavior": behavior, "format": fmt, "kind": "remote",
        "url": url, "repo_path": "", "inline_content": "", "interval": 86400,
        "client_interval": 21600, "enabled": 1,
        "created_at": NOW, "updated_at": NOW,
    })
    pid += 1

v2_groups = [g for g in snap["proxy_groups"] if g["variant_id"] != 0]
v2_rules = [r for r in snap["rules"] if r["variant_id"] != 0]
snap["proxy_groups"] = groups + v2_groups
snap["rules"] = rules + v2_rules
snap["rule_providers"] = providers
snap["meta"] = {"build_id": 0, "build_status": "target", "verify_status": "target",
                "policy_sha": "", "build_created_at": NOW}
snap["exported_at"] = NOW
import hashlib
canonical = json.dumps({k: v for k, v in snap.items() if k != "digest"},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":"))
snap["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
json.dump(snap, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"组 {len(groups)}（默认方案 {len(DEFS)} + 保留 {len(groups)-len(DEFS)}）")
print(f"规则 {len(rules)} 条（默认方案）")
print(f"来源 {len(providers)}（启用 {sum(1 for p in providers if p['enabled'])} / 停用 {sum(1 for p in providers if not p['enabled'])}）")
v2g = sum(1 for g in snap["proxy_groups"] if g["variant_id"] != 0)
v2r = sum(1 for r in snap["rules"] if r["variant_id"] != 0)
print(f"移动网络方案保留：组 {v2g} 规则 {v2r}")
