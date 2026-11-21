"""口令散列、令牌、对称加密与审计写入。"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

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


def derive_subkey(master: bytes, *, purpose: str, version: int = 1) -> bytes:
    """主密钥按用途分域；派生值不进入公开对象。"""
    if (not isinstance(master, bytes) or len(master) != 32 or type(version) is not int or version != 1 or
            not isinstance(purpose, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", purpose)):
        raise ValueError("key_derivation_invalid")
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=b"MagicPanel/v2/key-derivation",
                info=("v1:" + purpose).encode("ascii")).derive(master)


def read_master_material(path) -> bytes:
    """只读显式密钥，绝不替代丢失的密钥。"""
    try:
        if path.is_symlink():
            raise ValueError
        encoded = path.read_bytes().strip()
        material = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(material) != 32:
            raise ValueError
        return material
    except FileNotFoundError:
        raise DecryptError("key_required") from None
    except (OSError, ValueError):
        raise DecryptError("key_invalid") from None


def load_master_material(require_existing: bool = True) -> bytes:
    """仅全新空目录可建钥，已有安装缺钥必须停止。"""
    path = config.SECRET_KEY_PATH
    if not path.exists():
        root = config.DATA_DIR
        if require_existing or (root.exists() and any(root.iterdir())):
            raise DecryptError("key_required")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(Fernet.generate_key())
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass
    material = read_master_material(path)
    path.chmod(0o600)
    return material


def _fernet() -> Fernet:
    """取主密钥。已加载则复用（避免每次加解密都读盘）。"""
    path = config.SECRET_KEY_PATH
    if not path.exists():
        raise DecryptError("key_required")
    if "fernet" in _fernet_cache and _fernet_cache.get("path") == path:
        return _fernet_cache["fernet"]
    material = load_master_material()
    fernet = Fernet(base64.urlsafe_b64encode(material))
    _fernet_cache["fernet"] = fernet
    _fernet_cache["path"] = path
    return fernet


def encrypt_bytes(plain: bytes) -> bytes:
    return _fernet().encrypt(plain)


def decrypt_bytes(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except DecryptError:
        raise
    except Exception:
        raise DecryptError("private_blob_corrupt") from None


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
    """URL 的展示形态：完整显示，仅剔除 userinfo 口令。

    仓库地址、WebDAV 地址这类 URL 的路径不含凭据，直接原样显示；
    user:password@ 形式的口令替换为 ***（否则每次打开面板都会把
    订阅地址里的口令明文送到浏览器，抵消掉加密存储的意义）。
    """
    if not url:
        return ""
    return _URL_USERINFO.sub("***@", url)


def mask_url_secret(url: str) -> str:
    """「路径即凭据」的 URL 展示形态：协议 + 主机 + 长度提示。

    用于订阅地址（/feed/<token>/config.yaml）——路径里的令牌
    等同于凭据，不能完整送进浏览器。
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
