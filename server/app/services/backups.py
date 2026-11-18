"""逻辑快照与先校验后恢复；外部文件仍须由完整私密归档携带。"""
from contextlib import contextmanager
from datetime import datetime
import base64
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sqlite3

from .. import config, db
from . import backup_tables, local_nodes


def _require_transaction(conn) -> None:
    if not conn.in_transaction:
        raise ValueError("backup_transaction_required")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _columns(conn, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"PRAGMA table_info({_quote(table)})"))


def _rows(conn, table: str) -> list[dict]:
    primary = sorted((r for r in _columns(conn, table) if r["pk"]), key=lambda r: r["pk"])
    order = ",".join(_quote(r["name"]) for r in primary) or "rowid"
    return [dict(row) for row in conn.execute(f"SELECT * FROM {_quote(table)} ORDER BY {order}")]


def _data_dir(conn) -> Path:
    path = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not path:
        raise ValueError("backup_missing_resource")
    return Path(path).resolve().parent


def _json_object(value) -> dict:
    try:
        result = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError("backup_invalid") from None
    if not isinstance(result, dict):
        raise ValueError("backup_invalid")
    return result


def _kept_build_ids(tables: dict) -> set[int]:
    """备份视角的产物保留窗口（与 retention._kept_build_ids 同口径）。

    留存清理会删掉窗口外构建的产物目录（历史行保留归档），备份不再
    要求这些文件：恢复后窗口外构建的产物缺失，再次发布会被
    releases._check_artifacts 拦住，安全。
    """
    published_keep = int(config.PUBLISHED_BUILD_KEEP)
    built_keep = int(config.BUILD_ARTIFACT_KEEP)
    published = sorted((b for b in tables["builds"] if b["status"] != "BUILT"),
                       key=lambda b: int(b["id"]), reverse=True)
    keep = {int(b["id"]) for b in published[:published_keep]}
    keep |= {int(b["id"]) for b in tables["builds"]
             if b["status"] in ("PRODUCTION", "TESTING")}
    built = sorted((b for b in tables["builds"] if b["status"] == "BUILT"),
                   key=lambda b: int(b["id"]), reverse=True)
    keep |= {int(b["id"]) for b in built[:built_keep]}
    return keep


def _required_files(tables: dict) -> dict[str, dict]:
    required = {}
    kept = _kept_build_ids(tables)
    for build in tables["builds"]:
        if int(build["id"]) not in kept:
            # 保留窗口外：产物文件已被留存清理，备份不要求
            # （2026-11-18 修复：原来对所有历史构建要求产物文件，
            # 老构建产物被清理后备份永远 backup_missing_resource）
            continue
        results = _json_object(build["results"])
        for name, item in results.items():
            if not isinstance(item, dict):
                raise ValueError("backup_invalid")
            if not item.get("ok"):
                continue
            if (not isinstance(name, str) or not name or
                    any(char in name for char in '/\\\x00:') or name in {".", ".."}):
                raise ValueError("backup_invalid")
            if (type(item.get("size")) is not int or item["size"] < 0 or
                    not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64 or
                    any(char not in "0123456789abcdef" for char in item["sha256"])):
                raise ValueError("backup_missing_resource")
            path = f"builds/{build['id']}/{name}.yaml"
            required[path] = {"path": path, "size": item["size"], "sha256": item["sha256"]}
        if build["status"] in {"PRODUCTION", "TESTING"} and not any(
                item.get("ok") for item in results.values()):
            raise ValueError("backup_missing_resource")
    return required


def _resource_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative or "\x00" in relative:
        raise ValueError("backup_missing_resource")
    pure = PurePosixPath(relative)
    if (pure.is_absolute() or str(pure) != relative or
            any(part in {"", ".", ".."} or ":" in part for part in pure.parts)):
        raise ValueError("backup_missing_resource")
    path = root.joinpath(*pure.parts)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
        raise ValueError("backup_missing_resource")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("backup_missing_resource")
    return path


def _file_record(root: Path, relative: str) -> dict:
    path = _resource_path(root, relative)
    try:
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError:
        raise ValueError("backup_missing_resource") from None
    return {"path": relative, "size": size, "sha256": digest.hexdigest()}


def _validate_files(conn, payload: dict, tables: dict, *, legacy: bool) -> None:
    required = _required_files(tables)
    manifest = payload.get("files", [] if legacy else None)
    if not isinstance(manifest, list):
        raise ValueError("backup_invalid")
    records = {}
    for item in manifest:
        if (not isinstance(item, dict) or set(item) != {"path", "size", "sha256"} or
                not isinstance(item["path"], str) or type(item["size"]) is not int or
                item["size"] < 0 or not isinstance(item["sha256"], str) or
                len(item["sha256"]) != 64 or
                any(char not in "0123456789abcdef" for char in item["sha256"])):
            raise ValueError("backup_invalid")
        if item["path"] in records:
            raise ValueError("backup_invalid")
        records[item["path"]] = item
    if legacy and "files" not in payload:
        # v1 无 manifest：只能用构建当时记录的 size/hash 验证原目录。
        records = dict(required)
    if records != required:
        raise ValueError("backup_missing_resource")
    if required:
        root = _data_dir(conn)
        for relative, expected in records.items():
            if _file_record(root, relative) != expected:
                raise ValueError("backup_missing_resource")


def export_logical(conn) -> dict:
    """调用方须持有一致性读事务；此服务不提交、不写审计。"""
    _require_transaction(conn)
    tables = {table: _rows(conn, table) for table in backup_tables.registered_tables(conn)}
    required = _required_files(tables)
    files = [_file_record(_data_dir(conn), path) for path in sorted(required)]
    if any(record != required[record["path"]] for record in files):
        raise ValueError("backup_missing_resource")
    for table, column in backup_tables.BLOB_COLUMNS:
        for row in tables[table]:
            value = row[column]
            if not isinstance(value, bytes):
                raise ValueError("backup_invalid")
            row[column] = {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    return {"version": 2, "exported_at": db.now(), "tables": tables,
            "files": files, "key_required": True}


def _normalize(conn, payload: dict) -> tuple[dict, bool]:
    if (not isinstance(payload, dict) or type(payload.get("version")) is not int or
            payload["version"] not in {1, 2} or not isinstance(payload.get("tables"), dict)):
        raise ValueError("backup_invalid")
    moment = payload.get("exported_at")
    try:
        if not isinstance(moment, str) or datetime.fromisoformat(moment).tzinfo is None:
            raise ValueError
    except ValueError:
        raise ValueError("backup_invalid") from None
    legacy = payload["version"] == 1
    supplied = payload["tables"]
    registered = backup_tables.registered_tables(conn)
    missing = set(registered) - set(supplied)
    optional = backup_tables.LEGACY_OPTIONAL_TABLES if legacy else {"variants"}
    if set(supplied) - set(registered) or missing - optional:
        raise ValueError("backup_invalid")
    tables = {}
    for table in registered:
        rows = supplied.get(table, [])
        if not isinstance(rows, list):
            raise ValueError("backup_invalid")
        columns = _columns(conn, table)
        allowed = {row["name"] for row in columns}
        primary = [row for row in columns if row["pk"]]
        for row in rows:
            if not isinstance(row, dict) or not row or set(row) - allowed:
                raise ValueError("backup_invalid")
            for column in primary:
                value = row.get(column["name"])
                kind = int if "INT" in column["type"].upper() else str
                if type(value) is not kind:
                    raise ValueError("backup_invalid")
            row = dict(row)
            for column, value in row.items():
                if (table, column) in backup_tables.BLOB_COLUMNS:
                    try:
                        if (not isinstance(value, dict) or set(value) != {"encoding", "data"} or
                                value["encoding"] != "base64" or not isinstance(value["data"], str)):
                            raise ValueError
                        row[column] = base64.b64decode(value["data"], validate=True)
                    except (ValueError, TypeError):
                        raise ValueError("backup_invalid") from None
                    continue
                if (value is not None and type(value) not in {str, int, float, bool}) or (
                        isinstance(value, float) and not math.isfinite(value)):
                    raise ValueError("backup_invalid")
            tables.setdefault(table, []).append(row)
        tables.setdefault(table, [])
    if "variants" not in supplied:
        used = {row.get("variant_id", 0) for table in ("proxy_groups", "rules") for row in tables[table]}
        if not legacy or used - {0}:
            raise ValueError("backup_missing_variants")
        tables["variants"] = [{"id": 0, "name": "默认", "is_system": 1,
                                "created_at": moment, "updated_at": moment}]
    if legacy:
        # staging 使用当前已迁移结构，旧 marker 不能让下次启动重放迁移。
        current = {row["key"]: row for row in _rows(conn, "schema_version")}
        supplied_keys = {row["key"] for row in tables["schema_version"]}
        tables["schema_version"] = [current.get(row["key"], row) for row in tables["schema_version"]]
        tables["schema_version"].extend(row for key, row in current.items() if key not in supplied_keys)
    if legacy and 'catalog_state' not in supplied:
        tables['catalog_state'] = [{'id': 1, 'revision': 0}]
    if legacy and 'node_catalog' not in supplied:
        tables['schema_version'] = [r for r in tables['schema_version'] if r['key'] != 'v2_catalog']
    return tables, legacy


def _insert(conn, tables: dict) -> None:
    for table in backup_tables.BACKUP_TABLES:
        for row in tables[table]:
            columns = ",".join(_quote(column) for column in row)
            marks = ",".join("?" for _ in row)
            conn.execute(f"INSERT INTO {_quote(table)}({columns}) VALUES({marks})", tuple(row.values()))


@contextmanager
def _staging_schema(conn):
    stage = sqlite3.connect(":memory:")
    stage.row_factory = sqlite3.Row
    stage.execute("PRAGMA foreign_keys=ON")
    try:
        # DDL 仅取当前已迁移的可信数据库，绝不执行备份提供的 SQL。
        for row in conn.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"):
            stage.execute(row[0])
        for row in conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
            stage.execute(row[0])
        yield stage
    finally:
        stage.close()


def _list(row: dict, field: str) -> list:
    try:
        result = json.loads(row[field] or "[]")
    except (KeyError, TypeError, ValueError):
        raise ValueError("backup_invalid_reference") from None
    if not isinstance(result, list):
        raise ValueError("backup_invalid_reference")
    return result


def _validate_references(tables: dict) -> None:
    from . import node_refs
    for group in tables['proxy_groups']:
        if group.get('members_format') not in ('legacy', 'typed-v2'):
            raise ValueError('backup_invalid')
    try:
        groups = tables['proxy_groups']
        # Restore checks identity while preserving disabled/retired state.
        catalog = [{**node,'enabled':True,'retired':False} for node in tables['node_catalog']]
        for group in groups:
            if group.get('members_format') == 'typed-v2':
                names = node_refs.resolve_refs(node_refs.decoded(group.get('members_v2'),[]),
                    variant_id=group['variant_id'],groups=groups,nodes=catalog)
                if json.loads(group['proxies']) != names:
                    raise ValueError('backup_invalid_reference')
                group['proxies'] = json.dumps(names,ensure_ascii=False)
                group['local_nodes'] = '[]'
        for rule in tables['rules']:
            ref = node_refs.decoded(rule.get('target_ref_v2'),None)
            if ref is not None:
                name = node_refs.resolve_refs([ref],variant_id=rule['variant_id'],groups=groups,nodes=catalog)[0]
                if rule['target'] != name:
                    raise ValueError('backup_invalid_reference')
                rule['target'] = name
    except (ValueError,TypeError,KeyError):
        raise ValueError('backup_invalid_reference') from None
    state = tables['catalog_state']
    revisions = {(row['node_uid'], row['revision']) for row in tables['node_revisions']}
    if (len(state) != 1 or state[0]['id'] != 1 or state[0]['revision'] < 0 or
            any((row['node_uid'], row['current_revision']) not in revisions
                for row in tables['node_catalog'])):
        raise ValueError('backup_invalid_reference')
    variants = {row["id"] for row in tables["variants"]}
    default = [row for row in tables["variants"] if row["id"] == 0]
    if len(default) != 1 or default[0]["name"] != "默认" or default[0]["is_system"] != 1:
        raise ValueError("backup_invalid_reference")
    targets = {row["name"] for row in tables["targets"]}
    devices = {row["name"] for row in tables["devices"]}
    sources = {row["name"] for row in tables["sources"]}
    nodes = {row["id"] for row in tables["local_nodes"]}
    providers = {row["name"] for row in tables["rule_providers"]}
    group_keys = {(row["variant_id"], row["name"]) for row in tables["proxy_groups"]}
    local_names = set(local_nodes.display_index(tables["local_nodes"], enabled_only=False))
    source_names = {node["emit_name"] for node in tables["node_catalog"] if node["origin_kind"] == "source"}
    for source in tables["sources"]:
        for node in _list(source, "nodes_meta"):
            if not isinstance(node, dict) or not isinstance(node.get("name"), str):
                raise ValueError("backup_invalid_reference")
            source_names.add(node["name"] + source["suffix"])
    for table in ("proxy_groups", "rules"):
        for row in tables[table]:
            if row["variant_id"] not in variants:
                raise ValueError("backup_invalid_reference")
            for field, names in (("targets", targets), ("devices", devices)):
                if any(not isinstance(value, str) or value not in names | {config.ALL_SCOPE}
                       for value in _list(row, field)):
                    raise ValueError("backup_invalid_reference")
    graph = {}
    for group in tables["proxy_groups"]:
        if any(type(value) is not int or value not in nodes for value in _list(group, "local_nodes")):
            raise ValueError("backup_invalid_reference")
        if any(not isinstance(value, str) or value not in sources | {config.ALL_SCOPE}
               for value in _list(group, "use_sources")):
            raise ValueError("backup_invalid_reference")
        key = (group["variant_id"], group["name"])
        graph[key] = []
        for member in _list(group, "proxies"):
            if not isinstance(member, str):
                raise ValueError("backup_invalid_reference")
            ref = (group["variant_id"], member)
            if ref in group_keys:
                graph[key].append(ref)
            elif member not in config.BUILTIN_TARGETS | local_names | source_names | {config.GUARD_PROXY}:
                raise ValueError("backup_invalid_reference")
    pending, visited = set(), set()

    def visit(key):
        if key in pending:
            raise ValueError("backup_invalid_reference")
        if key in visited:
            return
        pending.add(key)
        for member in graph[key]:
            visit(member)
        pending.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
    for rule in tables["rules"]:
        if rule["target"] not in config.BUILTIN_TARGETS and (rule["variant_id"], rule["target"]) not in group_keys:
            raise ValueError("backup_invalid_reference")
        if rule["type"] == "RULE-SET" and rule["value"] not in providers:
            raise ValueError("backup_invalid_reference")
    target_by_id = {row["id"]: row for row in tables["targets"]}
    device_by_id = {row["id"]: row for row in tables["devices"]}
    scopes = [(row["engine"], row["platform"]) for row in tables["targets"]]
    if len(scopes) != len(set(scopes)):
        raise ValueError("backup_invalid_reference")
    for row in tables["base_configs"]:
        if row["engine"] not in config.ENGINE_LABELS:
            raise ValueError("backup_invalid_reference")
        if row["device_id"]:
            device = device_by_id.get(row["device_id"])
            target = target_by_id.get(device["target_id"]) if device else None
            if not target or (row["engine"], row["platform"]) != (target["engine"], target["platform"]):
                raise ValueError("backup_invalid_reference")
        elif row["platform"] and row["platform"] not in config.PLATFORM_LABELS:
            raise ValueError("backup_invalid_reference")


def _validated(conn, payload: dict) -> tuple[dict, bool]:
    tables, legacy = _normalize(conn, payload)
    try:
        with _staging_schema(conn) as stage:
            _insert(stage, tables)
            if stage.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("backup_invalid_reference")
            # 使用 SQLite 应用缺省值后的行完成逻辑校验，不在 Python 猜测缺省值。
            tables = {table: _rows(stage, table) for table in backup_tables.BACKUP_TABLES}
            _validate_references(tables)
    except sqlite3.IntegrityError as exc:
        code = "backup_invalid_reference" if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY else "backup_invalid"
        raise ValueError(code) from None
    except (sqlite3.Error, OverflowError, TypeError, KeyError, RecursionError):
        raise ValueError("backup_invalid") from None
    _validate_files(conn, payload, tables, legacy=legacy)
    return tables, legacy


def _report(tables: dict, legacy: bool) -> dict:
    return {"legacy_import": legacy, "tables": len(tables),
            "rows": sum(len(rows) for rows in tables.values())}


def validate_logical(conn, payload: dict) -> dict:
    """在一致性读事务内验证 staging，不写当前数据库。"""
    _require_transaction(conn)
    tables, legacy = _validated(conn, payload)
    return _report(tables, legacy)


def restore_logical(conn, payload: dict, *, _backfill_catalog: bool = True) -> dict:
    """调用方须持有写事务；校验全部通过后才清空，事务由调用方提交。"""
    _require_transaction(conn)
    tables, legacy = _validated(conn, payload)
    conn.execute("SAVEPOINT logical_restore")
    try:
        for table in reversed(backup_tables.reset_tables(conn)):
            conn.execute(f"DELETE FROM {_quote(table)}")
        for table in reversed(backup_tables.BACKUP_TABLES):
            conn.execute(f"DELETE FROM {_quote(table)}")
        _insert(conn, tables)
        from .backup_archive import sanitize_restored
        sanitize_restored(conn)
        if legacy and _backfill_catalog:
            from . import node_catalog
            node_catalog.backfill(conn)
        from . import node_refs
        node_refs.migrate_refs(conn)
    except Exception:
        conn.execute("ROLLBACK TO logical_restore")
        conn.execute("RELEASE logical_restore")
        raise
    conn.execute("RELEASE logical_restore")
    return _report(tables, legacy)


def restore_legacy_database(conn, source) -> dict:
    """历史物理库只读转 v1 输入，复用 staging 校验与事务替换。"""
    _require_transaction(conn)
    _require_transaction(source)
    if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("backup_invalid")
    actual = {row[0] for row in source.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    known = (set(backup_tables.BACKUP_TABLES) | set(backup_tables.PRESERVED_TABLES) |
             set(backup_tables.RESET_TABLES))
    if actual - known:
        raise ValueError("backup_schema_unregistered")
    for table in set(backup_tables.BACKUP_TABLES) & actual:
        columns = _columns(conn, table)
        allowed = {row["name"] for row in columns}
        required = {row["name"] for row in columns if row["pk"] or (
            row["notnull"] and row["dflt_value"] is None)}
        present = {row["name"] for row in _columns(source, table)}
        if present - allowed or required - present:
            raise ValueError("backup_invalid")
    tables = {table: _rows(source, table) for table in backup_tables.BACKUP_TABLES if table in actual}
    for table, column in backup_tables.BLOB_COLUMNS:
        for row in tables.get(table, []):
            value = row[column]
            if not isinstance(value, bytes):
                raise ValueError("backup_invalid")
            row[column] = {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    payload = {"version": 1, "exported_at": db.now(), "tables": tables}
    return restore_logical(conn, payload, _backfill_catalog=False)


def create_archive(conn, destination: Path, include_runtime: bool = False) -> dict:
    from .backup_archive import create_archive as create
    return create(conn, destination, include_runtime=include_runtime)


def restore_archive(archive: Path, destination: Path, *, key_path: Path) -> dict:
    from .backup_archive import restore_archive as restore
    return restore(archive, destination, key_path=key_path)
