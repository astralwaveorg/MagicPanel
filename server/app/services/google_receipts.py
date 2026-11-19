"""导入独立观测者签署的 Google 业务回执，不发起网络请求或切换线路。"""
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .. import db
from . import probe_observers, probe_store

SERVICE = "google:critical"
PROBE_ID = "google-critical"
VERSION = "v1"
REGIONS = ("US", "SG", "JP")
PRODUCT_STATES = frozenset({
    "observed-ok", "confirmed-blocked", "auth-required", "challenge", "rate-limited", "unknown",
})
FIELDS = frozenset({
    "observer_id", "path_epoch", "node_uid", "node_revision", "measured_at",
    "products", "control_sha256",
})


def message(receipt):
    """签名绑定实际被测节点版本、路径、目标证据和测量时间。"""
    return json.dumps(
        {"purpose": "magicpanel-google-observation", "version": 1, "receipt": receipt},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()


def _digest(value, length=64):
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value)


def verify(receipt, signature, public_key):
    """核对四个目标各自的出口证明，只有同一国家且同类结论才参与整档选路。"""
    try:
        if (not isinstance(receipt, dict) or set(receipt) != FIELDS
                or not _digest(signature, 128) or not _digest(public_key)
                or not _digest(receipt["control_sha256"])
                or not _digest(receipt["node_uid"], 32)
                or not isinstance(receipt["observer_id"], str)
                or not 0 < len(receipt["observer_id"]) <= 128
                or type(receipt["node_revision"]) is not int or receipt["node_revision"] < 1
                or type(receipt["path_epoch"]) is not int or receipt["path_epoch"] < 1):
            return None
        measured_at = datetime.fromisoformat(receipt["measured_at"])
        if measured_at.utcoffset() is None:
            return None
        products = receipt["products"]
        if not isinstance(products, dict) or set(products) != probe_observers.GOOGLE_PROBE_HOST_ALLOWLIST:
            return None
        for row in products.values():
            if (not isinstance(row, dict) or set(row) != {"state", "country", "egress_sha256", "result_sha256"}
                    or row["state"] not in PRODUCT_STATES or row["country"] not in REGIONS
                    or not _digest(row["egress_sha256"]) or not _digest(row["result_sha256"])):
                return None
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            bytes.fromhex(signature), message(receipt))
        countries = {row["country"] for row in products.values()}
        if len(countries) != 1:
            return None
        states = {row["state"] for row in products.values()}
        state = ("observed-ok" if states == {"observed-ok"} else
                 "blocked" if states == {"confirmed-blocked"} else "unknown")
        return measured_at.astimezone(timezone.utc), countries.pop(), state
    except (InvalidSignature, TypeError, ValueError, OverflowError):
        return None


def ingest(conn, receipt, signature, *, now):
    if not conn.in_transaction:
        raise ValueError("probe_transaction_required")
    if not isinstance(receipt, dict) or set(receipt) != FIELDS or not isinstance(receipt["observer_id"], str):
        raise ValueError("google_receipt_invalid")
    observer = db.one(conn, "SELECT public_key FROM probe_observers WHERE id=? AND enabled=1 AND kind!='fixture'",
                      (receipt["observer_id"],))
    verified = verify(receipt, signature, observer["public_key"]) if observer else None
    if not verified:
        raise ValueError("google_receipt_invalid")
    measured, country, state = verified
    if not now - timedelta(minutes=5) <= measured <= now:
        raise ValueError("google_receipt_stale")
    path = probe_observers.require_path(conn, receipt["observer_id"], receipt["path_epoch"], "google", measured)
    valid_until = min(datetime.fromisoformat(path["expires_at"]), measured + timedelta(hours=24))
    if valid_until <= now:
        raise ValueError("google_receipt_stale")
    current = db.one(conn, "SELECT 1 FROM node_catalog WHERE node_uid=? AND current_revision=? "
                          "AND retired=0 AND enabled=1", (receipt["node_uid"], receipt["node_revision"]))
    if not current:
        raise ValueError("google_node_revision_stale")
    # 同一观测者重传同一时刻的回执也只算一次，不给两次故障确认增加票数。
    scope = (receipt["observer_id"], receipt["node_uid"], receipt["node_revision"], measured.isoformat())
    key = "google-receipt:" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()
    if db.one(conn, "SELECT 1 FROM probe_jobs WHERE schedule_key=?", (key,)):
        raise ValueError("google_receipt_duplicate")
    job = probe_store.enqueue(conn, trigger="observer-receipt", observer_id=receipt["observer_id"],
        nodes=[(receipt["node_uid"], receipt["node_revision"])], services=(SERVICE,), schedule_key=key,
        now=now, deadline=now + timedelta(minutes=1))
    worker = uuid.uuid4().hex
    item = probe_store.claim(conn, worker_id=worker, now=now, job_id=job["id"],
                             observer_id=receipt["observer_id"])
    probe_store.finish(conn, item["id"], worker, {
        "path_epoch": receipt["path_epoch"], "probe_id": PROBE_ID, "probe_version": VERSION,
        "result_state": state, "valid_until": valid_until,
        "egress": {"scope": "google", "verified": True, "country": country},
        "evidence": {"receipt": receipt, "signature": signature},
    }, now)
    return {"job_id": job["id"], "state": state}


def main():
    # 只接受标准输入，不把回执内容或异常参数写入运维日志。
    try:
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768:
            raise ValueError("google_receipt_too_large")
        doc = json.loads(raw)
        if not isinstance(doc, dict) or set(doc) != {"receipt", "signature"}:
            raise ValueError("google_receipt_invalid")
        with db.tx(immediate=True) as conn:
            result = ingest(conn, doc["receipt"], doc["signature"], now=datetime.now(timezone.utc))
        print(json.dumps(result))
    except (ValueError, TypeError, KeyError) as exc:
        code = str(exc)
        sys.exit(code if re.fullmatch(r"(google|path)_[a-z_]+", code) else "google_receipt_invalid")


if __name__ == "__main__":
    main()
