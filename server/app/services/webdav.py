"""WebDAV 备份：把数据库快照与主密钥推到远端，并支持从远端恢复。

为什么必须有：容器内的备份与数据在同一个磁盘上，NAS 一次磁盘故障
就会把备份一起带走。远端（WebDAV）是唯一能跨故障保存副本的地方。

约定与边界：
- 只做"整库快照 + 主密钥"两件文件的复制，不做增量；
- 远端文件名带时间戳，保留最近 N 份，超出的自动清理；
- 口令用主密钥加密后入库，接口不会回显明文；
- 恢复前必须校验快照可用（integrity_check），且要求显式确认。
"""
import logging
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


def download_file(conn, remote_name: str, local_path: Path) -> None:
    """下载远端文件到本地路径。"""
    if "/" in remote_name or ".." in remote_name:
        raise WebDavError("远端文件名不合法")
    source = f"{_base(conn)}/{remote_name}"
    try:
        with _client(conn) as client:
            with client.stream("GET", source) as resp:
                if resp.status_code >= 400:
                    raise WebDavError(f"HTTP {resp.status_code}")
                with local_path.open("wb") as handle:
                    for chunk in resp.iter_bytes():
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


def _snapshot_to_temp(conn) -> Path:
    """生成数据库一致性快照（VACUUM INTO），返回临时文件路径。"""
    tmpdir = Path(tempfile.mkdtemp(prefix="mp-webdav-"))
    target = tmpdir / f"{PREFIX}local.db"
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    except sqlite3.Error as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise WebDavError(f"生成数据库快照失败：{exc}") from exc
    return target


def run_backup(conn, operator: str = "系统", trigger: str = "auto") -> dict:
    """执行一次完整备份：本地快照 + 主密钥 → 上传 → 清理旧副本。"""
    if not is_configured(conn):
        raise WebDavError("尚未配置 WebDAV 地址")
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    # 同一秒内重复备份要生成不同文件名，否则后一次会覆盖前一次
    suffix = 0
    while any(name.startswith(f"{PREFIX}{stamp}") for name in _remote_names(conn)):
        suffix += 1
        stamp = f"{datetime.now(timezone.utc).astimezone().strftime('%Y%m%d-%H%M%S')}-{suffix}"
    tmpdir = Path(tempfile.mkdtemp(prefix="mp-webdav-"))
    uploaded: list[str] = []
    try:
        snapshot = tmpdir / f"{PREFIX}{stamp}{DB_SUFFIX}"
        try:
            conn.execute("VACUUM INTO ?", (str(snapshot),))
        except sqlite3.Error as exc:
            raise WebDavError(f"生成数据库快照失败：{exc}") from exc
        # 快照必须可用才上传
        check = sqlite3.connect(str(snapshot))
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise WebDavError("生成的快照自检未通过，已中止上传")
        finally:
            check.close()
        upload_file(conn, snapshot, snapshot.name)
        uploaded.append(snapshot.name)

        key_file = config.SECRET_KEY_PATH
        if key_file.exists():
            remote_key = f"{PREFIX}{stamp}{KEY_SUFFIX}"
            upload_file(conn, key_file, remote_key)
            uploaded.append(remote_key)

        # 轮转：只保留最近 N 份快照（成对删除 db 与 key）
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
        message = str(exc)
        with db.tx() as wconn:
            db.set_setting(wconn, SET_LAST_STATUS, "失败")
            db.set_setting(wconn, SET_LAST_ERROR, message[:500])
            security.audit(wconn, operator, "WebDAV 备份失败", "backup", "",
                           {"error": message[:500]})
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _remote_names(conn) -> list[str]:
    try:
        return [item["name"] for item in list_backups(conn)]
    except WebDavError:
        return []


def _keep_count(conn) -> int:
    try:
        return max(1, int(_setting(conn, SET_KEEP, "7")))
    except ValueError:
        return 7


def _prune_remote(conn, keep: int) -> int:
    """远端只保留最近 keep 份快照（db 与 key 一起删）。"""
    items = [i for i in list_backups(conn) if i["name"].endswith(DB_SUFFIX)]
    removed = 0
    for item in items[keep:]:
        stamp = item["name"][len(PREFIX):-len(DB_SUFFIX)]
        try:
            delete_file(conn, item["name"])
            removed += 1
        except WebDavError:
            continue
        try:
            delete_file(conn, f"{PREFIX}{stamp}{KEY_SUFFIX}")
        except WebDavError:
            pass
    return removed


def restore_from_remote(conn, remote_name: str, operator: str) -> dict:
    """从远端快照恢复数据库与主密钥。

    恢复前会校验快照完整性；主密钥会一并还原（否则密文全都解不开）。
    """
    if not remote_name.startswith(PREFIX) or not remote_name.endswith(DB_SUFFIX):
        raise WebDavError("只能恢复本系统的数据库快照")
    tmpdir = Path(tempfile.mkdtemp(prefix="mp-restore-"))
    try:
        local_db = tmpdir / remote_name
        download_file(conn, remote_name, local_db)
        check = sqlite3.connect(str(local_db))
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise WebDavError("远端快照自检未通过，已中止恢复")
            tables = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            check.close()
        if "base_configs" not in tables or "users" not in tables:
            raise WebDavError("远端文件不是 MagicPanel 的数据库快照")
        # 主密钥：与快照同名的 .key
        stamp = remote_name[len(PREFIX):-len(DB_SUFFIX)]
        key_name = f"{PREFIX}{stamp}{KEY_SUFFIX}"
        key_local = tmpdir / key_name
        try:
            download_file(conn, key_name, key_local)
        except WebDavError:
            key_local = None
        return _restore_files(local_db, key_local, operator)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _restore_files(local_db: Path, key_local: Path | None, operator: str) -> dict:
    """用快照文件覆盖当前数据库（必要时同时替换主密钥）。"""
    from ..routers.misc import RESTORE_TABLES
    source = sqlite3.connect(str(local_db))
    try:
        source.row_factory = sqlite3.Row
        rows = {}
        for table in RESTORE_TABLES:
            try:
                rows[table] = [dict(r) for r in source.execute(
                    f"SELECT * FROM {table}").fetchall()]
            except sqlite3.Error:
                rows[table] = []
        with db.tx() as conn:
            for table in reversed(RESTORE_TABLES):
                conn.execute(f"DELETE FROM {table}")
            for table in RESTORE_TABLES:
                for row in rows.get(table) or []:
                    if not isinstance(row, dict) or not row:
                        continue
                    allowed = [r["name"] for r in conn.execute(
                        f"PRAGMA table_info({table})")]
                    columns = [c for c in row.keys() if c in allowed]
                    if not columns:
                        continue
                    marks = ",".join("?" for _ in columns)
                    conn.execute(
                        f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})",
                        tuple(row[c] for c in columns))
            security.audit(conn, operator, "从 WebDAV 恢复备份", "backup", "",
                           {"file": local_db.name})
    finally:
        source.close()
    if key_local and key_local.exists():
        # 换密钥后必须重启进程才能解密旧密文，这里只落盘并提示
        shutil.copyfile(key_local, config.SECRET_KEY_PATH)
        try:
            config.SECRET_KEY_PATH.chmod(0o600)
        except OSError:
            pass
    return {"restored": True, "key_restored": bool(key_local and key_local.exists())}


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
