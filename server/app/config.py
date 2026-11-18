"""运行路径与全局常量。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # server/
DATA_DIR = Path(os.environ.get(
    "MAGICPANEL_DATA_DIR", BASE_DIR.parent / "data"
)).resolve()                                                 # 运行数据目录，可用环境变量覆盖
BUILDS_DIR = DATA_DIR / "builds"
DB_PATH = DATA_DIR / "magicpanel.db"
SECRET_KEY_PATH = DATA_DIR / "secret.key"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 专有名词展示（大小写必须规范）
ENGINE_LABELS = {"stash": "Stash", "mihomo": "Mihomo"}
PLATFORM_LABELS = {
    "ios": "iOS", "macos": "macOS", "tvos": "tvOS", "windows": "Windows",
    "android": "Android", "linux": "Linux",
}

GUARD_PROXY = "空组保护"           # 永远无法出站的占位节点，防止空策略组被客户端隐式改写
BUILTIN_TARGETS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "GLOBAL"}
# 节点来源的两种下发方式：
#   provider —— 写进产物的 proxy-providers 段，客户端按 interval 自己拉取更新；
#   inline   —— 节点写进产物顶层 proxies，客户端不再下载 provider。
# 内联的好处是节点会进 GLOBAL 组（Clash/Stash 的 GLOBAL 只收顶层 proxies
# 与策略组，provider 里的节点进不去）；代价是机场换节点后要重拉订阅才生效。
SOURCE_MODE_PROVIDER = "provider"
SOURCE_MODE_INLINE = "inline"
SOURCE_MODES = (SOURCE_MODE_PROVIDER, SOURCE_MODE_INLINE)
# 健康检查地址：节点延迟测试、策略组测速、界面默认值共用同一处。
# 各写一份的话，改了其中一处就会出现"测速地址和实际测速不一致"。
HEALTH_CHECK_URL = "https://www.gstatic.com/generate_204"
# MRS（MetaCubeX 的二进制规则集）：内容按字节处理，存库时 base64 编码，
# 下发时还原成二进制。条目数无法从文件里数出来，只能留空。
MRS_FORMAT = "mrs"
BINARY_FORMATS = {MRS_FORMAT}
# 「包含所有」哨兵：多选列表里放这个值表示"全部"（节点来源 = 所有来源，
# 含以后新增的；引擎平台 / 设备 = 全部）。
ALL_SCOPE = "*"
MAX_CHECK_INTERVAL = 604800  # 周检测显式上限；300秒哨兵由运行合同单独控制
GROUP_TYPES = {"select", "url-test", "fallback", "load-balance", "relay"}
LB_STRATEGIES = {"consistent-hashing", "round-robin", "sticky-sessions"}
RULE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX",
    "IP-CIDR", "IP-CIDR6", "GEOIP", "GEOSITE", "RULE-SET",
    "SRC-IP-CIDR", "DST-PORT", "PROCESS-NAME", "MATCH", "FINAL",
    # 逻辑规则：QUIC 兼容层用（AND,((NETWORK,udp),(DST-PORT,443)),REJECT，
    # 排在 MATCH 前：只拦"本来就要走代理"的 QUIC，国内直连流量不受影响）
    "AND",
    # FINAL 是 MATCH 的旧写法（2026-11-18 收进白名单）：编译器校验、
    # 兜底排序与历史数据都按兜底处理它，创建接口却拒绝，属"幽灵类型"
}
# 各引擎官方支持的规则类型（超出白名单的类型在产物里会导致客户端加载失败）
# 依据：Stash https://stash.wiki/rules/rule-types ；
#        Mihomo https://wiki.metacubex.one/config/rules/
STASH_RULE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD", "DOMAIN-REGEX",
    "GEOIP", "GEOSITE", "IP-CIDR", "IP-CIDR6", "IP-ASN", "DST-PORT", "SRC-IP",
    "SRC-PORT", "NETWORK", "PROTOCOL", "USER-AGENT", "URL-REGEX", "RULE-SET",
    "PROCESS-NAME", "PROCESS-PATH", "AND", "OR", "NOT", "SCRIPT", "MATCH",
}
MIHOMO_RULE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD", "DOMAIN-REGEX",
    "GEOIP", "GEOSITE", "IP-CIDR", "IP-CIDR6", "IP-SUFFIX", "IP-ASN", "SRC-IP",
    "SRC-IP-CIDR", "SRC-IP-SUFFIX", "SRC-IP-ASN", "SRC-GEOIP", "DST-PORT", "SRC-PORT",
    "IN-PORT", "IN-TYPE", "IN-USER", "IN-NAME", "NETWORK", "DSCP", "RULE-SET",
    "PROCESS-NAME", "PROCESS-PATH", "PROCESS-NAME-WILDCARD", "PROCESS-NAME-REGEX",
    "PROCESS-PATH-WILDCARD", "PROCESS-PATH-REGEX", "UID", "AND", "OR", "NOT",
    "SUB-RULE", "MATCH",
}
ENGINE_RULE_TYPES = {"stash": STASH_RULE_TYPES, "mihomo": MIHOMO_RULE_TYPES}

# 允许附加 no-resolve 修饰符的规则类型（IP 字面量匹配，不触发域名解析）
NO_RESOLVE_TYPES = {"IP-CIDR", "IP-CIDR6", "GEOIP", "RULE-SET", "SRC-IP-CIDR"}
# Stash 专属修饰符 pre-matching：让 REJECT 在连接建立之前生效。
# 官方原文：只能用在"连接建立前就能判断"的规则类型上，
# PROCESS-NAME / PROCESS-PATH / USER-AGENT / URL-REGEX / PROTOCOL / SCRIPT 带它会报错。
PRE_MATCHING_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD", "DOMAIN-REGEX",
    "GEOSITE", "IP-CIDR", "IP-CIDR6", "GEOIP", "IP-ASN", "DST-PORT", "SRC-IP",
    "SRC-PORT", "NETWORK", "RULE-SET", "AND", "OR", "NOT",
}
# pre-matching 的目标只能是这两个字面量；用策略组会让客户端配置加载失败
PRE_MATCHING_TARGETS = {"REJECT", "REJECT-DROP"}
# 分流方案（variants）：0 = 默认方案（迁移播种，is_system 保护）。
# 方案 N 的组/规则 sort 占 [N*10000, (N+1)*10000) 一段，各方案拖拽排序
# 互不干扰，也保证默认方案的 sort 值永不被新方案改动（AGENTS 约束 27/28）。
DEFAULT_VARIANT_ID = 0
VARIANT_SORT_STRIDE = 10000
# 方案名会拼进产物文件名（{target}@方案.yaml），禁文件名不安全字符
VARIANT_NAME_FORBIDDEN = set('@/\\:*?"<>|')
TOKEN_PREFIX = "mp_"
DEFAULT_UA = "Stash"
FETCH_MAX_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT = 20.0
SESSION_TTL_HOURS = 168
# 内置调度器：单进程后台任务，随应用启动；测试环境用 MAGICPANEL_SCHEDULER=0 关闭
SCHEDULER_AUTOSTART = os.environ.get("MAGICPANEL_SCHEDULER", "1") != "0"
# 是否信任反代注入的 X-Forwarded-For（2026-11-18 安全修复）。
# 生产部署在 OpenResty 后面时设 MAGICPANEL_TRUST_PROXY=1（反代是追加式，
# 取最后一段才是真实客户端）；直连部署保持 0——否则攻击者自带随机 XFF
# 就能轮换"IP"绕过登录与门户 PIN 的限流。
TRUST_PROXY = os.environ.get("MAGICPANEL_TRUST_PROXY", "0") == "1"
SCHEDULER_TICK_SECONDS = max(10, int(os.environ.get("MAGICPANEL_SCHEDULER_TICK", "30")))
RELEASE_HISTORY_LIMIT = 20       # 发布历史只保留最近 20 条（每日两次约 10 天）
# 磁盘留存策略：构建产物与审计日志都会随时间增长，NAS 磁盘有限，必须有上限。
BUILD_ARTIFACT_KEEP = 30        # 保留最近 30 个「从未发布过」的构建及其产物
PUBLISHED_BUILD_KEEP = 20       # 曾发布过的构建只保留最近 20 个，更早的彻底清理
AUDIT_LOG_KEEP = 20000          # 审计日志最多保留 2 万行

SETTINGS_DEFAULTS = {
    "base_url": "",                 # 对外基础地址，如 https://panel.example.com
    "session_ttl_hours": str(SESSION_TTL_HOURS),
    "profile_update_interval": "1",  # 小时，写入响应头 profile-update-interval
    # 内置定时任务
    "scheduler_enabled": "1",
    "auto_fetch_sources": "1",
    "auto_fetch_rules": "1",
    "auto_test_sources": "0",
    "auto_build_enabled": "1",
    "auto_build_interval_hours": "1",
    "auto_publish_enabled": "1",
    "auto_publish_env": "production",   # production / testing
    "auto_build_last_attempt": "",      # 内部：上次自动构建检查时间
    "auto_build_fail_count": "0",       # 内部：发布连续失败次数（指数退避）
    "auto_build_backoff_until": "",     # 内部：发布退避截止时间（ISO）
    "auto_fetch_snippets": "1",         # 抓取远程拓展模块（原漏播种，设置页看不到开关却默认开启）
    "node_name_unlock_badge": "0",      # 节点名加解锁徽章 🔓（AI 全解锁才加，单向变化）
    "unlock_batch_auto": "0",           # 调度器自动轮转批量检测节点解锁（每 tick 一小批）
    "unlock_batch_size": "3",           # 每批检测节点数
    "unlock_batch_cursor": "0",         # 内部：批量检测轮转游标
    "probe_funnel_enabled": "0",        # 周期性质量漏斗（延迟→吞吐→解锁，默认关）
    "probe_max_delay_ms": "600",        # 一级门禁：延迟上限（毫秒）
    "probe_min_speed_bps": "2097152",   # 二级门禁：吞吐下限（2MB/s）
    "probe_speed_bytes": "5242880",     # 测速文件大小（5MB）
    "probe_timeout_ms": "8000",         # 单请求超时
    "probe_concurrency": "4",           # 探测并发
    "probe_round_limit": "200",         # 单轮最多探测节点数
    "probe_retry": "1",                 # 重试次数（仅超时/5xx）
    "backup_include_runtime": "0",      # 备份是否含 mihomo 核心与 geo 数据（默认关：归档会 150MB+ 超上传上限）
    "backup_include_history_builds": "0",  # 备份是否含历史构建产物（默认关：体积大且历史产物随时会被留存清理）
    # 自主维护：依赖文件库（单仓库）
    "deps_enabled": "0",
    "deps_url": "git@github.com:astralwaveorg/magic-sets.git",
    "deps_branch": "main",
    "deps_auth": "ssh",                 # ssh / https / none
    "deps_private_key_enc": "",         # Fernet 密文，只写不读
    "deps_token_enc": "",               # HTTPS 方式用，Fernet 密文
    "deps_commit_name": "MagicPanel",
    "deps_commit_email": "magicpanel@localhost",
    "deps_sync_hours": "12",
    "deps_auto_push": "1",
    "deps_auto_create_rule_sources": "1",
    "deps_exclude_paths": ".git,.github,.env,*.bak,.*",
    "deps_max_file_bytes": str(2 * 1024 * 1024),
    "deps_last_sync_at": "",            # 内部
    "deps_last_commit": "",             # 内部
    "deps_last_error": "",              # 内部
}


def ensure_dirs() -> None:
    """准备数据目录，并把权限收紧。

    构建产物里含明文节点凭据，数据库里有口令散列与设备令牌密文，
    默认的 0644/0755 会让同机其它用户可读。
    """
    for path in (DATA_DIR, BUILDS_DIR):
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass
    for path in (DB_PATH,):
        if path.exists():
            try:
                path.chmod(0o600)
            except OSError:
                pass
