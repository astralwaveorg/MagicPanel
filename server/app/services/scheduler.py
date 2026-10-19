"""服务端定时任务：抓取上游、节点测速与自动构建发布。

单进程后台任务，随 FastAPI lifespan 启动/停止。每个 tick 读取设置与各来源的
interval，只处理到期的项目；失败后把 last_attempt_at 推进到当前时间，避免每个
tick 重复请求上游。
"""
import asyncio
import json
import logging
import threading
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from .. import config, db, security
from ..routers import builds
from . import tester, updater

logger = logging.getLogger("magicpanel.scheduler")
AUTO_OPERATOR = "系统"

_state: dict = {
    "running": False,
    "last_tick_at": "",
    "last_result": None,
    "last_error": "",
}
_lock = threading.Lock()
_core_cache: dict = {"at": 0.0, "available": False, "status": None}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _due(last_attempt: str | None, interval_seconds: int, now: datetime) -> bool:
    last = _parse_time(last_attempt)
    if last is None:
        return True
    return last + timedelta(seconds=max(0, interval_seconds)) <= now


def _setting(conn, key: str, default: str = "") -> str:
    return db.get_setting(conn, key, default)


def _enabled(conn, key: str, default: str = "0") -> bool:
    return _setting(conn, key, default) == "1"


def _core_available() -> bool:
    """缓存核心状态，避免每个 tick 都执行 mihomo -v。"""
    import time
    now = time.monotonic()
    if now - _core_cache["at"] < 300:
        return bool(_core_cache["available"])
    status = tester.core_status()
    _core_cache.update(at=now, available=bool(status.get("available")),
                       status=status)
    return bool(status.get("available"))


def _run_source_fetch(summary: dict, now: datetime, force: bool = False) -> None:
    with db.connect() as conn:
        rows = db.all_(
            conn,
            "SELECT id, name, interval, last_attempt_at, last_fetched_at, "
            "created_at FROM sources WHERE enabled=1 AND auto_fetch=1 ORDER BY id",
        )
    for row in rows:
        last = row["last_attempt_at"] or row["last_fetched_at"]
        if not force and last and not _due(last, row["interval"], now):
            continue
        try:
            updater.refresh_source(row["id"], AUTO_OPERATOR, automatic=True)
            summary["sources_fetched"] += 1
        except Exception as exc:  # 单个来源失败不影响其他项目
            summary["sources_failed"] += 1
            summary["errors"].append(f"节点来源 {row['name']}：{exc}")
            logger.warning("自动抓取节点来源失败：%s：%s", row["name"], exc)


def _run_source_test(summary: dict, now: datetime, force: bool = False) -> None:
    with db.connect() as conn:
        rows = db.all_(
            conn,
            "SELECT id, name, test_interval, test_attempt_at, tested_at, created_at, "
            "snapshot_enc FROM sources WHERE enabled=1 AND test_interval>0 "
            "AND auto_test=1 AND snapshot_enc IS NOT NULL ORDER BY id",
        )
    due = []
    for row in rows:
        last = row["test_attempt_at"] or row["tested_at"]
        if force or not last or _due(last, row["test_interval"], now):
            due.append(row)
    if not due:
        return
    if not _core_available():
        summary["test_skipped"] = "测速核心未安装"
        return
    for row in due:
        try:
            outcome = updater.test_source(row["id"], AUTO_OPERATOR, automatic=True)
            results = outcome["test_results"]
            if isinstance(results, str):
                try:
                    results = json.loads(results or "{}")
                except ValueError:
                    results = {}
            if not isinstance(results, dict):
                results = {}
            summary["tests_run"] += 1
            summary["tests_ok"] += sum(1 for v in results.values() if v >= 0)
            summary["tests_failed"] += sum(1 for v in results.values() if v < 0)
        except Exception as exc:
            summary["tests_errors"] += 1
            summary["errors"].append(f"节点来源测速 {row['name']}：{exc}")
            logger.warning("自动测速失败：%s：%s", row["name"], exc)


def _run_rule_fetch(summary: dict, now: datetime, force: bool = False) -> None:
    with db.connect() as conn:
        rows = db.all_(
            conn,
            "SELECT id, name, interval, last_attempt_at, last_fetched_at, created_at "
            "FROM rule_providers WHERE enabled=1 AND kind='remote' ORDER BY id",
        )
    for row in rows:
        last = row["last_attempt_at"] or row["last_fetched_at"]
        if not force and last and not _due(last, row["interval"], now):
            continue
        try:
            updater.refresh_provider(row["id"], AUTO_OPERATOR, automatic=True)
            summary["rules_fetched"] += 1
        except Exception as exc:
            summary["rules_failed"] += 1
            summary["errors"].append(f"规则来源 {row['name']}：{exc}")
            logger.warning("自动抓取规则来源失败：%s：%s", row["name"], exc)


def _publish_tests_ready(conn) -> tuple[bool, list[str]]:
    """自动发布前检查：启用“只分发可用节点”的来源必须有新鲜且可用的测速结果。"""
    rows = db.all_(
        conn,
        "SELECT name, test_results, tested_at, last_fetched_at FROM sources "
        "WHERE enabled=1 AND filter_unavailable=1 ORDER BY id",
    )
    missing: list[str] = []
    for row in rows:
        try:
            results = json.loads(row["test_results"] or "{}")
        except ValueError:
            results = {}
        if not isinstance(results, dict) or not results:
            missing.append(f"{row['name']}（无测速结果）")
            continue
        if not any(value >= 0 for value in results.values()):
            missing.append(f"{row['name']}（全部节点测速失败）")
            continue
        tested = _parse_time(row["tested_at"])
        fetched = _parse_time(row["last_fetched_at"])
        if not tested:
            missing.append(f"{row['name']}（无测速结果）")
        elif fetched and tested < fetched:
            missing.append(f"{row['name']}（测速早于最近抓取）")
    return not missing, missing


def _run_auto_build(summary: dict, now: datetime, force: bool = False) -> None:
    with db.tx() as conn:
        if not _enabled(conn, "auto_build_enabled", "1"):
            return
        try:
            interval_hours = max(1, int(_setting(conn, "auto_build_interval_hours", "12")))
        except ValueError:
            interval_hours = 12
        last_attempt = _setting(conn, "auto_build_last_attempt", "")
        if not force and not _due(last_attempt, interval_hours * 3600, now):
            return
        latest = db.one(
            conn, "SELECT * FROM builds WHERE status='success' ORDER BY id DESC LIMIT 1")

        try:
            snapshot, policy_sha = builds.current_policy(conn)
        except Exception as exc:
            summary["build_error"] = f"读取策略失败：{exc}"
            return
        if not snapshot["targets"]:
            # 没有发布目标时不推进检查时间，添加目标后可尽快自动构建
            summary["build_error"] = "尚未配置任何发布目标"
            return
        if latest and latest["policy_sha"] == policy_sha:
            db.set_setting(conn, "auto_build_last_attempt", db.now())
            summary["build"] = "策略未变化，跳过"
            return
        publish = _enabled(conn, "auto_publish_enabled", "1")
        if publish:
            ready, missing = _publish_tests_ready(conn)
            if not ready:
                # 不推进自动构建时间：测速完成后下一轮立即重试
                summary["build_error"] = (
                    "自动发布等待测速结果：" + "、".join(missing)
                )
                return
        db.set_setting(conn, "auto_build_last_attempt", db.now())
        try:
            build_id, status = builds.create_candidate(
                conn, AUTO_OPERATOR, note="自动构建", snapshot=snapshot,
                policy_sha=policy_sha,
            )
        except builds.BuildError as exc:
            summary["build_error"] = str(exc)
            return
        except Exception as exc:
            summary["build_error"] = f"自动构建失败：{exc}"
            logger.exception("自动构建失败")
            return
        summary["build"] = {"id": build_id, "status": status}
        if status != "success":
            return
        if not publish:
            return
        channel = _setting(conn, "auto_publish_channel", "stable")
        if channel not in ("stable", "candidate"):
            channel = "stable"
        build = builds._get_build(conn, build_id)
        try:
            builds.promote_internal(
                conn, build, channel, "promote", AUTO_OPERATOR, "自动构建发布",
            )
        except Exception as exc:
            summary["build_error"] = f"自动发布失败：{exc}"
            logger.exception("自动发布失败")
            return
        summary["published"] = channel


def _has_activity(summary: dict) -> bool:
    keys = ("sources_fetched", "sources_failed", "rules_fetched", "rules_failed",
            "tests_run", "tests_errors", "build", "published")
    return any(summary.get(key) for key in keys) or bool(summary.get("errors"))


def _record_run(summary: dict, trigger: str, actor: str) -> None:
    """手动运行必记；定时运行只在有实际动作时记，避免每 30 秒写一条。"""
    if trigger != "manual" and not _has_activity(summary):
        return
    detail = {
        "trigger": trigger,
        "sources_fetched": summary["sources_fetched"],
        "sources_failed": summary["sources_failed"],
        "rules_fetched": summary["rules_fetched"],
        "rules_failed": summary["rules_failed"],
        "tests_run": summary["tests_run"],
        "tests_ok": summary["tests_ok"],
        "tests_failed": summary["tests_failed"],
        "tests_errors": summary["tests_errors"],
        "build": summary.get("build"),
        "published": summary.get("published", ""),
        "skipped": summary.get("skipped", ""),
        "build_error": summary.get("build_error", ""),
        "errors": summary.get("errors", [])[:10],
    }
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO automation_runs(at, trigger, summary) VALUES(?,?,?)",
            (summary["finished_at"] or db.now(), trigger,
             json.dumps(summary, ensure_ascii=False)),
        )
        conn.execute(
            "DELETE FROM automation_runs WHERE id NOT IN "
            "(SELECT id FROM automation_runs ORDER BY id DESC LIMIT 50)"
        )
        security.audit(
            conn, actor,
            "手动自动任务运行完成" if trigger == "manual" else "定时任务执行",
            "automation", "", detail,
        )


def run_once(force: bool = False, trigger: str = "scheduled",
             actor: str = AUTO_OPERATOR) -> dict:
    """执行一轮检查；force=True 时忽略到期时间（用于“立即运行一次”）。"""
    if not _lock.acquire(blocking=False):
        return {"skipped": "上一轮任务仍在运行"}
    _state["running"] = True
    summary = {
        "started_at": db.now(),
        "finished_at": "",
        "trigger": trigger,
        "actor": actor,
        "sources_fetched": 0,
        "sources_failed": 0,
        "rules_fetched": 0,
        "rules_failed": 0,
        "tests_run": 0,
        "tests_ok": 0,
        "tests_failed": 0,
        "tests_errors": 0,
        "build": None,
        "published": "",
        "errors": [],
    }
    try:
        with db.connect() as conn:
            master = _setting(conn, "scheduler_enabled", "1") == "1"
            fetch_sources = _enabled(conn, "auto_fetch_sources", "1")
            fetch_rules = _enabled(conn, "auto_fetch_rules", "1")
            test_sources = _enabled(conn, "auto_test_sources", "1")
        if not master and not force:
            summary["skipped"] = "定时任务未启用"
        else:
            now = datetime.now(timezone.utc).astimezone()
            if fetch_sources:
                _run_source_fetch(summary, now, force=force)
            if fetch_rules:
                _run_rule_fetch(summary, now, force=force)
            if test_sources:
                _run_source_test(summary, now, force=force)
            _run_auto_build(summary, now, force=force)
        summary["finished_at"] = db.now()
        _state["last_tick_at"] = summary["finished_at"]
        _state["last_result"] = summary
        _state["last_error"] = ""
        logger.info(
            "定时任务完成：抓取节点 %s/%s，规则 %s/%s，测速 %s，构建 %s",
            summary["sources_fetched"], summary["sources_fetched"] + summary["sources_failed"],
            summary["rules_fetched"], summary["rules_fetched"] + summary["rules_failed"],
            summary["tests_run"], summary["build"],
        )
        _record_run(summary, trigger, actor)
        return summary
    except Exception as exc:
        _state["last_error"] = str(exc)
        logger.exception("定时任务异常")
        raise
    finally:
        _state["running"] = False
        _lock.release()


def run_once_safe(force: bool = False, trigger: str = "scheduled",
                  actor: str = AUTO_OPERATOR) -> dict | None:
    try:
        return run_once(force=force, trigger=trigger, actor=actor)
    except Exception:
        return None


def status() -> dict:
    with db.connect() as conn:
        settings = {
            key: _setting(conn, key, default)
            for key, default in (
                ("scheduler_enabled", "1"),
                ("auto_fetch_sources", "1"),
                ("auto_fetch_rules", "1"),
                ("auto_test_sources", "1"),
                ("auto_build_enabled", "1"),
                ("auto_build_interval_hours", "12"),
                ("auto_publish_enabled", "1"),
                ("auto_publish_channel", "stable"),
            )
        }
    return {
        "autostart": config.SCHEDULER_AUTOSTART,
        "tick_seconds": config.SCHEDULER_TICK_SECONDS,
        "running": _state["running"],
        "last_tick_at": _state["last_tick_at"],
        "last_result": _state["last_result"],
        "last_error": _state["last_error"],
        "settings": settings,
    }


def start_loop() -> asyncio.Task:
    async def loop():
        # 启动后稍等，避免和数据库初始化、首次请求争抢
        await asyncio.sleep(5)
        while True:
            try:
                await asyncio.to_thread(run_once)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("定时任务循环异常")
            await asyncio.sleep(config.SCHEDULER_TICK_SECONDS)

    logger.info("定时任务循环已启动（tick=%ss）", config.SCHEDULER_TICK_SECONDS)
    return asyncio.create_task(loop(), name="magicpanel-scheduler")


async def stop_loop(task: asyncio.Task) -> None:
    logger.info("定时任务循环已停止")
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
