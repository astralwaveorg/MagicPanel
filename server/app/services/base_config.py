"""产物基础配置：多级联动的顶层键文档。

层级（后者覆盖前者）：
① 内置默认：随程序发布，只读可见（按引擎）；
② 通用配置：按「引擎 + 平台」维护（与"引擎平台"一一对应，如 Stash · macOS）；
③ 设备专属：按设备维护，只对该设备的最终配置生效。

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

# 结构化内容由业务页面维护，基础配置与目标扩展都不允许覆盖
PROTECTED_KEYS = {
    "proxies": "节点由“节点来源 / 本地单节点”维护",
    "proxy-providers": "远程代理集由“节点来源”维护",
    "proxy-groups": "策略组由“策略组”页维护",
    "rule-providers": "规则集合由“规则来源”维护",
    "rules": "分流规则由“分流规则”页维护",
}

# 设备专属作用域额外禁止的键：控制面相关。
# 设备层只用于"这台设备的个性化"，写上对外控制端口等于
# 把管理接口暴露到局域网，客户端侧也没有对应的鉴权配置。
DEVICE_FORBIDDEN_KEYS = {
    "external-controller": "设备专属配置不能开启对外控制端口",
    "external-ui": "设备专属配置不能指定外部控制器界面",
    "secret": "设备专属配置不能设置控制端口密钥",
    "listeners": "设备专属配置不能新增监听器",
    "tun": "设备专属配置不能开启 TUN",
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

# Stash 官方精简：只保留官方有文档的顶层键
STASH_OFFICIAL = {
    "mode": "rule",
    "log-level": "warning",
    "ipv6": False,
    PANEL_DIRECT_KEY: True,
}

# 兼容现状（含 Clash 端口与 profile 段）
COMPAT = {
    "mixed-port": 7890,
    "allow-lan": False,
    "mode": "rule",
    "log-level": "warning",
    "ipv6": False,
    "profile": {"store-selected": True, "store-fake-ip": True},
    PANEL_DIRECT_KEY: True,
}

PRESETS = {
    "stash": {
        "official": ("Stash 官方精简", deepcopy(STASH_OFFICIAL)),
        "compat": ("兼容现状（含端口与 profile）", deepcopy(COMPAT)),
    },
    "mihomo": {
        "compat": ("Mihomo 现状", deepcopy(COMPAT)),
        "official": ("Mihomo 官方精简", {
            "mode": "rule",
            "log-level": "warning",
            "ipv6": False,
            PANEL_DIRECT_KEY: True,
        }),
    },
}

DEFAULT_ENGINE = "stash"


def default_doc(engine: str) -> dict:
    key = "official" if engine == "stash" else "compat"
    return deepcopy(PRESETS[engine][key][1])


# ---- 多级联动：合并、差异、来源 ----

# 多级联动的合并策略（用成熟库 deepmerge 实现，避免手写合并出纰漏）：
# - 字典：递归合并（并集，逐键覆盖）
# - 列表：整体替换（不拼接，避免配置语义含糊）
# - 标量 / 类型冲突：后者覆盖前者
_MERGER = Merger(
    [(list, ListStrategy.ListStrategies.strategy_override),
     (dict, DictStrategy.DictStrategies.strategy_merge)],
    FallbackStrategy.FallbackStrategies.strategy_override,
    TypeConflictStrategy.TypeConflictStrategies.strategy_override,
)


def merge_docs(base: dict, overlay: dict) -> dict:
    """合并一层覆盖：键级并集，同键后者覆盖前者。

    字典递归合并、列表整体替换、标量覆盖——语义由 deepmerge 的策略显式声明。
    """
    if not overlay:
        return deepcopy(base or {})
    if not base:
        return deepcopy(overlay)
    return _MERGER.merge(deepcopy(base), deepcopy(overlay))


def diff_overlay(base: dict, effective: dict) -> dict:
    """比较"上层生效值"与"本层编辑后的值"，得出本层真正需要覆盖的差异。

    字典递归比较，列表整体比较；相同则不写入本层（保持"跟随上层"）。
    """
    overlay: dict = {}
    for key, value in (effective or {}).items():
        if key not in (base or {}):
            overlay[key] = deepcopy(value)
            continue
        old = base[key]
        if isinstance(value, dict) and isinstance(old, dict):
            sub = diff_overlay(old, value)
            if sub:
                overlay[key] = sub
        elif value != old:
            overlay[key] = deepcopy(value)
    return overlay


def cascade(layers: list[tuple[str, dict]]) -> tuple[dict, dict]:
    """按层级顺序合并，返回 (生效文档, 每个键的来源层级)。

    layers 形如 [("内置默认", {...}), ("通用配置", {...}), ("设备专属", {...})]，
    来源记录到最后一次改写该键的层（顶层键粒度），便于界面展示"这个值来自哪一层"。
    """
    effective: dict = {}
    sources: dict = {}
    for label, doc in layers:
        for key, value in (doc or {}).items():
            if isinstance(value, dict) and isinstance(effective.get(key), dict):
                effective[key] = merge_docs(effective[key], value)
            else:
                effective[key] = deepcopy(value)
            # 后面的层级优先：来源记录最后一次改写该键的层
            sources[key] = label
    return effective, sources


def leaf_sources(layers: list[tuple[str, dict]]) -> dict[str, str]:
    """每个叶子路径的来源层级（点号路径，如 "dns.nameserver"）。

    顶层来源不足以说明"dns 里的 nameserver 来自哪一层"——通用配置改了
    dns.nameserver、内置默认改了 dns.enable，两者来源不同。界面按叶子
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
    """按作用域取出各层文档（从低到高：内置默认 → 通用配置 → 设备专属）。

    返回的列表**包含当前作用域自己那一层**，因此：
    - layers[:-1] 是当前层的"继承值"（上层合并结果）；
    - layers 是完整链路，合并结果即"生效值"。

    内置默认本身也可以被覆盖：用户改的是"出厂值之上的差异"，
    差异存在 (engine, "", 0) 这条记录里；不覆盖时就是源码里的出厂值，
    随时可以删掉这条记录恢复出厂。
    """
    docs = docs or {}
    # 出厂值 = 源码内置内容 + 用户对出厂值的覆盖（存 (engine, "", 0)）
    base = deepcopy(default_doc(engine))
    override = docs.get((engine, "", 0))
    if override:
        base = merge_docs(base, override)
    layers: list[tuple[str, dict]] = [("内置默认", base)]
    if platform:
        # 当前作用域自己那一层始终参与（没有覆盖时为空层），
        # 这样 layers[:-1] 才是"继承自上层的值"。
        layers.append(("通用配置", deepcopy(docs.get((engine, platform, 0)) or {})))
    if device_id:
        layers.append(("设备专属", deepcopy(docs.get((engine, platform, int(device_id))) or {})))
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


def validate_doc(doc: dict, device_scope: bool = False) -> None:
    """校验基础配置；不合法时抛 ValueError（中文提示）。"""
    for key in doc:
        if key in PROTECTED_KEYS:
            raise ValueError(f"基础配置不能包含“{key}”：{PROTECTED_KEYS[key]}")
        if device_scope and key in DEVICE_FORBIDDEN_KEYS:
            raise ValueError(DEVICE_FORBIDDEN_KEYS[key])
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
    "personal": "个人配置（直连域名 / Fake-IP 过滤）",
}
