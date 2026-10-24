"""口令散列、令牌、对称加密与审计写入。"""
import base64
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from . import config, db

_PBKDF2_ROUNDS = 600_000   # OWASP 对 PBKDF2-HMAC-SHA256 的建议值


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ROUNDS
    )
    return digest.hex(), salt


def verify_password(password: str, digest: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, digest)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """二进制内容（MRS 规则集）的指纹。"""
    return hashlib.sha256(data).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_device_token() -> str:
    return config.TOKEN_PREFIX + secrets.token_urlsafe(32)


_fernet_cache: dict = {}


def _fernet() -> Fernet:
    """取主密钥。已加载则复用（避免每次加解密都读盘）。"""
    if "fernet" in _fernet_cache:
        return _fernet_cache["fernet"]
    config.ensure_dirs()
    path = config.SECRET_KEY_PATH
    if not path.exists():
        key = Fernet.generate_key()
        path.write_bytes(key)
    # 无论新建还是从备份还原，都强制 600，避免同机其它用户读取密钥
    try:
        path.chmod(0o600)
    except OSError:
        pass
    material = path.read_bytes().strip()
    if not material:
        raise DecryptError("主密钥 data/secret.key 为空，无法解密任何密文")
    fernet = Fernet(material)
    _fernet_cache["fernet"] = fernet
    return fernet


def encrypt_text(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


class DecryptError(RuntimeError):
    """解密失败：通常是密钥（data/secret.key）丢失或被替换。"""


def decrypt_text(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception as exc:  # InvalidToken 等
        raise DecryptError(
            "解密失败：主密钥 data/secret.key 缺失或已更换，"
            "该条密文内容无法恢复（请从备份还原密钥）"
        ) from exc


PAYLOAD_PREFIX = "enc:v1:"


def encrypt_payload(plain: str) -> str:
    """把整段文本加密后带版本前缀存库，便于识别与迁移。"""
    if not plain:
        return plain
    return PAYLOAD_PREFIX + encrypt_text(plain)


def decrypt_payload(payload: str) -> str:
    """兼容历史明文：没有版本前缀的直接返回。"""
    if not payload:
        return ""
    if payload.startswith(PAYLOAD_PREFIX):
        return decrypt_text(payload[len(PAYLOAD_PREFIX):])
    return payload


def mask_url(url: str) -> str:
    """凭据类 URL 的展示形态：协议 + 主机 + 长度提示。

    必须剔除 userinfo（user:password@）——否则每次打开面板
    都会把订阅地址里的口令明文送到浏览器，抵消掉加密存储的意义。
    """
    if not url:
        return ""
    parsed = urlparse(url)
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None      # 非法端口号：只展示主机部分
    if port:
        host = f"{host}:{port}"
    tail = parsed.path or ""
    if parsed.query:
        tail += "?" + parsed.query
    hint = f"…({len(tail)} 字符)" if tail else ""
    return f"{scheme}://{host}/{hint}"


_SECRET_KEY_HINTS = ("token", "password", "passwd", "secret", "proxy", "url",
                      "key", "pin", "credential")
_URL_USERINFO = re.compile(r"(?<=://)[^/@\s]+(?=@)")


def mask_secret_value(key: str, value: str) -> str:
    """设置项写入审计前的统一打码。

    凭据类键名直接打码；任何含 userinfo 的 URL 也把口令部分去掉。
    """
    text = "" if value is None else str(value)
    lowered = (key or "").lower()
    if any(hint in lowered for hint in _SECRET_KEY_HINTS):
        return "***"
    return _URL_USERINFO.sub("***", text)


def audit(conn, actor: str, action: str, object_type: str = "",
          object_id: str = "", detail: dict | str = "") -> None:
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False)
    conn.execute(
        "INSERT INTO audit(at, actor, action, object_type, object_id, detail) "
        "VALUES(?,?,?,?,?,?)",
        (db.now(), actor, action, object_type, str(object_id), detail),
    )


def random_csrf() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(24)).decode()
