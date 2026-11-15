"""事务内的加密私密 bytes；不会自行 commit 或打开写连接。"""
import hashlib
import hmac
import uuid

from .. import db, security
from ..contracts.v2 import PrivateBlobRef

KINDS = frozenset({"node-material", "provider", "rule", "dns-owner", "artifact"})
MAX_PRIVATE_BYTES = 64 * 1024 * 1024


def _material_hmac(kind: str, body: bytes) -> str:
    key = security.derive_subkey(security.load_master_material(), purpose="private-blob-hmac")
    return hmac.new(key, kind.encode("ascii") + b"\x00" + body, hashlib.sha256).hexdigest()


def _reference(row) -> PrivateBlobRef:
    return {key: row[key] for key in ("blob_id", "kind", "size", "ciphertext_sha256")}


def put_private(conn, kind: str, body: bytes) -> PrivateBlobRef:
    if not conn.in_transaction:
        raise ValueError("private_blob_transaction_required")
    if not isinstance(kind, str) or kind not in KINDS or not isinstance(body, bytes) or len(body) > MAX_PRIVATE_BYTES:
        raise ValueError("private_blob_invalid")
    material_hmac = _material_hmac(kind, body)
    row = conn.execute("SELECT * FROM private_blobs WHERE kind=? AND material_hmac=? AND key_version=1",
                       (kind, material_hmac)).fetchone()
    if row:
        get_private(conn, row["blob_id"])
        return _reference(row)
    ciphertext = security.encrypt_bytes(body)
    ref = {"blob_id": uuid.uuid4().hex, "kind": kind, "size": len(body),
           "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest()}
    conn.execute("INSERT INTO private_blobs(blob_id,kind,material_hmac,key_version,ciphertext,"
                 "ciphertext_sha256,size,created_at) VALUES(?,?,?,1,?,?,?,?)",
                 (ref["blob_id"], kind, material_hmac, ciphertext, ref["ciphertext_sha256"], len(body), db.now()))
    return ref


def get_private(conn, blob_id: str) -> bytes:
    row = conn.execute("SELECT * FROM private_blobs WHERE blob_id=?", (blob_id,)).fetchone()
    if not row:
        raise ValueError("private_blob_missing")
    try:
        if (row["key_version"] != 1 or row["kind"] not in KINDS or
                not isinstance(row["ciphertext"], bytes) or row["size"] > MAX_PRIVATE_BYTES or
                hashlib.sha256(row["ciphertext"]).hexdigest() != row["ciphertext_sha256"]):
            raise ValueError
        body = security.decrypt_bytes(row["ciphertext"])
        if len(body) != row["size"] or not hmac.compare_digest(_material_hmac(row["kind"], body), row["material_hmac"]):
            raise ValueError
        return body
    except security.DecryptError as exc:
        if str(exc) in {"key_required", "key_invalid"}:
            raise
        raise ValueError("private_blob_corrupt") from None
    except (ValueError, TypeError, OverflowError):
        raise ValueError("private_blob_corrupt") from None
