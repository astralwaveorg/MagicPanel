"""磁盘与数据留存：构建产物、审计日志、过期会话。

面板长期运行在 NAS 上，构建产物与审计日志会随时间单调增长；
没有上限时磁盘会被慢慢写满，最终导致构建与订阅一起失败。
这里集中做"可回收数据的清理"，只删可再生的数据，不碰配置与产物当前版本。
"""
import logging
import shutil

from .. import config, db

logger = logging.getLogger("magicpanel.retention")


def _kept_build_ids(conn) -> set[int]:
    """必须保留的构建。

    * 当前生效版本（生产中 / 测试中）：永远保留；
    * 曾发布过的构建：保留最近 N 个（PUBLISHED_BUILD_KEEP），更早的彻底清理；
    * 从未发布过的构建：保留最近 M 个（BUILD_ARTIFACT_KEEP）。
    """
    keep: set[int] = set()
    for row in db.all_(
            conn, "SELECT id FROM builds "
                 "WHERE status IN ('PRODUCTION','TESTING')"):
        keep.add(int(row["id"]))
    # 曾发布过的构建：status 不再是 BUILT，或发布历史里有它
    for row in db.all_(
            conn, "SELECT id FROM builds WHERE status<>'BUILT' OR id IN "
                 "(SELECT build_id FROM releases) ORDER BY id DESC LIMIT ?",
            (config.PUBLISHED_BUILD_KEEP,)):
        keep.add(int(row["id"]))
    # 从未发布过的构建
    for row in db.all_(
            conn, "SELECT id FROM builds WHERE status='BUILT' "
                 "ORDER BY id DESC LIMIT ?", (config.BUILD_ARTIFACT_KEEP,)):
        keep.add(int(row["id"]))
    return keep


def prune_build_artifacts(conn) -> tuple[int, list[int]]:
    """回收不再需要的构建：数据库记录在事务内删，磁盘目录在事务外删。

    留存策略按状态机区分：
    * 生产中 / 测试中：永不清理；
    * 曾发布过（已下线）：保留最近 PUBLISHED_BUILD_KEEP 个，更早的**彻底清理**；
    * 从未发布过：保留最近 BUILD_ARTIFACT_KEEP 个，超出的直接删除。

    返回 (keep 集合, 事务内已删除记录的构建 id 列表)。

    磁盘删除必须放在事务之外（run_once 负责）：rmtree 不可回滚——
    原来放在事务里，DB 删除一旦失败回滚，就留下"行在文件不在"的
    不一致，备份完整性校验从此永远 backup_missing_resource
    （2026-11-18 线上实证：#190/#273/#274/#276-#282 九个构建）。
    """
    keep = _kept_build_ids(conn)
    purge = [int(r["id"]) for r in db.all_(conn, "SELECT id FROM builds ORDER BY id")
             if int(r["id"]) not in keep]
    if purge:
        marks = ",".join("?" for _ in purge)
        # releases.build_id 有外键，必须先删对应的发布历史
        conn.execute(f"DELETE FROM releases WHERE build_id IN ({marks})", purge)
        conn.execute(f"DELETE FROM builds WHERE id IN ({marks})", purge)
    return keep, purge


def purge_build_dirs(keep: set[int], purged_ids: list[int]) -> int:
    """删除留存窗口外的构建产物目录（调用方在 DB 事务提交之后调用）。

    目录删除失败只告警：目录残留不影响数据库一致性，下一轮会重试。
    """
    removed = 0
    if not config.BUILDS_DIR.exists():
        return 0
    for path in config.BUILDS_DIR.iterdir():
        if not path.is_dir() or not path.name.isdigit():
            continue
        if int(path.name) in keep:
            continue
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            logger.warning("删除构建产物目录失败 %s：%s", path, exc)
    return removed


def prune_audit_log(conn) -> int:
    """审计日志只保留最近 N 行（更早的可在归档文件里查）。"""
    cur = conn.execute(
        "DELETE FROM audit WHERE id NOT IN "
        "(SELECT id FROM audit ORDER BY id DESC LIMIT ?)",
        (config.AUDIT_LOG_KEEP,),
    )
    return cur.rowcount or 0


def prune_sessions(conn) -> int:
    """清理过期会话。"""
    cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))
    return cur.rowcount or 0


def mark_stale_builds_failed(conn) -> int:
    """把卡在 building 的构建标记为失败。

    进程在渲染途中被 kill 时，校验状态会永远停在 building，
    界面上出现一条既不能发布、也看不出原因的僵尸记录。
    """
    cur = conn.execute(
        "UPDATE builds SET verify_status='failed' WHERE verify_status='building' "
        "AND created_at < ?", (db.now_offset_hours(-2),))
    return cur.rowcount or 0


def prune_probe_tables(conn) -> int:
    """清理 probe 三张表：入队任务（2026-11-18 起 active 才产出）历史行
    与结果行此前永不清理，单调膨胀。保留最近 200 条任务及其明细。"""
    tables = {r["name"] for r in db.all_(conn,
                "SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"probe_jobs", "probe_items", "probe_results"} <= tables:
        return 0     # 探测迁移未跑：没有表就没有东西要清
    keep_ids = [r["id"] for r in db.all_(
        conn, "SELECT id FROM probe_jobs ORDER BY created_at DESC, id DESC LIMIT 200")]
    removed = 0
    if keep_ids:
        marks = ",".join("?" for _ in keep_ids)
        item_ids = [r["id"] for r in db.all_(
            conn, f"SELECT id FROM probe_items WHERE job_id NOT IN ({marks})", keep_ids)]
        if item_ids:
            marks_i = ",".join("?" for _ in item_ids)
            removed += conn.execute(
                f"DELETE FROM probe_results WHERE item_id IN ({marks_i})", item_ids).rowcount or 0
            removed += conn.execute(
                f"DELETE FROM probe_items WHERE id IN ({marks_i})", item_ids).rowcount or 0
        removed += conn.execute(
            f"DELETE FROM probe_jobs WHERE id NOT IN ({marks})", keep_ids).rowcount or 0
    else:
        removed += conn.execute("DELETE FROM probe_results").rowcount or 0
        removed += conn.execute("DELETE FROM probe_items").rowcount or 0
        removed += conn.execute("DELETE FROM probe_jobs").rowcount or 0
    return removed


def prune_resource_revisions(conn) -> int:
    """非当前引用的资源版本 BLOB 只保留最近 10 个（2026-11-18）。

    被引用的行永远保留：resource_latest / build_resources 有 FK 指向
    resource_revisions，删掉当前指针指向的行会让留存清理整个事务回滚。
    """
    # 表可能还不存在（v2 探测迁移未跑或旧库）：跳过而不是让整轮清理失败
    tables = {r["name"] for r in db.all_(conn,
                "SELECT name FROM sqlite_master WHERE type='table'")}
    if "resource_revisions" not in tables:
        return 0
    total = db.one(conn, "SELECT COUNT(*) c FROM resource_revisions")["c"]
    if total <= 10:
        return 0
    keep = [r["id"] for r in db.all_(
        conn, "SELECT id FROM resource_revisions ORDER BY created_at DESC, id LIMIT 10")]
    # 引用表 FK 指向 resource_revisions(id)：被引用的行永远保留
    if {"resource_latest", "build_resources"} <= tables:
        for r in db.all_(conn,
                         "SELECT DISTINCT resource_id AS rid FROM resource_latest "
                         "UNION SELECT DISTINCT resource_id AS rid FROM build_resources"):
            if r["rid"] and r["rid"] not in keep:
                keep.append(r["rid"])
    marks = ",".join("?" for _ in keep)
    cur = conn.execute(
        f"DELETE FROM resource_revisions WHERE id NOT IN ({marks})", keep)
    return cur.rowcount or 0


def prune_probe_tmp_dirs(data_dir) -> int:
    """测速/校验临时目录（进程被杀时残留，finally 兜不住 SIGKILL）。

    只清 1 小时以上的残留：手动测速/构建可能正写到这些目录，
    并发删除会让运行中的任务神秘失败（2026-11-18 红队修复）。
    """
    import shutil
    import time as _time
    removed = 0
    cutoff = _time.time() - 3600
    for pattern in ("mihomo-test-*", "mp-validate-*"):
        for path in data_dir.glob(pattern):
            try:
                if path.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def run_once() -> dict:
    """执行一轮清理，返回各项目删除数量。"""
    from .. import config as _config
    with db.tx() as conn:
        stale = mark_stale_builds_failed(conn)
        keep, purged_ids = prune_build_artifacts(conn)
        audits = prune_audit_log(conn)
        sessions = prune_sessions(conn)
        probe = prune_probe_tables(conn)
        revisions = prune_resource_revisions(conn)
    # 磁盘目录清理在事务外：rmtree 不可回滚，DB 失败不能丢文件
    build_dirs = purge_build_dirs(keep, purged_ids)
    tmp_dirs = prune_probe_tmp_dirs(_config.DATA_DIR)
    if (build_dirs or audits or sessions or stale or purged_ids
            or probe or revisions or tmp_dirs):
        logger.info("留存清理：构建目录 %s，构建记录 %s，审计 %s，会话 %s，僵尸构建 %s，"
                    "probe %s，资源版本 %s，临时目录 %s",
                    build_dirs, len(purged_ids), audits, sessions, stale,
                    probe, revisions, tmp_dirs)
    return {"build_dirs": build_dirs, "builds": len(purged_ids), "audit": audits,
            "sessions": sessions, "stale_builds": stale,
            "probe": probe, "resource_revisions": revisions, "tmp_dirs": tmp_dirs}
