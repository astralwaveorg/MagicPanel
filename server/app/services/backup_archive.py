"""有界流式加密归档；认证通过后才允许解包到新 staging。"""
import base64
from contextlib import closing, contextmanager
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tarfile
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .. import config, security
from . import backup_tables, repo_manager

MAGIC = b"MPBACKUP\x00\x01"
HEADER_SIZE = len(MAGIC) + 12
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + 128 * 1024 * 1024
MAX_FILES = 100_000
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MANIFEST_NAME = "manifest.json"


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _relative(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("archive_invalid_path")
    path = PurePosixPath(name)
    if (path.is_absolute() or str(path) != name or len(name) > 4096 or
            any(part in {".", "..", ""} or ":" in part or part.endswith((".", " "))
                or part.split(".", 1)[0].upper() in {
                    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))} for part in path.parts)):
        raise ValueError("archive_invalid_path")
    return path


def _path(root: Path, name: str) -> Path:
    path = root.joinpath(*_relative(name).parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("archive_invalid_path")
    return path


def _managed_path(name: str) -> bool:
    parts = _relative(name).parts
    return (name in {"magicpanel.db", "bin/mihomo"} or
            (len(parts) >= 3 and parts[0] == "builds" and parts[1].isdigit()) or
            (len(parts) >= 2 and parts[0] == "avatars") or
            (len(parts) >= 3 and parts[:2] == ("deps", "rule-repo")) or
            (len(parts) == 2 and parts[0] == "core-work" and
             PurePosixPath(parts[1]).suffix.lower() in {".dat", ".mmdb"}))


def _fingerprint(path: Path) -> tuple:
    item = path.lstat()
    if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1:
        raise ValueError("archive_unsafe_file")
    return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns,
            stat.S_IMODE(item.st_mode))


def _check_parents(path: Path) -> None:
    if any(_linked(parent) for parent in (path, *path.parents)):
        raise ValueError("archive_invalid_path")


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _mkdir_private(path: Path) -> None:
    if _linked(path):
        raise ValueError("archive_invalid_path")
    if path.exists():
        if not path.is_dir():
            raise ValueError("archive_invalid_path")
        return
    _mkdir_private(path.parent)
    path.mkdir(mode=0o700)
    path.chmod(0o700)


def _target(destination: Path, *, archive: bool = False) -> Path:
    destination = Path(destination).absolute()
    _check_parents(destination)
    if destination.exists():
        raise ValueError("archive_destination_exists")
    if not destination.parent.is_dir():
        raise ValueError("archive_invalid_path")
    resolved = destination.resolve()
    runtime = config.DATA_DIR.resolve()
    isolated_child = (resolved.parent == runtime / "restore-staging" and len(resolved.name) == 32 and
                      all(char in "0123456789abcdef" for char in resolved.name))
    if not archive and (resolved == runtime or runtime.is_relative_to(resolved) or
                        (resolved.is_relative_to(runtime) and not isolated_child)):
        raise ValueError("archive_runtime_destination_forbidden")
    return destination


def _open_private(path: Path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                            getattr(os, "O_NOFOLLOW", 0), 0o600), "wb")


@contextmanager
def staging_directory(destination: Path):
    """只清理本次独占创建且身份未变的目录。"""
    destination = _target(destination)
    destination.mkdir(mode=0o700)
    destination.chmod(0o700)
    identity = destination.stat()
    try:
        yield destination
    except BaseException:
        try:
            current = destination.lstat()
        except FileNotFoundError:
            raise
        if (not _linked(destination) and current.st_dev == identity.st_dev and
                current.st_ino == identity.st_ino):
            shutil.rmtree(destination)
        raise


def _scan_tree(root: Path, folder: str, result: dict) -> None:
    start = _path(root, folder)
    if not start.exists() and not start.is_symlink():
        return
    if _linked(start) or not start.is_dir():
        raise ValueError("archive_unsafe_file")
    for directory, dirs, files in os.walk(start, followlinks=False):
        for name in dirs:
            if _linked(Path(directory) / name):
                raise ValueError("archive_unsafe_file")
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            _relative(relative)
            # Git 临时锁与其它临时文件不得充当已完成资源。
            if name.endswith((".lock", ".tmp", ".part")):
                raise ValueError("archive_resource_busy")
            result[relative] = _fingerprint(path)


def _inventory(root: Path, tables: dict) -> dict:
    result = {}
    for build in tables["builds"]:
        if build["status"] in {"BUILT", "TESTING", "PRODUCTION", "OFFLINE"} and build["verify_status"] != "building":
            _scan_tree(root, f"builds/{build['id']}", result)
    for folder in ("avatars", "deps/rule-repo"):
        _scan_tree(root, folder, result)
    core = root / "bin/mihomo"
    if core.exists() or core.is_symlink():
        _check_parents(core)
        result["bin/mihomo"] = _fingerprint(core)
    geo = root / "core-work"
    if geo.exists() or geo.is_symlink():
        if geo.is_symlink() or not geo.is_dir():
            raise ValueError("archive_unsafe_file")
        for item in geo.iterdir():
            if item.suffix.lower() in {".dat", ".mmdb"}:
                result[item.relative_to(root).as_posix()] = _fingerprint(item)
    if len(result) + 1 > MAX_FILES:
        raise ValueError("archive_limit_exceeded")
    if any(info[2] > MAX_FILE_BYTES for info in result.values()) or sum(info[2] for info in result.values()) > MAX_TOTAL_BYTES:
        raise ValueError("archive_limit_exceeded")
    return result


def _copy_file(source: Path, destination: Path, expected: tuple) -> dict:
    _check_parents(source)
    if _fingerprint(source) != expected:
        raise ValueError("archive_resource_changed")
    _mkdir_private(destination.parent)
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as reader, _open_private(destination) as writer:
        for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError("archive_limit_exceeded")
            digest.update(chunk)
            writer.write(chunk)
    if _fingerprint(source) != expected or size != expected[2]:
        raise ValueError("archive_resource_changed")
    mode = 0o700 if expected[5] & 0o111 else 0o600
    destination.chmod(mode)
    return {"size": size, "sha256": digest.hexdigest(), "mode": mode}


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError("archive_limit_exceeded")
            digest.update(chunk)
    return size, digest.hexdigest()


def _encrypt_file(plaintext: Path, output: Path, master: bytes) -> None:
    nonce = os.urandom(12)
    header = MAGIC + nonce
    key = security.derive_subkey(master, purpose="backup-archive-encryption")
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(header)
    with plaintext.open("rb") as reader, _open_private(output) as writer:
        writer.write(header)
        for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
            writer.write(cipher.update(chunk))
        writer.write(cipher.finalize())
        writer.write(cipher.tag)
        writer.flush()
        os.fsync(writer.fileno())


def _decrypt_file(archive: Path, output: Path, master: bytes) -> None:
    size = archive.stat().st_size
    if size < HEADER_SIZE + TAG_SIZE or size > MAX_ARCHIVE_BYTES:
        raise ValueError("archive_invalid" if size < HEADER_SIZE + TAG_SIZE else "archive_limit_exceeded")
    with archive.open("rb") as reader:
        header = reader.read(HEADER_SIZE)
        if not header.startswith(MAGIC):
            raise ValueError("archive_invalid")
        reader.seek(-TAG_SIZE, os.SEEK_END)
        tag = reader.read(TAG_SIZE)
        reader.seek(HEADER_SIZE)
        key = security.derive_subkey(master, purpose="backup-archive-encryption")
        cipher = Cipher(algorithms.AES(key), modes.GCM(header[-12:], tag)).decryptor()
        cipher.authenticate_additional_data(header)
        left = size - HEADER_SIZE - TAG_SIZE
        try:
            with _open_private(output) as writer:
                while left:
                    chunk = reader.read(min(CHUNK_SIZE, left))
                    if not chunk:
                        raise ValueError("archive_authentication_failed")
                    left -= len(chunk)
                    writer.write(cipher.update(chunk))
                writer.write(cipher.finalize())
        except InvalidTag:
            raise ValueError("archive_authentication_failed") from None


def _manifest_mac(manifest: dict, master: bytes) -> str:
    key = security.derive_subkey(master, purpose="backup-manifest-mac")
    return hmac.new(key, _canonical(manifest), hashlib.sha256).hexdigest()


def create_archive(conn, destination: Path) -> dict:
    from . import backups
    if conn.in_transaction:
        raise ValueError("archive_requires_idle_connection")
    destination = _target(destination, archive=True)
    if destination.suffix != ".mpbackup":
        raise ValueError("archive_invalid_extension")
    root = backups._data_dir(conn)
    master = security.load_master_material()
    with tempfile.TemporaryDirectory(prefix=".mp-archive-", dir=destination.parent) as temp:
        work = Path(temp)
        work.chmod(0o700)
        snapshot = work / "magicpanel.db"
        with _open_private(snapshot):
            pass
        with closing(sqlite3.connect(snapshot)) as copy:
            conn.backup(copy)
        snapshot.chmod(0o600)
        with closing(sqlite3.connect(snapshot)) as copy:
            copy.row_factory = sqlite3.Row
            copy.execute("BEGIN")
            tables = {table: backups._rows(copy, table) for table in backup_tables.registered_tables(copy)}
            required = backups._required_files(tables)
            versions = dict(copy.execute("SELECT key,value FROM schema_version ORDER BY key"))
        files = []
        size, digest = _hash_file(snapshot)
        files.append({"path": "magicpanel.db", "size": size, "sha256": digest, "mode": 0o600})
        with repo_manager.operation("复制备份仓库"):
            inventory = _inventory(root, tables)
            if required.keys() - inventory.keys():
                raise ValueError("backup_missing_resource")
            for relative, fingerprint in sorted(inventory.items()):
                record = {"path": relative, **_copy_file(_path(root, relative), _path(work, relative), fingerprint)}
                if relative in required and any(record[key] != required[relative][key] for key in ("size", "sha256")):
                    raise ValueError("backup_missing_resource")
                files.append(record)
            if inventory != _inventory(root, tables):
                raise ValueError("archive_resource_changed")
        if sum(item["size"] for item in files) > MAX_TOTAL_BYTES:
            raise ValueError("archive_limit_exceeded")
        _validate_database(work, master, versions)
        manifest = {"format": "MagicPanel/private-archive", "version": 1,
                    "schema_versions": versions, "files": files}
        encoded = _canonical({"manifest": manifest, "mac": _manifest_mac(manifest, master)})
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise ValueError("archive_limit_exceeded")
        plaintext = work / "archive-plaintext.tar"
        with _open_private(plaintext) as writer, tarfile.open(fileobj=writer, mode="w:") as tar:
            info = tarfile.TarInfo(MANIFEST_NAME)
            info.size, info.mode = len(encoded), 0o600
            tar.addfile(info, io.BytesIO(encoded))
            for record in files:
                info = tarfile.TarInfo(record["path"])
                info.size, info.mode = record["size"], record["mode"]
                with _path(work, record["path"]).open("rb") as handle:
                    tar.addfile(info, handle)
        if plaintext.stat().st_size + HEADER_SIZE + TAG_SIZE > MAX_ARCHIVE_BYTES:
            raise ValueError("archive_limit_exceeded")
        encrypted = work / "complete.mpbackup"
        _encrypt_file(plaintext, encrypted, master)
        if destination.exists():
            raise ValueError("archive_destination_exists")
        encrypted.rename(destination)
    return {"format": "mpbackup", "version": 1, "encrypted": True,
            "files": len(files), "size": destination.stat().st_size, "key_included": False}


def _load_manifest(tar, members: list, master: bytes) -> dict:
    matches = [item for item in members if item.name == MANIFEST_NAME]
    if len(matches) != 1 or matches[0].size > MAX_MANIFEST_BYTES:
        raise ValueError("archive_invalid_manifest")
    try:
        with tar.extractfile(matches[0]) as handle:
            envelope = json.loads(handle.read(MAX_MANIFEST_BYTES + 1))
        if not isinstance(envelope, dict) or set(envelope) != {"manifest", "mac"}:
            raise ValueError
        manifest = envelope["manifest"]
        if (not isinstance(envelope["mac"], str) or
                not hmac.compare_digest(_manifest_mac(manifest, master), envelope["mac"])):
            raise ValueError
        if (set(manifest) != {"format", "version", "schema_versions", "files"} or
                manifest["format"] != "MagicPanel/private-archive" or type(manifest["version"]) is not int or
                manifest["version"] != 1 or not isinstance(manifest["schema_versions"], dict) or
                not isinstance(manifest["files"], list)):
            raise ValueError
    except (TypeError, KeyError, ValueError, UnicodeError):
        raise ValueError("archive_invalid_manifest") from None
    return manifest


def _unpack(plaintext: Path, destination: Path, master: bytes) -> dict:
    try:
        with tarfile.open(plaintext, "r:") as tar:
            members, names, total = [], set(), 0
            for member in tar:
                _relative(member.name)
                normalized = member.name.casefold()
                if normalized in names:
                    raise ValueError("archive_duplicate_path")
                names.add(normalized)
                if not member.isfile() or member.issparse() or member.linkname:
                    raise ValueError("archive_unsafe_file")
                total += member.size
                if member.size < 0 or member.size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES or len(members) >= MAX_FILES + 1:
                    raise ValueError("archive_limit_exceeded")
                members.append(member)
            manifest = _load_manifest(tar, members, master)
            records = {}
            for record in manifest["files"]:
                if (not isinstance(record, dict) or set(record) != {"path", "size", "sha256", "mode"} or
                        type(record["size"]) is not int or record["size"] < 0 or record["size"] > MAX_FILE_BYTES or
                        record["mode"] not in {0o600, 0o700} or not isinstance(record["sha256"], str) or
                        len(record["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in record["sha256"])):
                    raise ValueError("archive_invalid_manifest")
                name = record["path"]
                _relative(name)
                if name in records or not _managed_path(name):
                    raise ValueError("archive_invalid_manifest")
                records[name] = record
            if "magicpanel.db" not in records or set(records) != {item.name for item in members} - {MANIFEST_NAME}:
                raise ValueError("archive_invalid_manifest")
            for member in members:
                if member.name == MANIFEST_NAME:
                    continue
                record = records[member.name]
                if member.size != record["size"]:
                    raise ValueError("archive_invalid_manifest")
                target = _path(destination, member.name)
                _mkdir_private(target.parent)
                digest, count = hashlib.sha256(), 0
                with tar.extractfile(member) as reader, _open_private(target) as writer:
                    for chunk in iter(lambda: reader.read(CHUNK_SIZE), b""):
                        digest.update(chunk)
                        count += len(chunk)
                        writer.write(chunk)
                if count != record["size"] or digest.hexdigest() != record["sha256"]:
                    raise ValueError("archive_resource_corrupt")
                target.chmod(record["mode"])
            return manifest
    except (tarfile.TarError, EOFError, OSError):
        raise ValueError("archive_invalid") from None


def _validate_database(destination: Path, master: bytes, versions: dict) -> None:
    from . import backups, resource_store
    path = destination / "magicpanel.db"
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("BEGIN")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("backup_invalid")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') OR upper(sql) LIKE 'CREATE VIRTUAL%'").fetchone():
            raise ValueError("backup_invalid")
        if dict(conn.execute("SELECT key,value FROM schema_version")) != versions:
            raise ValueError("archive_schema_mismatch")
        payload = backups.export_logical(conn)
        backups.validate_logical(conn, payload)
        fernet = Fernet(base64.urlsafe_b64encode(master))
        for table in backup_tables.BACKUP_TABLES:
            for row in backups._rows(conn, table):
                for column, value in row.items():
                    if isinstance(value, str) and value:
                        if column.endswith("_enc"):
                            token = value[len(security.PAYLOAD_PREFIX):] if value.startswith(security.PAYLOAD_PREFIX) else value
                            fernet.decrypt(token.encode("ascii"))
                        elif value.startswith(security.PAYLOAD_PREFIX):
                            fernet.decrypt(value[len(security.PAYLOAD_PREFIX):].encode("ascii"))
        for row in conn.execute("SELECT * FROM private_blobs"):
            if (row["key_version"] != 1 or row["kind"] not in resource_store.KINDS or
                    row["size"] > resource_store.MAX_PRIVATE_BYTES or not isinstance(row["ciphertext"], bytes) or
                    hashlib.sha256(row["ciphertext"]).hexdigest() != row["ciphertext_sha256"]):
                raise ValueError("private_blob_corrupt")
            body = fernet.decrypt(row["ciphertext"])
            key = security.derive_subkey(master, purpose="private-blob-hmac")
            material_hmac = hmac.new(key, row["kind"].encode("ascii") + b"\x00" + body, hashlib.sha256).hexdigest()
            if len(body) != row["size"] or not hmac.compare_digest(material_hmac, row["material_hmac"]):
                raise ValueError("private_blob_corrupt")
    except (sqlite3.Error, InvalidToken, UnicodeError, TypeError):
        raise ValueError("backup_invalid") from None
    finally:
        conn.close()


def sanitize_restored(conn) -> None:
    """恢复保留历史，但撤销会话和未完成执行权。"""
    actual = {item[0] for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in backup_tables.reset_tables(conn):
        conn.execute(f'DELETE FROM "{table}"')
    for table in ("probe_jobs", "probe_items"):
        if table in actual:
            columns = {item[1] for item in conn.execute(f'PRAGMA table_info("{table}")')}
            assignments = ["state='cancelled'"]
            assignments.extend(f'"{column}"=NULL' for column in ("lease_owner", "lease_until") if column in columns)
            if "cancel_requested" in columns:
                assignments.append("cancel_requested=1")
            conn.execute(f'UPDATE "{table}" SET {",".join(assignments)} '
                         "WHERE state NOT IN ('completed','succeeded','failed','cancelled','expired')")
    for table, column in (("managed_execution_owners", "status"), ("managed_selection_state", "mirror_state")):
        if table in actual:
            conn.execute(f'UPDATE "{table}" SET "{column}"=\'reconcile_required\' '
                         f'WHERE "{column}"<>\'retired\'')
    if "managed_apply_intents" in actual:
        conn.execute("UPDATE managed_apply_intents SET state='reconcile_required' "
                     "WHERE state NOT IN ('verified','rejected')")


def restore_archive(archive: Path, destination: Path, *, key_path: Path) -> dict:
    archive = Path(archive)
    if archive.suffix != ".mpbackup":
        raise ValueError("archive_invalid_extension")
    _check_parents(archive)
    if not archive.is_file():
        raise ValueError("archive_invalid")
    try:
        master = security.read_master_material(Path(key_path))
    except security.DecryptError as exc:
        raise ValueError(str(exc)) from None
    with staging_directory(destination) as stage:
        plaintext = stage / ".archive-plaintext.tar"
        _decrypt_file(archive, plaintext, master)
        manifest = _unpack(plaintext, stage, master)
        plaintext.unlink()
        _validate_database(stage, master, manifest["schema_versions"])
        with closing(sqlite3.connect(stage / "magicpanel.db")) as conn:
            conn.execute("PRAGMA trusted_schema=OFF")
            sanitize_restored(conn)
            conn.commit()
        # 副本中的 WAL/SHM 只可能属于本次验证连接，不作为恢复资源。
        for suffix in ("-wal", "-shm"):
            (stage / ("magicpanel.db" + suffix)).unlink(missing_ok=True)
        with _open_private(stage / "secret.key") as handle:
            handle.write(base64.urlsafe_b64encode(master))
        (stage / "magicpanel.db").chmod(0o600)
    return {"status": "VERIFIED", "files": len(manifest["files"]), "key_installed": True,
            "manifest_verified": True, "requires_maintenance_restart": True}
