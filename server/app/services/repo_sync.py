"""仓库同步：把仓库里的 rule/*.yaml 同步成规则来源的内容。

业务判断都在这里，Git 动作在 repo_manager。
仓库里除 rule/ 之外的目录是素材区：面板只管理文件，不消费。
"""
import re

import yaml

from .. import db, security
from . import repo_manager


class SyncError(Exception):
    """同步过程中的可读错误。"""


def rule_name_of(path: str) -> str:
    """rule/<name>.yaml → <name>（文件名去扩展名即引用键）。"""
    return path.rsplit("/", 1)[-1][:-len(".yaml")]


def header_meta(text: str) -> dict:
    """文件头注释里的名称 / behavior / 条目 / 说明。"""
    out: dict = {}
    for line in text.splitlines()[:20]:
        m = re.match(r"^#\s*([^:：]+)\s*[:：]\s*(.+)$", line.strip())
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        low = key.lower()
        if low in ("名称", "name"):
            out["name"] = val
        elif low == "behavior":
            out["behavior"] = val.lower()
        elif low in ("条目", "count"):
            out["count"] = val
        elif low in ("说明", "description"):
            out["desc"] = val
    return out


def validate_rule_file(text: str, path: str) -> dict:
    """校验仓库里的规则集合文件，返回解析出的元信息。"""
    meta = header_meta(text)
    behavior = meta.get("behavior", "domain")
    if behavior not in ("domain", "ipcidr", "classical"):
        raise SyncError(f"{path}：behavior 仅支持 domain / ipcidr / classical")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SyncError(f"{path}：内容不是合法 YAML：{exc}") from exc
    if not isinstance(data, dict) or "payload" not in data:
        raise SyncError(f"{path}：规则集合文件必须有 payload 列表")
    payload = data.get("payload")
    if not isinstance(payload, list) or not payload:
        raise SyncError(f"{path}：payload 必须是非空列表")
    return {"behavior": behavior, "count": len(payload), "desc": meta.get("desc", "")}


def sync_content(conn, operator: str) -> dict:
    """把仓库里的 rule/*.yaml 同步进规则来源。

    - 来源不存在就新建（kind='repo'），可用设置关掉
    - 内容以仓库为准，覆盖面板侧的快照
    - 面板侧的启用状态不被仓库覆盖
    """
    cfg = repo_manager.get_settings(conn)
    if not repo_manager.is_cloned():
        raise SyncError("仓库还没有克隆")
    patterns = cfg["exclude_paths"].split(",") if cfg["exclude_paths"] else []
    patterns = [p.strip() for p in patterns if p.strip()]
    files = repo_manager.list_files(conn)
    created = updated = 0
    errors: list[str] = []
    for item in files:
        rel = item["path"]
        if not rel.startswith("rule/") or not rel.endswith(".yaml"):
            continue
        try:
            target = repo_manager.safe_path(conn, rel)
            text = target.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"{rel}：{exc}")
            continue
        try:
            meta = validate_rule_file(text, rel)
        except SyncError as exc:
            errors.append(str(exc))
            continue
        name = rule_name_of(rel)
        row = db.one(conn, "SELECT * FROM rule_providers WHERE name=?", (name,))
        now = db.now()
        if row is None:
            if not cfg["auto_create_rule_sources"]:
                continue
            cur = conn.execute(
                "INSERT INTO rule_providers(name, behavior, format, kind, url, "
                "repo_path, inline_content, interval, client_interval, enabled, "
                "content, rule_count, sha256, last_status, last_fetched_at, "
                "created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, meta["behavior"], "yaml", "repo", "", rel, "",
                 86400, 0, 1, text, meta["count"], _sha(text), "ok", now, now, now),
            )
            security.audit(conn, operator, "从仓库创建规则来源", "rule_provider",
                           cur.lastrowid, {"name": name, "repo_path": rel})
            created += 1
            continue
        if row["content"] == text and row["repo_path"] == rel:
            continue
        conn.execute(
            "UPDATE rule_providers SET repo_path=?, behavior=?, content=?, "
            "rule_count=?, sha256=?, last_status='ok', last_fetched_at=?, "
            "updated_at=? WHERE id=?",
            (rel, meta["behavior"], text, meta["count"], _sha(text), now, now, row["id"]),
        )
        updated += 1
    return {"created": created, "updated": updated, "errors": errors}


def sync_one(conn, name: str, operator: str) -> dict:
    """从仓库同步单个规则集合（只更新这一个文件的内容，不做 Git 操作）。"""
    row = db.one(conn, "SELECT * FROM rule_providers WHERE name=?", (name,))
    if not row:
        raise SyncError("规则来源不存在")
    rel = row["repo_path"] if "repo_path" in row.keys() else ""
    if not rel:
        raise SyncError("这条规则来源没有绑定仓库文件")
    target = repo_manager.safe_path(conn, rel)
    if not target.exists():
        raise SyncError(f"仓库里没有 {rel}")
    content = target.read_text(encoding="utf-8")
    meta = validate_rule_file(content, rel)
    now = db.now()
    conn.execute(
        "UPDATE rule_providers SET content=?, sha256=?, rule_count=?, behavior=?, "
        "last_status='ok', last_fetched_at=?, updated_at=? WHERE id=?",
        (content, security.sha256_text(content), meta["count"], meta["behavior"],
         now, now, row["id"]),
    )
    security.audit(conn, operator, "从仓库同步规则来源", "rule_provider",
                   row["id"], {"name": name, "repo_path": rel})
    return db.one(conn, "SELECT * FROM rule_providers WHERE id=?", (row["id"],))


def _sha(text: str) -> str:
    return security.sha256_text(text)


def run_sync(conn, operator: str, automatic: bool = False) -> dict:
    """一轮完整同步：拉取 → 同步内容 → 记录状态。

    定时任务只 pull 不 push（D7）；冲突时停在冲突态，不推。
    """
    summary = {"pulled": False, "created": 0, "updated": 0,
               "errors": [], "conflicts": [], "pushed": False}
    try:
        repo_manager.pull(conn)
        summary["pulled"] = True
        conflicts = repo_manager.conflicted_files(conn)
        if conflicts:
            summary["conflicts"] = conflicts
            summary["errors"].append(f"存在 {len(conflicts)} 个冲突文件，需要手工解决")
            _record(conn, summary)
            return summary
        result = sync_content(conn, operator)
        summary["created"] = result["created"]
        summary["updated"] = result["updated"]
        summary["errors"].extend(result["errors"])
        cfg = repo_manager.get_settings(conn)
        if cfg["auto_push"] and repo_manager.dirty_files(conn):
            repo_manager.commit_all(conn, "面板自动提交：同步仓库内容")
            repo_manager.push(conn)
            summary["pushed"] = True
        _record(conn, summary)
    except Exception as exc:
        summary["errors"].append(str(exc))
        _record(conn, summary, error=str(exc))
        raise
    return summary


def _record(conn, summary: dict, error: str = "") -> None:
    db.set_setting(conn, "deps_last_sync_at", db.now())
    db.set_setting(conn, "deps_last_error", error)
    db.set_setting(conn, "deps_last_commit", repo_manager.head_commit(conn))
