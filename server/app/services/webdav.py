"""WebDAV 只上传加密完整归档；恢复永远停在独立 staging。"""
import base64
from contextlib import closing
import json
import logging
import secrets
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import httpx

from .. import config, db, security

logger = logging.getLogger("magicpanel.webdav")

# 远端文件名前缀，便于识别与清理
PREFIX = "magicpanel-"
DB_SUFFIX = ".db"
KEY_SUFFIX = ".key"
ARCHIVE_SUFFIX = ".mpbackup"
META_SUFFIX = ".meta.json"

# 设置项
SET_ENABLED = "webdav_enabled"
SET_URL = "webdav_url"
SET_USER = "webdav_username"
SET_PASS = "webdav_password_enc"
SET_DIR = "webdav_dir"
SET_INTERVAL = "webdav_interval_hours"
SET_KEEP = "webdav_keep"
SET_LAST_AT = "webdav_last_backup_at"
SET_LAST_STATUS = "webdav_last_status"
SET_LAST_ERROR = "webdav_last_error"


class WebDavError(Exception):
    """WebDAV 操作失败（连接、鉴权、路径、响应异常）。"""


def _setting(conn, key: str, default: str = "") -> str:
    return db.get_setting(conn, key, default)


def _credentials(conn) -> tuple[str, str, str, str]:
    """返回 (地址, 用户名, 口令, 目录)。口令从加密存储中取出。"""
    url = _setting(conn, SET_URL).strip()
    username = _setting(conn, SET_USER).strip()
    encrypted = _setting(conn, SET_PASS)
    password = ""
    if encrypted:
        try:
            password = security.decrypt_payload(encrypted)
        except security.DecryptError:
            password = ""
    directory = _setting(conn, SET_DIR, "magicpanel").strip().strip("/")
    return url, username, password, directory


def is_configured(conn) -> bool:
    url, _, _, _ = _credentials(conn)
    return bool(url)


def _client(conn, timeout: float = 60.0) -> httpx.Client:
    url, username, password, _ = _credentials(conn)
    if not url:
        raise WebDavError("尚未配置 WebDAV 地址")
    auth = (username, password) if username else None
    return httpx.Client(timeout=timeout, auth=auth, follow_redirects=True,
                        trust_env=False)


def _base(conn) -> str:
    url, _, _, directory = _credentials(conn)
    return f"{url.rstrip('/')}/{directory}" if directory else url.rstrip("/")


def _request(conn, method: str, url: str, **kwargs) -> httpx.Response:
    try:
        with _client(conn) as client:
            resp = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise WebDavError(f"连接失败：{exc}") from exc
    if resp.status_code >= 400:
        raise WebDavError(f"HTTP {resp.status_code} {resp.reason_phrase}")
    return resp


def test_connection(conn) -> str:
    """测试连通性与鉴权，并确保备份目录存在。"""
    _ensure_dir(conn)
    url, username, _, directory = _credentials(conn)
    return f"{url.rstrip('/')}/{directory}（用户：{username or '匿名'}）"


def _ensure_dir(conn) -> None:
    """逐级创建远端目录（已存在时忽略 405）。"""
    url, _, _, directory = _credentials(conn)
    if not directory:
        return
    parts = directory.split("/")
    current = url.rstrip("/")
    for part in parts:
        current = f"{current}/{part}"
        try:
            _request(conn, "MKCOL", current)
        except WebDavError as exc:
            if "405" in str(exc) or "301" in str(exc):
                continue      # 已存在
            raise


def upload_file(conn, local_path: Path, remote_name: str) -> str:
    """上传一个本地文件到备份目录。"""
    _ensure_dir(conn)
    target = f"{_base(conn)}/{remote_name}"
    try:
        with local_path.open("rb") as handle:
            _request(conn, "PUT", target, content=handle)
    except OSError as exc:
        raise WebDavError(f"读取本地文件失败：{exc}") from exc
    return target


def download_file(conn, remote_name: str, local_path: Path, *, max_bytes: int | None = None) -> None:
    """下载远端文件到本地路径。"""
    if "/" in remote_name or "\\" in remote_name or ".." in remote_name:
        raise WebDavError("远端文件名不合法")
    if max_bytes is None:
        from .backup_archive import MAX_ARCHIVE_BYTES
        max_bytes = MAX_ARCHIVE_BYTES
    source = f"{_base(conn)}/{remote_name}"
    try:
        with _client(conn) as client:
            with client.stream("GET", source) as resp:
                if resp.status_code >= 400:
                    raise WebDavError(f"HTTP {resp.status_code}")
                from .backup_archive import _open_private
                with _open_private(local_path) as handle:
                    total = 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise WebDavError("archive_limit_exceeded")
                        handle.write(chunk)
    except httpx.HTTPError as exc:
        raise WebDavError(f"下载失败：{exc}") from exc
    except OSError as exc:
        raise WebDavError(f"写入本地文件失败：{exc}") from exc


def delete_file(conn, remote_name: str) -> None:
    if "/" in remote_name or ".." in remote_name:
        raise WebDavError("远端文件名不合法")
    _request(conn, "DELETE", f"{_base(conn)}/{remote_name}")


def list_backups(conn) -> list[dict]:
    """列出远端备份（PROPFIND 深度 1，解析 XML）。"""
    body = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:"><D:prop>
<D:displayname/><D:getcontentlength/><D:getlastmodified/>
</D:prop></D:propfind>"""
    try:
        with _client(conn) as client:
            resp = client.request("PROPFIND", _base(conn), content=body.encode(),
                                   headers={"Depth": "1"})
    except httpx.HTTPError as exc:
        raise WebDavError(f"连接失败：{exc}") from exc
    if resp.status_code >= 400:
        raise WebDavError(f"PROPFIND 失败：HTTP {resp.status_code}")
    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError as exc:
        raise WebDavError(f"远端返回的不是合法 PROPFIND 响应：{exc}") from exc
    ns = {"D": "DAV:"}
    items: list[dict] = []
    for node in root.findall("D:response", ns):
        href = node.findtext("D:href", default="", namespaces=ns)
        name = href.rstrip("/").split("/")[-1]
        if not name or not name.startswith(PREFIX):
            continue
        props = node.find("D:propstat/D:prop", ns)
        size = 0
        modified = ""
        if props is not None:
            size_text = props.findtext("D:getcontentlength", default="0", namespaces=ns)
            try:
                size = int(size_text or 0)
            except ValueError:
                size = 0
            modified = props.findtext("D:getlastmodified", default="", namespaces=ns)
        items.append({"name": name, "size": size, "modified": modified})
    items.sort(key=lambda x: x["name"], reverse=True)
    return items


def run_backup(conn, operator: str = "系统", trigger: str = "auto") -> dict:
    """只上传认证加密归档与安全外层元数据；主密钥独立保管。"""
    from . import backups
    if not is_configured(conn):
        raise WebDavError("尚未配置 WebDAV 地址")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(4)
    tmpdir = Path(tempfile.mkdtemp(prefix="mp-webdav-"))
    uploaded: list[str] = []
    try:
        tmpdir.chmod(0o700)
        archive = tmpdir / f"{PREFIX}{stamp}{ARCHIVE_SUFFIX}"
        # 运行时资源（mihomo 核心 + geo 数据）默认不进归档：可重新下载，
        # 带着它们会让归档 150MB+ 超 WebDAV 请求体上限（HTTP 413，2026-11-18 实证）
        include_runtime = _setting(conn, "backup_include_runtime", "0") == "1"
        report = backups.create_archive(conn, archive, include_runtime=include_runtime)
        metadata = tmpdir / f"{PREFIX}{stamp}{META_SUFFIX}"
        from .backup_archive import _open_private
        with _open_private(metadata) as handle:
            handle.write(json.dumps({"format": "mpbackup", "version": 1, "encrypted": True,
                                      "created_at": db.now(), "size": report["size"],
                                      "key_included": False}).encode("utf-8"))
        for local in (archive, metadata):
            upload_file(conn, local, local.name)
            uploaded.append(local.name)

        keep = _keep_count(conn)
        removed = _prune_remote(conn, keep)
        result = {
            "stamp": stamp,
            "files": uploaded,
            "removed": removed,
            "trigger": trigger,
        }
        with db.tx() as wconn:
            db.set_setting(wconn, SET_LAST_AT, db.now())
            db.set_setting(wconn, SET_LAST_STATUS, "成功")
            db.set_setting(wconn, SET_LAST_ERROR, "")
            security.audit(wconn, operator, "WebDAV 备份", "backup", stamp, result)
        return result
    except Exception as exc:
        message = str(exc) if isinstance(exc, WebDavError) else "backup_failed"
        with db.tx() as wconn:
            db.set_setting(wconn, SET_LAST_STATUS, "失败")
            db.set_setting(wconn, SET_LAST_ERROR, message[:500])
            security.audit(wconn, operator, "WebDAV 备份失败", "backup", "",
                           {"error": message[:500]})
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _keep_count(conn) -> int:
    try:
        return max(1, int(_setting(conn, SET_KEEP, "7")))
    except ValueError:
        return 7


def _prune_remote(conn, keep: int) -> int:
    """仅轮转新加密归档；历史 db/key 不自动删除。"""
    items = [i for i in list_backups(conn) if i["name"].endswith(ARCHIVE_SUFFIX)]
    removed = 0
    for item in items[keep:]:
        stamp = item["name"][len(PREFIX):-len(ARCHIVE_SUFFIX)]
        try:
            delete_file(conn, item["name"])
            removed += 1
        except WebDavError:
            continue
        try:
            delete_file(conn, f"{PREFIX}{stamp}{META_SUFFIX}")
        except WebDavError:
            pass
    return removed


def restore_from_remote(conn, remote_name: str, operator: str, *, destination: Path | None = None,
                        key_path: Path | None = None, legacy: bool = False) -> dict:
    """下载到私有临时目录，仅验证并生成调用方指定的新 staging。"""
    from . import backups
    if destination is None or (key_path is None and not legacy):
        raise WebDavError("backup_staging_required")
    if (not isinstance(remote_name, str) or "/" in remote_name or "\\" in remote_name or
            ".." in remote_name or not remote_name.startswith(PREFIX)):
        raise WebDavError("archive_invalid")
    if remote_name.endswith(DB_SUFFIX) and not legacy:
        raise WebDavError("legacy_restore_required")
    if not remote_name.endswith(DB_SUFFIX if legacy else ARCHIVE_SUFFIX):
        raise WebDavError("archive_invalid_extension")
    # HTTP 只会给出此固定父目录；离线调用方的其它父目录必须已存在。
    staging_root = config.DATA_DIR / "restore-staging"
    if Path(destination).absolute().parent == staging_root:
        from .backup_archive import _check_parents
        try:
            _check_parents(staging_root)
            staging_root.mkdir(mode=0o700, exist_ok=True)
            staging_root.chmod(0o700)
        except (OSError, ValueError):
            raise WebDavError("archive_invalid_path") from None
    tmpdir = Path(tempfile.mkdtemp(prefix="mp-restore-"))
    try:
        tmpdir.chmod(0o700)
        local = tmpdir / remote_name
        download_file(conn, remote_name, local)
        local.chmod(0o600)
        if not legacy:
            backups.restore_archive(local, Path(destination), key_path=Path(key_path))
            return _staged_result(Path(destination))
        key_local = Path(key_path) if key_path is not None else tmpdir / "legacy.key"
        if key_path is None:
            stamp = remote_name[len(PREFIX):-len(DB_SUFFIX)]
            key_name = f"{PREFIX}{stamp}{KEY_SUFFIX}"
            download_file(conn, key_name, key_local, max_bytes=4096)
            key_local.chmod(0o600)
        return _restore_files(local, key_local, operator, destination=Path(destination), legacy=True)
    except (ValueError, security.DecryptError) as exc:
        raise WebDavError(str(exc)) from None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _staged_result(destination: Path, *, legacy: bool = False) -> dict:
    return {"status": "STAGED", "verification_status": "VERIFIED", "restored": False,
            "staging_name": destination.name, "requires_maintenance_restart": True,
            "key_restored": False, "legacy_import": legacy, "complete_archive": not legacy}


def _restore_files(local_db: Path, key_local: Path | None, operator: str, *,
                   destination: Path | None = None, key_path: Path | None = None,
                   legacy: bool = False) -> dict:
    """显式历史物理库导入：可信当前 schema → 新 staging，绝不覆盖运行库。"""
    from . import backups
    from .backup_archive import (_open_private, _validate_database, sanitize_restored,
                                 staging_directory)
    if destination is None:
        raise WebDavError("backup_staging_required")
    if not legacy:
        raise WebDavError("legacy_restore_required")
    supplied_key = key_local if key_local is not None else key_path
    if supplied_key is None:
        raise WebDavError("key_required")
    try:
        master = security.read_master_material(Path(supplied_key))
    except security.DecryptError as exc:
        raise WebDavError(str(exc)) from None
    source = sqlite3.connect(local_db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        source.row_factory = sqlite3.Row
        source.execute("PRAGMA trusted_schema=OFF")
        source.execute("BEGIN")
        with staging_directory(Path(destination)) as stage:
            target = stage / "magicpanel.db"
            with _open_private(target):
                pass
            with db.connect() as template, backups._staging_schema(template) as schema:
                with closing(sqlite3.connect(target)) as conn:
                    schema.backup(conn)
            with closing(sqlite3.connect(target)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                # v1 合并当前迁移标记，但不导入运行库的策略或历史行。
                with db.connect() as template:
                    conn.executemany("INSERT INTO schema_version(key,value) VALUES(?,?)",
                                     [tuple(row) for row in template.execute("SELECT key,value FROM schema_version")])
                backups.restore_legacy_database(conn, source)
                if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit'").fetchone():
                    allowed = {row["name"] for row in backups._columns(conn, "audit")}
                    if {row["name"] for row in backups._columns(source, "audit")} != allowed:
                        raise ValueError("backup_invalid")
                    for row in backups._rows(source, "audit"):
                        columns = ','.join(backups._quote(column) for column in row)
                        conn.execute(f'INSERT INTO audit({columns}) VALUES({",".join("?" for _ in row)})', tuple(row.values()))
                sanitize_restored(conn)
                conn.commit()
                versions = dict(conn.execute("SELECT key,value FROM schema_version"))
            _validate_database(stage, master, versions)
            with _open_private(stage / "secret.key") as handle:
                handle.write(base64.urlsafe_b64encode(master))
    except (ValueError, sqlite3.Error) as exc:
        code = str(exc) if str(exc) in {
            "backup_invalid", "backup_invalid_reference", "backup_missing_variants",
            "backup_missing_resource", "backup_schema_unregistered", "private_blob_corrupt",
            "archive_destination_exists", "archive_invalid_path", "archive_runtime_destination_forbidden",
        } else "backup_invalid"
        raise WebDavError(code) from None
    finally:
        source.close()
    return _staged_result(Path(destination), legacy=True)


def status(conn) -> dict:
    url, username, _, directory = _credentials(conn)
    encrypted = _setting(conn, SET_PASS)
    return {
        "enabled": _setting(conn, SET_ENABLED, "0") == "1",
        "url": url,
        "username": username,
        "directory": directory,
        "password_set": bool(encrypted),
        "interval_hours": _setting(conn, SET_INTERVAL, "12"),
        "keep": _setting(conn, SET_KEEP, "7"),
        "last_backup_at": _setting(conn, SET_LAST_AT),
        "last_status": _setting(conn, SET_LAST_STATUS),
        "last_error": _setting(conn, SET_LAST_ERROR),
    }


# 前端字段名 → 设置项键名
FIELD_TO_SETTING = {
    "enabled": SET_ENABLED,
    "url": SET_URL,
    "username": SET_USER,
    "directory": SET_DIR,
    "interval_hours": SET_INTERVAL,
    "keep": SET_KEEP,
}


def save_settings(conn, values: dict) -> None:
    """保存 WebDAV 配置（口令加密存储，不回显）。

    字段名用界面上的说法（enabled / url / directory / username /
    password / interval_hours / keep），落到设置表时统一加前缀。
    """
    for field, key in FIELD_TO_SETTING.items():
        if field in values:
            value = values[field]
            if value is None:
                continue
            db.set_setting(conn, key, str(value).strip())
    if "password" in values:
        password = values["password"]
        if password:                       # 非空：设置新口令
            db.set_setting(conn, SET_PASS, security.encrypt_payload(str(password)))
        elif password is None:             # None：清除口令
            db.set_setting(conn, SET_PASS, "")
