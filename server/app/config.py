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
GROUP_TYPES = {"select", "url-test", "fallback"}
RULE_TYPES = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX",
    "IP-CIDR", "IP-CIDR6", "GEOIP", "GEOSITE", "RULE-SET",
    "SRC-IP-CIDR", "DST-PORT", "PROCESS-NAME", "MATCH",
}
TOKEN_PREFIX = "mp_"
DEFAULT_UA = "Stash"
FETCH_MAX_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT = 20.0
SESSION_TTL_HOURS = 168

SETTINGS_DEFAULTS = {
    "base_url": "",                 # 对外基础地址，如 https://panel.example.com
    "session_ttl_hours": str(SESSION_TTL_HOURS),
    "profile_update_interval": "12",  # 小时，写入响应头 profile-update-interval
}


def ensure_dirs() -> None:
    for p in (DATA_DIR, BUILDS_DIR):
        p.mkdir(parents=True, exist_ok=True)
