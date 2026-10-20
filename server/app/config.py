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

GUARD_PROXY = "空组保护"           # 永远无法出站的占位节点，防止空策略组被客户端隐式改写
BUILTIN_TARGETS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "GLOBAL"}
GROUP_TYPES = {"select", "url-test", "fallback", "load-balance", "relay"}
LB_STRATEGIES = {"consistent-hashing", "round-robin", "sticky-sessions"}
RULE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX",
    "IP-CIDR", "IP-CIDR6", "GEOIP", "GEOSITE", "RULE-SET",
    "SRC-IP-CIDR", "DST-PORT", "PROCESS-NAME", "MATCH",
}
# 允许附加 no-resolve 修饰符的规则类型（IP 字面量匹配，不触发域名解析）
NO_RESOLVE_TYPES = {"IP-CIDR", "IP-CIDR6", "GEOIP", "RULE-SET", "SRC-IP-CIDR"}
TOKEN_PREFIX = "mp_"
DEFAULT_UA = "Stash"
FETCH_MAX_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT = 20.0
SESSION_TTL_HOURS = 168
# 内置调度器：单进程后台任务，随应用启动；测试环境用 MAGICPANEL_SCHEDULER=0 关闭
SCHEDULER_AUTOSTART = os.environ.get("MAGICPANEL_SCHEDULER", "1") != "0"
SCHEDULER_TICK_SECONDS = max(10, int(os.environ.get("MAGICPANEL_SCHEDULER_TICK", "30")))
RELEASE_HISTORY_LIMIT = 10       # 发布历史只保留最近 10 条（每日两次约 5 天）

SETTINGS_DEFAULTS = {
    "base_url": "",                 # 对外基础地址，如 https://panel.example.com
    "session_ttl_hours": str(SESSION_TTL_HOURS),
    "profile_update_interval": "1",  # 小时，写入响应头 profile-update-interval
    # 内置定时任务
    "scheduler_enabled": "1",
    "auto_fetch_sources": "1",
    "auto_fetch_rules": "1",
    "auto_test_sources": "1",
    "auto_build_enabled": "1",
    "auto_build_interval_hours": "1",
    "auto_publish_enabled": "1",
    "auto_publish_channel": "stable",   # stable / candidate
    "auto_build_last_attempt": "",      # 内部：上次自动构建检查时间
}


def ensure_dirs() -> None:
    for p in (DATA_DIR, BUILDS_DIR):
        p.mkdir(parents=True, exist_ok=True)
