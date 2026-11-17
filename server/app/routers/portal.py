"""门户展示页：PIN 仅用于查看门槛，订阅链接本身的安全性由高熵令牌承担。

PIN 统一为 4 位数字，只保存散列；验证有简单的失败锁定（单进程内存计数）。
历史 6 位 PIN 仍然可以继续使用，但不能再新建 6 位。
"""
import hashlib
import hmac
import json
import math
import secrets
import re
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .. import config, db
from .. import security
from ..services import unlock_check
from ..deps import CurrentUser, RequireCapabilities
from ..services.capabilities import effective_capabilities
from ..services.access_dto import url_summary
from ..services import releases

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])

_MAX_FAILS = 5
_LOCK_SECONDS = 600
_PREVIEW_LINES = 120  # 详情预览最多给多少行
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


def _pin_hash(pin: str, salt: str | None = None) -> str:
    """门户 PIN 散列：PBKDF2 + 每用户随机盐。

    之前是"无盐单次 SHA-256"，4 位 PIN 只有 10^4 种，
    拿到库就能瞬间枚举出明文；备份里带着该散列，等同于带着 PIN。
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode(), bytes.fromhex(salt), 200_000
    ).hex()
    return f"pbkdf2${salt}${digest}"


def _client_ip(request: Request) -> str:
    """真实来源 IP：仅 TRUST_PROXY 开启时读反代追加式 XFF 的最后一段。

    直连部署不信任该头，否则门户 PIN 限流可被自带随机 XFF 绕过
    （2026-11-18 修复，与 auth._client_ip 同一约定）。
    """
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]
    return request.client.host if request.client else "unknown"


def _pin_matches(pin: str, stored: str) -> bool:
    """校验 PIN；兼容历史的无盐 SHA-256 散列。"""
    if not stored:
        return False
    if stored.startswith("pbkdf2$"):
        try:
            _, salt, digest = stored.split("$", 2)
        except ValueError:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", pin.encode(), bytes.fromhex(salt), 200_000
        ).hex()
        return hmac.compare_digest(candidate, digest)
    legacy = hashlib.sha256(f"magicpanel-portal:{pin}".encode()).hexdigest()
    return hmac.compare_digest(legacy, stored)


class PinBody(BaseModel):
    """门户校验用的 PIN。

    新规范统一为 4 位；历史上设过 6 位 PIN 的维护者，其已存 PIN 仍然可用
    （散列照旧校验），只是不能再新建 6 位 PIN。
    """
    pin: str = Field(default="", pattern=r"^(\d{4}|\d{6})?$")


class StrictPinBody(BaseModel):
    """新建/更换 PIN 时使用：统一 4 位数字。"""

    pin: str = Field(default="")

    @field_validator("pin")
    @classmethod
    def _check_pin(cls, v: str) -> str:
        # 自己给中文提示：Pydantic 默认是 "String should have at least 4 characters"
        if not re.fullmatch(r"\d{4}", v or ""):
            raise ValueError("PIN 必须是 4 位数字")
        return v


def _session_user(conn, request: Request):
    """只有具有 reveal 能力的会话可以免 PIN。"""
    from ..deps import SESSION_COOKIE, _load_session
    token = request.cookies.get(SESSION_COOKIE, "")
    row = _load_session(conn, token) if token else None
    return row if row and "reveal" in effective_capabilities(dict(row)) else None


def _check_pin(conn, request: Request, pin: str) -> None:
    ip = _client_ip(request)
    fails, locked_until = _attempts.get(ip, [0, 0])
    now = time.time()
    if locked_until > now:
        raise HTTPException(429, "尝试次数过多，请稍后再试",
                            headers={"Retry-After": str(math.ceil(locked_until - now))})
    hashes = [r["portal_pin_hash"] for r in db.all_(
        conn, "SELECT portal_pin_hash FROM users WHERE role='admin' AND portal_pin_hash != ''")]
    if not hashes:
        raise HTTPException(404, "门户页未启用，请先在管理后台设置 PIN")
    if not pin or not any(_pin_matches(pin, h) for h in hashes):
        fails += 1
        _attempts[ip] = [fails, time.time() + _LOCK_SECONDS if fails >= _MAX_FAILS else 0]
        raise HTTPException(403, "PIN 不正确")
    _attempts.pop(ip, None)


class ProviderDetailBody(BaseModel):
    """按需拉取单个规则来源详情：名字加门户 PIN。"""
    name: str
    pin: str = Field(default="")


def _provider_origin(url: str) -> str:
    """只从可信主机的仓库路径取公开标识，忽略凭据与查询片段。"""
    text = (url or "").strip()
    scp_prefix = "git@github.com:"
    if text.lower().startswith(scp_prefix):
        text = "ssh://git@github.com/" + text[len(scp_prefix):]
    try:
        parsed = urlsplit(text)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return ""
    parts = parsed.path.split("/")
    if not parts or parts[0] != "":
        return ""
    if host == "cdn.jsdelivr.net" and parsed.scheme in {"http", "https"}:
        if len(parts) < 4 or parts[1] != "gh":
            return ""
        owner, repo = parts[2], parts[3].split("@", 1)[0]
    elif (host in {"github.com", "www.github.com"} and parsed.scheme in {"http", "https", "ssh", "git"}
          or host == "raw.githubusercontent.com" and parsed.scheme in {"http", "https"}):
        if len(parts) < 3:
            return ""
        owner, repo = parts[1], parts[2]
    else:
        return ""
    if repo.endswith(".git"):
        repo = repo[:-len(".git")]
    if (not re.fullmatch(r"[A-Za-z0-9-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo)
            or repo in {".", ".."}):
        return ""
    return f"{owner}/{repo}"


def _provider_desc(content: str, fmt: str) -> str:
    """集合文件头部的说明行：自维护集合写「# 说明: ...」，上游文件没有就留空。"""
    if fmt in config.BINARY_FORMATS:
        return ""
    for line in (content or "").splitlines()[:20]:
        m = re.match(r"^#\s*(?:说明|Description)\s*[:：]\s*(\S.*)$", line.strip())
        if m:
            return m.group(1).strip()
    return ""


def _provider_meta(r, repo_origin: str = "") -> dict:
    """规则来源的元信息：不含原始内容，内容按需单独取。"""
    content = r["content"] or ""
    kind = r["kind"]
    repo_path = r["repo_path"] if "repo_path" in r.keys() else ""
    # 远程只展示地址摘要；仓库托管显示相对路径，内联没有地址。
    if kind == "remote":
        address = url_summary(r["url"])
        origin = _provider_origin(r["url"])
    elif kind == "repo":
        address = repo_path
        origin = repo_origin
    else:
        address = ""
        origin = ""
    return {
        "name": r["name"],
        "behavior": r["behavior"],
        "format": r["format"],
        "kind": kind,
        "rule_count": r["rule_count"] or 0,
        "url": url_summary(r["url"]) if kind == "remote" else "",
        "repo_path": repo_path,
        "address": address,
        "interval": r["interval"],
        "client_interval": r["client_interval"],
        "last_status": r["last_status"],
        "last_fetched_at": r["last_fetched_at"],
        "size": len(content),
        "sha256": (r["sha256"] or "")[:12],
        # 仓库托管的来源没有上游 URL，来源归属取自后台配置的依赖仓库地址
        "origin": origin,
        "desc": _provider_desc(content, r["format"]),
    }


@router.get("/status")
def portal_status():
    """门户是否可用：任一维护者设置了 PIN 即视为开启。"""
    with db.connect() as conn:
        enabled = bool(db.one(
            conn, "SELECT 1 FROM users WHERE role='admin' AND portal_pin_hash != '' LIMIT 1"))
    return {"enabled": enabled}


@router.post("/my-pin", status_code=201)
def set_my_pin(body: StrictPinBody, user=RequireCapabilities('edit', 'reveal')):
    """设置当前账号的门户 PIN；其他维护者的 PIN 不受影响。"""
    with db.tx() as conn:
        conn.execute("UPDATE users SET portal_pin_hash=? WHERE id=?",
                     (_pin_hash(body.pin), user["id"]))
        security.audit(conn, user["username"], "设置门户 PIN", "user", user["id"])
    _attempts.clear()
    return {"ok": True}


@router.delete("/my-pin")
def clear_my_pin(user=RequireCapabilities('edit', 'reveal')):
    """撤销当前账号的门户 PIN；全部撤销后门户页即关闭。"""
    with db.tx() as conn:
        conn.execute("UPDATE users SET portal_pin_hash='' WHERE id=?", (user["id"],))
        security.audit(conn, user["username"], "撤销门户 PIN", "user", user["id"])
    _attempts.clear()
    return {"ok": True}


def _build_ok_artifacts(conn, env: str) -> set[str]:
    """某个环境当前生效构建里构建成功的产物名集合。"""
    status = "PRODUCTION" if env == "production" else "TESTING"
    build = db.one(conn, "SELECT results FROM builds WHERE status=? LIMIT 1", (status,))
    if not build:
        return set()
    try:
        results = json.loads(build["results"] or "{}")
    except (TypeError, ValueError):
        return set()
    return {key for key, value in results.items()
            if isinstance(value, dict) and value.get("ok")}


def _available_variants(ok_artifacts: set[str], variants: list[dict],
                        target_name: str, device_name: str) -> list[str]:
    """该设备当前能下载到的方案：产物真实存在才给选项，避免 404 链接。

    默认方案的产物不带方案后缀；自定义方案产物是 {目标/设备}@方案名.yaml。
    """
    out = []
    for v in variants:
        if int(v["id"]) == 0:
            ok = target_name in ok_artifacts or device_name in ok_artifacts
        else:
            ok = (f"{target_name}@{v['name']}" in ok_artifacts
                  or f"{device_name}@{v['name']}" in ok_artifacts)
        if ok:
            out.append(v["name"])
    return out


@router.post("/data")
def portal_data(body: PinBody, request: Request, response: Response):
    """门户数据：设备订阅链接、客户端资源、导入指引与个人规则。

    已登录的维护者免 PIN；未登录访客按 PIN 校验。
    """
    response.headers["Cache-Control"] = "no-store"
    with db.connect() as conn:
        user = _session_user(conn, request)
        if not user:
            if not body.pin:
                raise HTTPException(401, "请输入 PIN 或登录维护者账号")
            _check_pin(conn, request, body.pin)
        base = db.get_setting(conn, "base_url", "").rstrip("/") \
            or str(request.base_url).rstrip("/")
        variants = [
            {"id": int(r["id"]), "name": r["name"], "note": r["note"]}
            for r in db.all_(
                conn, "SELECT id, name, note FROM variants WHERE enabled=1 "
                      "ORDER BY sort, id")
        ]
        # 预取：设备循环里每台一次 targets/builds 查询是 N+1（2026-11-18 收口）
        targets_by_id = {int(t["id"]): t for t in db.all_(conn, "SELECT * FROM targets")}
        ok_artifacts_by_env = {env: _build_ok_artifacts(conn, env)
                               for env in ("production", "testing")}
        devices = []
        for r in db.all_(conn, "SELECT * FROM devices ORDER BY id"):
            target = targets_by_id.get(int(r["target_id"]))
            item = {
                "name": r["name"],
                "display_name": r["note"] or r["name"],
                "platform": r["platform"],
                "env": r["env"],
                "engine": target["engine"] if target else "",
                "target_name": target["name"] if target else "",
                "note": r["note"],
                "last_pull_at": r["last_pull_at"],
                "subscription_url": "",
                # 「看配置源码」用：同一份内容，但不记拉取、内联展示。
                # 用**相对路径**：门户与 feed 是同一个服务，相对路径天然同源，
                # 从内网 IP、容器端口还是公网域名打开都能预览；写绝对地址会让
                # 前两种场景变成跨源请求，被浏览器 CORS 拦掉。
                "preview_url": "",
                # 该设备当前能选的分流方案（按生效构建的真实产物计算）
                "variants": [],
            }
            if r["token_enc"]:
                token = security.decrypt_text(r["token_enc"])
                item["subscription_url"] = f"{base}/feed/{token}/config.yaml"
                item["preview_url"] = f"/feed/{token}/config.yaml?preview=1"
                item["variants"] = _available_variants(
                    ok_artifacts_by_env.get(r["env"], set()), variants,
                    item["target_name"], r["name"])
            else:
                item["note"] = (item["note"] + "；" if item["note"] else "") \
                    + "缺少可展示的令牌，请在后台轮换一次"
            devices.append(item)
        rules = [
            {"type": r["type"], "value": r["value"], "target": r["target"],
             "note": r["note"], "no_resolve": bool(r["no_resolve"])}
            for r in db.all_(
                conn,
                "SELECT * FROM rules WHERE enabled=1 AND type!='RULE-SET' "
                "AND variant_id=0 ORDER BY sort, id",
            )
        ]
        # 规则来源仅展示元信息，随配置下发，不展示原始内容
        repo_origin = _provider_origin(db.get_setting(conn, "deps_url", ""))
        rule_providers = [
            _provider_meta(r, repo_origin)
            for r in db.all_(
                conn,
                "SELECT * FROM rule_providers WHERE enabled=1 ORDER BY id",
            )
        ]
        release_state = releases.state_public(conn)
        snippets = [
            {"name": r["name"], "category": r["category"], "engine": r["engine"],
             "note": r["note"]}
            for r in db.all_(
                conn, "SELECT * FROM snippets WHERE enabled=1 ORDER BY sort, id")
        ]
    return {
        "base_url": base,
        "devices": devices,
        "variants": variants,
        "clients": CLIENT_RESOURCES,
        "guides": IMPORT_GUIDES,
        "rules": rules,
        "rule_providers": rule_providers,
        "snippets": snippets,
        "release_state": release_state,
    }


@router.post("/provider-detail")
def portal_provider_detail(body: ProviderDetailBody, request: Request, response: Response):
    """单个规则来源的详情与内容预览。

    原始内容不进门户首屏数据，这里按需取：文本格式给前若干行，
    二进制格式（MRS）没有可读内容，只给大小与指纹。
    """
    response.headers["Cache-Control"] = "no-store"
    with db.connect() as conn:
        user = _session_user(conn, request)
        if not user:
            if not body.pin:
                raise HTTPException(401, "请输入 PIN 或登录维护者账号")
            _check_pin(conn, request, body.pin)
        row = db.one(
            conn,
            "SELECT * FROM rule_providers WHERE name=? AND enabled=1",
            (body.name,),
        )
        if not row:
            raise HTTPException(404, "规则来源不存在")
        meta = _provider_meta(row, _provider_origin(
            db.get_setting(conn, "deps_url", "")))
        content = row["content"] or ""
    lines = content.splitlines()
    preview = ""
    if row["format"] not in config.BINARY_FORMATS:
        preview = "\n".join(lines[:_PREVIEW_LINES])
    return {
        **meta,
        "preview": preview,
        "total_lines": len(lines),
        "truncated": len(lines) > _PREVIEW_LINES,
    }


@router.get("/unlock")
def portal_unlock_last():
    """门户公开：最近一次面板出口的解锁检测结果。"""
    return unlock_check.last_results("panel")


_unlock_run_lock = threading.Lock()

@router.post("/unlock/run")
def portal_unlock_run():
    """门户公开：触发一次面板出口的全量检测（60 秒内复用缓存）。

    进程内锁串行化（2026-11-18）：缓存挡不住并发——未认证访客并发
    打这个端点会让面板出口持续对外发请求。
    """
    import time as _time
    last = unlock_check.last_results("panel")
    now = int(_time.time())
    if last.get("checked_at") and now - last.get("checked_at", 0) < 60:
        return last
    if not _unlock_run_lock.acquire(blocking=False):
        # 已有一轮在跑：等下一轮结果，不叠加外发
        raise HTTPException(429, "已有检测在进行中，请稍后刷新结果")
    try:
        # 双重检查：排队期间可能别人已经跑完
        last = unlock_check.last_results("panel")
        now = int(_time.time())
        if last.get("checked_at") and now - last.get("checked_at", 0) < 60:
            return last
        try:
            return unlock_check.run_checks("panel", operator="portal")
        except Exception as exc:
            raise HTTPException(502, f"检测执行失败：{exc}")
    finally:
        _unlock_run_lock.release()
