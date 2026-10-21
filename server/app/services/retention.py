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
    """必须保留产物目录的构建：当前生效版本 + 最近 N 个构建。

    生效版本（生产中 / 测试中）永远保留；已下线版本在留存窗口内保留，
    超出窗口的产物会被清理——回滚到这类构建会被明确拒绝。
    """
    keep: set[int] = set()
    for row in db.all_(
            conn, "SELECT id FROM builds "
                 "WHERE status IN ('PRODUCTION','TESTING')"):
        keep.add(int(row["id"]))
    for row in db.all_(
            conn, "SELECT id FROM builds ORDER BY id DESC LIMIT ?",
            (config.BUILD_ARTIFACT_KEEP,)):
        keep.add(int(row["id"]))
    return keep


def prune_build_artifacts(conn) -> int:
    """删除不再需要的构建产物目录，并回收对应的构建记录。

    留存策略按状态机区分：
    * 生产中 / 测试中：永不清理；
    * 已下线（曾发布过）：保留归档行，但清空快照——快照里含节点凭据密文，
      不应长期留档；产物清理后回滚会被明确拒绝；
    * 已构建（从未发布过）：超出窗口直接删除，连同其发布历史。
    """
    keep = _kept_build_ids(conn)
    removed = 0
    if config.BUILDS_DIR.exists():
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
    # 数据库里的旧构建记录同样回收（保留最近 N 条 + 当前生效版本）。
    # releases.build_id 有外键，必须先删对应的发布历史，
    # 否则删除构建记录会触发外键约束失败，整轮清理回滚。
    old_ids = [int(r["id"]) for r in db.all_(
        conn, "SELECT id FROM builds ORDER BY id DESC LIMIT -1 OFFSET ?",
        (config.BUILD_ARTIFACT_KEEP,))]
    if old_ids:
        marks = ",".join("?" for _ in old_ids)
        conn.execute(
            f"DELETE FROM releases WHERE build_id IN ({marks})", old_ids)
        # 从未发布过的构建：整行删除
        conn.execute(
            f"DELETE FROM builds WHERE id IN ({marks}) AND status='BUILT'", old_ids)
        # 已发布过的构建：保留归档行，只清空含凭据的快照
        conn.execute(
            f"UPDATE builds SET snapshot='' "
            f"WHERE id IN ({marks}) AND status<>'BUILT'", old_ids)
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


def run_once() -> dict:
    """执行一轮清理，返回各项目删除数量。"""
    with db.tx() as conn:
        stale = mark_stale_builds_failed(conn)
        artifacts = prune_build_artifacts(conn)
        audits = prune_audit_log(conn)
        sessions = prune_sessions(conn)
    if artifacts or audits or sessions or stale:
        logger.info("留存清理：构建产物 %s，审计 %s，会话 %s，僵尸构建 %s",
                    artifacts, audits, sessions, stale)
    return {"artifacts": artifacts, "audit": audits, "sessions": sessions,
            "stale_builds": stale}
