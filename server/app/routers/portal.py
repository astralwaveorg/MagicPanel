"""门户展示页：PIN 仅用于查看门槛，订阅链接本身的安全性由高熵令牌承担。

PIN 为 4 位数字，只保存散列；验证有简单的失败锁定（单进程内存计数）。
"""
import hashlib
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, security
from ..deps import CurrentUser

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])

_MAX_FAILS = 5
_LOCK_SECONDS = 600
_attempts: dict[str, list] = {}  # ip -> [失败次数, 锁定截止时间戳]

# 客户端资源：官方或维护者确认的下载入口
CLIENT_RESOURCES = [
    {"name": "Stash Mac", "desc": "brew install stash（推荐）",
     "url": "https://releases.stash.ws/Stash-latest.dmg", "kind": "brew+dmg",
     "platform": "macOS"},
    {"name": "Stash Windows", "desc": "官方安装包",
     "url": "https://releases.stash.ws/windows/Stash-latest-setup.exe",
     "kind": "exe", "platform": "Windows"},
    {"name": "Stash iOS / iPadOS / tvOS", "desc": "App Store",
     "url": "https://apps.apple.com/us/app/stash/id1596063349?l=zh-Hans-CN",
     "kind": "store", "platform": "iOS / tvOS"},
    {"name": "Mihomo 内核", "desc": "GitHub 最新发布",
     "url": "https://github.com/MetaCubeX/mihomo/releases/latest",
     "kind": "release", "platform": "跨平台"},
    {"name": "Clash Verge Rev", "desc": "官方安装指引",
     "url": "https://www.clashverge.dev/install.html",
     "kind": "release", "platform": "Windows / macOS"},
    {"name": "FlClash", "desc": "GitHub 发布页（Android 主用客户端）",
     "url": "https://github.com/chen08209/FlClash/releases/latest",
     "kind": "release", "platform": "Android"},
]

# 各平台导入订阅的简要步骤
IMPORT_GUIDES = [
    {"platform": "Stash（iOS / Mac / tvOS）", "steps": [
        "复制设备对应的订阅地址",
        "打开 Stash → 设置 → 配置文件 → 新建 → 选择“服务商配置”",
        "粘贴地址并下载；首行为 #SUBSCRIBED 的配置会按提示间隔自动更新",
    ]},
    {"platform": "FlClash（Android）", "steps": [
        "复制设备对应的订阅地址",
        "打开 FlClash → 配置 → 右下角新建 → URL",
        "粘贴地址保存，开启自动更新",
    ]},
    {"platform": "Clash Verge Rev（Windows 后备）", "steps": [
        "复制 Mihomo 目标的订阅地址",
        "打开 Clash Verge Rev → 配置 → 新建 → Remote",
        "粘贴地址保存并启用",
    ]},
]


def _pin_hash(pin: str) -> str:
    return hashlib.sha256(f"magicpanel-portal:{pin}".encode()).hexdigest()


class PinBody(BaseModel):
    pin: str = Field(default="", pattern=r"^(\d{4})?$")


class StrictPinBody(BaseModel):
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


def _session_user(conn, request: Request):
    """已登录的维护者免 PIN：尝试按会话识别，失败返回 None。"""
    from ..deps import SESSION_COOKIE, _load_session
    token = request.cookies.get(SESSION_COOKIE, "")
    return _load_session(conn, token) if token else None


def _check_pin(conn, request: Request, pin: str) -> None:
    ip = request.client.host if request.client else "unknown"
    fails, locked_until = _attempts.get(ip, [0, 0])
    if locked_until > time.time():
        raise HTTPException(429, "尝试次数过多，请 10 分钟后再试")
    hashes = [r["portal_pin_hash"] for r in db.all_(
        conn, "SELECT portal_pin_hash FROM users WHERE portal_pin_hash != ''")]
    if not hashes:
        raise HTTPException(404, "门户页未启用，请先在管理后台设置 PIN")
    if not pin or _pin_hash(pin) not in hashes:
        fails += 1
        _attempts[ip] = [fails, time.time() + _LOCK_SECONDS if fails >= _MAX_FAILS else 0]
        raise HTTPException(403, "PIN 不正确")
    _attempts.pop(ip, None)


@router.get("/status")
def portal_status():
    """门户是否可用：任一维护者设置了 PIN 即视为开启。"""
    with db.connect() as conn:
        enabled = bool(db.one(
            conn, "SELECT 1 FROM users WHERE portal_pin_hash != '' LIMIT 1"))
    return {"enabled": enabled}


@router.post("/my-pin", status_code=201)
def set_my_pin(body: StrictPinBody, user=CurrentUser):
    """设置当前账号的门户 PIN；其他维护者的 PIN 不受影响。"""
    with db.tx() as conn:
        conn.execute("UPDATE users SET portal_pin_hash=? WHERE id=?",
                     (_pin_hash(body.pin), user["id"]))
        security.audit(conn, user["username"], "设置门户 PIN", "user", user["id"])
    _attempts.clear()
    return {"ok": True}


@router.delete("/my-pin")
def clear_my_pin(user=CurrentUser):
    """撤销当前账号的门户 PIN；全部撤销后门户页即关闭。"""
    with db.tx() as conn:
        conn.execute("UPDATE users SET portal_pin_hash='' WHERE id=?", (user["id"],))
        security.audit(conn, user["username"], "撤销门户 PIN", "user", user["id"])
    _attempts.clear()
    return {"ok": True}


@router.post("/data")
def portal_data(body: PinBody, request: Request):
    """门户数据：设备订阅链接、客户端资源、导入指引与个人规则。

    已登录的维护者免 PIN；未登录访客按 PIN 校验。
    """
    with db.connect() as conn:
        user = _session_user(conn, request)
        if not user:
            if not body.pin:
                raise HTTPException(401, "请输入 PIN 或登录维护者账号")
            _check_pin(conn, request, body.pin)
        base = db.get_setting(conn, "base_url", "").rstrip("/") \
            or str(request.base_url).rstrip("/")
        devices = []
        for r in db.all_(conn, "SELECT * FROM devices ORDER BY id"):
            target = db.one(conn, "SELECT * FROM targets WHERE id=?", (r["target_id"],))
            item = {
                "name": r["name"],
                "platform": r["platform"],
                "channel": r["channel"],
                "engine": target["engine"] if target else "",
                "target_name": target["name"] if target else "",
                "note": r["note"],
                "last_pull_at": r["last_pull_at"],
                "subscription_url": "",
            }
            if r["token_enc"]:
                token = security.decrypt_text(r["token_enc"])
                item["subscription_url"] = f"{base}/feed/{token}/config.yaml"
            else:
                item["note"] = (item["note"] + "；" if item["note"] else "") \
                    + "缺少可展示的令牌，请在后台轮换一次"
            devices.append(item)
        rules = [
            {"type": r["type"], "value": r["value"], "target": r["target"],
             "note": r["note"]}
            for r in db.all_(
                conn,
                "SELECT * FROM rules WHERE enabled=1 AND type!='RULE-SET' "
                "ORDER BY sort, id",
            )
        ]
        # 规则来源仅展示元信息，随配置下发，不展示原始内容
        rule_providers = [
            {"name": r["name"], "behavior": r["behavior"], "kind": r["kind"],
             "rule_count": r["rule_count"]}
            for r in db.all_(
                conn,
                "SELECT * FROM rule_providers WHERE enabled=1 ORDER BY id",
            )
        ]
        channels = {}
        for p in db.all_(conn, "SELECT * FROM pointers"):
            build = db.one(conn, "SELECT * FROM builds WHERE id=?", (p["build_id"],))
            if build:
                channels[p["channel"]] = {
                    "build_id": build["id"], "created_at": build["created_at"],
                }
        snippets = [
            {"name": r["name"], "category": r["category"], "engine": r["engine"],
             "note": r["note"]}
            for r in db.all_(
                conn, "SELECT * FROM snippets WHERE enabled=1 ORDER BY sort, id")
        ]
    return {
        "base_url": base,
        "devices": devices,
        "clients": CLIENT_RESOURCES,
        "guides": IMPORT_GUIDES,
        "rules": rules,
        "rule_providers": rule_providers,
        "snippets": snippets,
        "channels": channels,
    }
