"""Studio's private SQLite store. No dependency on the v1 runtime or database."""
import hashlib
import json
import os
import secrets
import sqlite3
import time
import zlib
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from . import model,routing

ROOT = Path(os.environ.get("STUDIO_DATA", "/var/lib/magicpanel-studio"))
DB = ROOT / "studio.sqlite3"

DDL = """
CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, salt TEXT NOT NULL, verifier TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, user TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS draft(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, token BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS blobs(id TEXT PRIMARY KEY, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS releases(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, at INTEGER NOT NULL, actor TEXT NOT NULL, manifest BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS live(id INTEGER PRIMARY KEY CHECK(id=1), release INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS subscription_key(id INTEGER PRIMARY KEY CHECK(id=1),digest TEXT UNIQUE NOT NULL,token BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS catalogs(release INTEGER PRIMARY KEY,body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS corechecks(key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS checks(kind TEXT,key TEXT,at INTEGER,error TEXT,PRIMARY KEY(kind,key));
CREATE TABLE IF NOT EXISTS automation(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0, failed_revision INTEGER, error TEXT NOT NULL DEFAULT '');
INSERT OR IGNORE INTO automation(id) VALUES(1);
"""

def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

@lru_cache(maxsize=4)
def cipher(root):
    return Fernet((root / "master.key").read_bytes())

def seal(raw):
    return cipher(ROOT).encrypt(zlib.compress(raw, 4))

def unseal(raw):
    return zlib.decompress(cipher(ROOT).decrypt(raw))

def init():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = ROOT / "master.key"
    if not key.exists():
        if DB.exists():
            raise RuntimeError("数据库已有数据但主密钥缺失")
        with os.fdopen(os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as f:
            f.write(Fernet.generate_key())
            f.flush()
            os.fsync(f.fileno())
    with tx() as c:
        c.executescript(DDL)
    with sqlite3.connect(DB) as c:
        c.execute("PRAGMA journal_mode=WAL")
    DB.chmod(0o600)

@contextmanager
def tx(write=False):
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()

def workspace(c):
    row = c.execute("SELECT revision,body FROM draft WHERE id=1").fetchone()
    if not row:
        raise ValueError("尚未导入初始工作区")
    w=model.expand(json.loads(unseal(row[1])))
    routing.ensure(w)
    return row[0],w

def encode_workspace(w):
    return seal(encode(model.pack(w)))

def event(c, actor, message):
    c.execute("INSERT INTO events(at,actor,action) VALUES(?,?,?)", (int(time.time()), actor, message))

def put_blob(c, raw):
    key = digest(raw)
    if not c.execute("SELECT 1 FROM blobs WHERE id=?", (key,)).fetchone():
        c.execute("INSERT INTO blobs VALUES(?,?)", (key,seal(raw)))
    return key

def read_blob(c, key):
    row = c.execute("SELECT body FROM blobs WHERE id=?", (key,)).fetchone()
    if not row:
        raise ValueError("发布资源缺失")
    return unseal(row[0])

def new_token(c, did):
    token = secrets.token_urlsafe(32)
    c.execute("INSERT INTO devices VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET digest=excluded.digest,token=excluded.token",
              (did,digest(token.encode()),seal(token.encode())))
    return token
