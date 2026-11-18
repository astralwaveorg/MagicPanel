"""节点名称规范化（Sub-Store 风格）：机场订阅的节点名千奇百怪——
有中英混杂、有超长宣传语、有「剩余流量」这类占位节点。构建与分发时统一
成「旗帜 [机场·标签] 国名 徽章 序号」的确定性格式，客户端里看起来整齐划一。

    🇺🇸 [神龙机场·IEPL] 美国 🔓 01     ← 开启解锁徽章且该节点 AI 全解锁
    🇺🇸 [神龙机场] 美国 01            ← 常态

机场提前：客户端按名字排序时同一机场的节点自然聚拢，方便对照管理。

设计约束：
* 确定性：同一个名字在同一个来源批次里永远得到同一个结果（序号按出现顺序分配），
  客户端拉两次 feed 得到一致的名称，不会随机抖动。
* 地区关键词保留：策略组的过滤正则靠 🇺🇸/美国/Japan 这类 token 匹配节点，
  规范化后的名字必须仍然包含「旗帜 + 中文国名」，否则地区组会失配。
* 徽章单向变化（2026-11-18）：解锁徽章只有「AI 全部解锁」时才加，未测与
  被拒都不加——名字只会从无徽章变有徽章，不会来回抖动；解锁状态易变，
  编进名字的必须是单向的、稳定的信息，否则客户端节点身份跟着抖。
* 测速结果不受影响：测速以原始节点名为键，规范化只发生在产物/分发出口，
  原始名 → 新名的映射不会回写数据库。
"""
import re

# 解锁能力徽章（由调用方按检测缓存判定后传入，可组合）：
#   🔓 AI 六项全解锁     🎬 流媒体主项全解锁     📺 Netflix 高级版目录可达
# 徽章单向变化：未测与被拒都不加，节点名不会因检测结果抖动而来回变。
UNLOCK_BADGE = "🔓"
STREAM_BADGE = "🎬"
NETFLIX_PREMIUM_BADGE = "📺"

# 占位/信息节点：对分流毫无意义（server 都不是真实节点），构建与分发时直接丢弃
INFO_NODE_PATTERN = re.compile(
    r"剩余流量|套餐到期|到期时间|距离下次|重置剩余|订阅提醒|官网|官方网站|"
    r"expire|traffic|valid until|subscription", re.IGNORECASE)

# 提示型节点：名字就是一个网址（机场的"加速页/公告页"占位），
# 2026-11-19 实测遇到「📢大陆加速:shenlong66.com」——它不是可用的出口，
# 留在产物里会占位、也会被漏斗反复探测。
# 提示型节点的名字通常以网址结尾（前缀可有 emoji、冒号、中文说明）
INFO_DOMAIN_PATTERN = re.compile(
    r"[a-z0-9\-]{2,}\.(?:com|net|org|top|xyz|cc|cn|io|co|me|info)$",
    re.IGNORECASE)

# 地区识别表：按顺序首个命中的生效。英文与缩写都用词边界，避免
# "IEPL" 里的 PL、"RUSsia" 里的 US 这类误伤。
_REGIONS = (
    (r"🇹🇼|台湾|臺灣|tw\b|taiwan", "🇹🇼", "台湾"),
    (r"🇭🇰|香港|\bhk\b|hkg\b|hong ?kong", "🇭🇰", "香港"),
    (r"🇯🇵|日本|日馆|jp\b|japan|tokyo|东京|東京|大阪|osaka", "🇯🇵", "日本"),
    (r"🇸🇬|新加坡|sg\b|singapore", "🇸🇬", "新加坡"),
    (r"🇰🇷|韩国|韓國|kr\b|korea|seoul|首尔|首爾", "🇰🇷", "韩国"),
    (r"🇺🇸|美国|美國|us\b|u\.s\.|usa|united states|america|los angeles|圣何塞|聖何塞|seattle|西雅图|西雅圖|portland", "🇺🇸", "美国"),
    (r"🇨🇦|加拿大|canada|\bca\b|ottawa|toronto|温哥华|溫哥華", "🇨🇦", "加拿大"),
    (r"🇬🇧|英国|英國|\buk\b|\bgb\b|britain|london|伦敦|倫敦", "🇬🇧", "英国"),
    (r"🇩🇪|德国|德國|\bde\b|germany|frankfurt|法兰克福|法蘭克福", "🇩🇪", "德国"),
    (r"🇫🇷|法国|法國|\bfr\b|france|paris|巴黎", "🇫🇷", "法国"),
    (r"🇳🇱|荷兰|荷蘭|\bnl\b|amsterdam|阿姆斯特丹", "🇳🇱", "荷兰"),
    (r"🇹🇷|土耳其|\btr\b|istanbul|伊斯坦布尔|伊斯坦布爾", "🇹🇷", "土耳其"),
    (r"🇷🇺|俄罗斯|俄羅斯|\bru\b|moscow|莫斯科", "🇷🇺", "俄罗斯"),
    (r"🇦🇺|澳大利亚|澳洲|\bau\b|australia|sydney|悉尼", "🇦🇺", "澳大利亚"),
    (r"🇮🇳|印度|\bin\b|india|mumbai|孟买|孟買", "🇮🇳", "印度"),
    (r"🇧🇷|巴西|\bbr\b|brazil|sao paulo", "🇧🇷", "巴西"),
    (r"🇦🇷|阿根廷|\bar\b|argentina", "🇦🇷", "阿根廷"),
    (r"🇲🇾|马来西亚|馬來西亞|\bmy\b|malaysia|kuala", "🇲🇾", "马来西亚"),
    (r"🇹🇭|泰国|泰國|\bth\b|thailand|bangkok|曼谷", "🇹🇭", "泰国"),
    (r"🇻🇳|越南|\bvn\b|vietnam|hanoi|河内", "🇻🇳", "越南"),
    (r"🇵🇭|菲律宾|菲律賓|\bph\b|philippines|manila", "🇵🇭", "菲律宾"),
    (r"🇮🇩|印尼|印度尼西亚|\bid\b|indonesia|jakarta", "🇮🇩", "印尼"),
    (r"🇮🇹|意大利|義大利|\bit\b|italy|milan|米兰|米蘭", "🇮🇹", "意大利"),
    (r"🇪🇸|西班牙|\bes\b|spain|madrid|马德里|馬德里", "🇪🇸", "西班牙"),
    (r"🇸🇪|瑞典|\bse\b|sweden|stockholm", "🇸🇪", "瑞典"),
    (r"🇨🇭|瑞士|\bch\b|switzerland|zurich", "🇨🇭", "瑞士"),
    (r"🇳🇴|挪威|\bno\b|norway|oslo", "🇳🇴", "挪威"),
    (r"🇫🇮|芬兰|芬蘭|\bfi\b|finland|helsinki", "🇫🇮", "芬兰"),
    (r"🇵🇱|波兰|波蘭|\bpl\b|poland|warsaw", "🇵🇱", "波兰"),
    (r"🇪🇺|欧洲|歐洲|\beu\b|europe", "🌍", "欧洲"),
)
_REGION_COMPILED = [(re.compile(p, re.IGNORECASE), flag, cn) for p, flag, cn in _REGIONS]

# 附加标签：倍率 / 家宽 / 专线 / 运营商
_MULTIPLIER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[xX倍]")
_HOME_PATTERN = re.compile(r"家宽|家寬|家庭宽带|住宅|宽带|\bhome\b|\bisp\b", re.IGNORECASE)
_IEPL_PATTERN = re.compile(r"iepl|iplc|专线|專線", re.IGNORECASE)
_CARRIER_PATTERN = re.compile(r"(移动|移動|cmcc|china mobile|联通|聯通|unicom|电信|電信|telecom)")


def is_info_node(name: str) -> bool:
    """「剩余流量」「套餐到期」这类占位节点，不进产物。"""
    return bool(INFO_NODE_PATTERN.search(name or ""))


def is_prompt_node(name: str) -> bool:
    """提示型节点：名字就是一个网址（机场的加速页/公告页占位）。"""
    text = (name or "").strip()
    return bool(text) and bool(INFO_DOMAIN_PATTERN.search(text))


def _extract_multiplier(name: str) -> str | None:
    m = _MULTIPLIER_PATTERN.search(name)
    if not m:
        return None
    value = m.group(1)
    return f"{float(value):g}x"


def detect_region(name: str) -> tuple[str, str] | None:
    text = name or ""
    for pattern, flag, cn in _REGION_COMPILED:
        if pattern.search(text):
            return flag, cn
    return None


def normalize_name(name: str, source: str = "", alloc: dict | None = None,
                   badge: str = "", speed_bps: int = 0, delay_ms: int = -1) -> str | None:
    """规范化单个节点名。

    返回 None 表示这是占位/信息节点，应从产物与分发中丢弃。
    alloc 是 (旗帜, 地区, 家宽) → 下一个序号 的分配表，调用方对同一批次
    传入同一个 dict，序号才会按出现顺序稳定递增。
    badge 是能力徽章串（可为空，如 "🔓🎬"）：调用方按解锁检测缓存判定。
    speed_bps / delay_ms 是质量漏斗的结果（0 / -1 表示没有数据）：
    有数据时在名字末尾追加「120M/45ms」这样的摘要。
    """
    name = (name or "").strip()
    if not name:
        return None
    if is_info_node(name):
        return None
    region = detect_region(name)
    home = bool(_HOME_PATTERN.search(name))
    multiplier = _extract_multiplier(name)
    tags = []
    if _IEPL_PATTERN.search(name):
        tags.append("IEPL")
    carrier = _CARRIER_PATTERN.search(name)
    if carrier:
        tags.append(carrier.group(1))
    if not region:
        # 识别不出地区：保留原名（清理多余空白），保证确定性
        cleaned = re.sub(r"\s+", " ", name)
        return cleaned
    flag, cn = region
    region_name = cn + ("家宽" if home else "")
    key = (flag, region_name)
    if alloc is None:
        alloc = {}
    seq = alloc.get(key, 0) + 1
    alloc[key] = seq
    # 机场·标签 提前：同一机场的节点在客户端按名排序时聚在一起
    bracket = ""
    if source or tags:
        if multiplier:
            tags.insert(0, multiplier)
        if source:
            tags.append(source)
        bracket = " [" + "·".join(tags) + "]"
    label = f"{flag}{bracket} {region_name}"
    if badge:
        # 兼容旧的布尔语义：True 表示「有 AI 徽章」
        badge_text = UNLOCK_BADGE if badge is True else str(badge)
        if badge_text:
            label += f" {badge_text}"
    label += f" {seq:02d}"
    # 质量摘要：吞吐(MB/s) / 延迟(ms)，都没有就不加这一段
    perf = ""
    if speed_bps and speed_bps > 0:
        perf = f"{int(speed_bps / 1024 / 1024)}M"
    if delay_ms is not None and delay_ms >= 0:
        perf = f"{perf}/{delay_ms}ms" if perf else f"{delay_ms}ms"
    if perf:
        label += f" {perf}"
    return label


def rename_batch(names: list[str], source: str = "",
                 badge_lookup=None, perf_lookup=None) -> dict[str, str | None]:
    """对一批节点名做规范化，返回 {原名: 新名或 None}。

    None 表示占位节点应丢弃。批内序号按列表出现顺序分配；
    重复出现的原名只分配一次（首个生效），保证同名节点映射一致。
    badge_lookup(原始名) → 徽章串（可为空）：能力徽章判定（调用方按 unlock 缓存判）。
    兼容旧的布尔返回：True 视为单独的 AI 徽章。
    """
    alloc: dict = {}
    result: dict[str, str | None] = {}
    for name in names:
        if name in result:
            continue
        badge = ""
        if badge_lookup:
            raw = badge_lookup(name)
            badge = UNLOCK_BADGE if raw is True else (str(raw) if raw else "")
        speed_bps = 0
        delay_ms = -1
        if perf_lookup:
            perf = perf_lookup(name) or {}
            speed_bps = int(perf.get("speed_bps") or 0)
            delay_ms = int(perf.get("delay_ms", -1))
        result[name] = normalize_name(name, source=source, alloc=alloc, badge=badge,
                                       speed_bps=speed_bps, delay_ms=delay_ms)
    return result


def normalize_snapshot(snapshot_text: str, source: str = "",
                       badge_lookup=None) -> str:
    """规范化 provider 快照 YAML：重命名节点并丢弃占位节点。

    仅当开关开启时由分发端调用；内容不可解析时原样返回，不阻断分发。
    badge_lookup 见 rename_batch。
    """
    import yaml

    try:
        data = yaml.safe_load(snapshot_text)
    except Exception:
        return snapshot_text
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        return snapshot_text
    mapping = rename_batch(
        [str(p.get("name") or "") for p in data["proxies"] if isinstance(p, dict)],
        source=source,
        badge_lookup=badge_lookup,
    )
    kept = []
    for p in data["proxies"]:
        if not isinstance(p, dict):
            continue
        new = mapping.get(str(p.get("name") or ""))
        if new is None:
            continue
        p["name"] = new
        kept.append(p)
    data["proxies"] = kept
    try:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096)
    except Exception:
        return snapshot_text
