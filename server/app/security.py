"""口令散列、令牌、对称加密与审计写入。"""
import base64
import hashlib
import hmac
import json
import secrets

from cryptography.fernet import Fernet

from . import config, db

_PBKDF2_ROUNDS = 260_000


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


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_device_token() -> str:
    return config.TOKEN_PREFIX + secrets.token_urlsafe(32)


def _fernet() -> Fernet:
    config.ensure_dirs()
    path = config.SECRET_KEY_PATH
    if not path.exists():
        key = Fernet.generate_key()
        path.write_bytes(key)
        path.chmod(0o600)
    return Fernet(path.read_bytes().strip())


def encrypt_text(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_text(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


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
    """凭据类 URL 的展示形态：协议 + 主机 + 长度提示，不含路径与查询串。"""
    if not url:
        return ""
    head, _, rest = url.partition("://")
    host = rest.split("/", 1)[0]
    tail = rest[len(host):]
    hint = f"…({len(tail)} 字符)" if tail else ""
    scheme = head if head in ("http", "https") else "https"
    return f"{scheme}://{host}/{hint}"


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
