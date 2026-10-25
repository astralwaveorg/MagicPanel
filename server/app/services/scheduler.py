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
from . import releases, repo_sync, retention, tester, updater

logger = logging.getLogger("magicpanel.scheduler")
AUTO_OPERATOR = "系统"

_state: dict = {
    "running": False,
    "last_tick_at": "",
    "last_result": None,
    "last_error": "",
    "last_notice": "",
}
_lock = threading.Lock()
_core_cache: dict = {"at": 0.0, "available": False, "status": None}
_last_retention: str = ""   # 最近一次留存清理的时间（ISO），一天最多一次


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


# 定时抓取失败后的重试次数与间隔（秒）
FETCH_RETRY_TIMES = 3
FETCH_RETRY_DELAY = 5


def _fetch_with_retry(fetch, label: str):
    """定时抓取失败时重试，最多 FETCH_RETRY_TIMES 次。

    抓取失败往往来自网络抖动（超时、对方临时限流），重试一次多半就好了；
    重试期间旧快照保持不变，客户端继续用上一份可用数据。
    最后一次仍失败就把错误抛给调用方，由调用方记入运行摘要。
    """
    import time
    last_exc = None
    for attempt in range(1, FETCH_RETRY_TIMES + 1):
        try:
            return fetch()
        except Exception as exc:
            last_exc = exc
            if attempt < FETCH_RETRY_TIMES:
                logger.warning("%s 失败（第 %d/%d 次）：%s，将重试",
                               label, attempt, FETCH_RETRY_TIMES, exc)
                time.sleep(FETCH_RETRY_DELAY)
    raise last_exc


def _run_source_fetch(summary: dict, now: datetime, force: bool = False) -> None:
    with db.connect() as conn:
        rows = db.all_(
            conn,
            "SELECT id, name, interval, last_attempt_at, last_fetched_at, "
            "created_at FROM sources WHERE enabled=1 AND auto_fetch=1 "
            "AND interval>0 ORDER BY id",
        )
    for row in rows:
        last = row["last_attempt_at"] or row["last_fetched_at"]
        if not force and last and not _due(last, row["interval"], now):
            continue
        try:
            _fetch_with_retry(
                lambda rid=row["id"]: updater.refresh_source(
                    rid, AUTO_OPERATOR, automatic=True),
                f"自动抓取节点来源 {row['name']}",
            )
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
            _fetch_with_retry(
                lambda rid=row["id"]: updater.refresh_provider(
                    rid, AUTO_OPERATOR, automatic=True),
                f"自动抓取规则来源 {row['name']}",
            )
            summary["rules_fetched"] += 1
        except Exception as exc:
            summary["rules_failed"] += 1
            summary["errors"].append(f"规则来源 {row['name']}：{exc}")
            logger.warning("自动抓取规则来源失败：%s：%s", row["name"], exc)


def _run_snippet_fetch(summary: dict, now: datetime, force: bool = False) -> None:
    """抓取远程拓展模块：与规则来源同构的到期判断与重试。"""
    with db.connect() as conn:
        rows = db.all_(
            conn,
            "SELECT id, name, interval, last_attempt_at, last_fetched_at, created_at "
            "FROM snippets WHERE enabled=1 AND source='remote' ORDER BY id",
        )
    for row in rows:
        last = row["last_attempt_at"] or row["last_fetched_at"]
        if not force and last and not _due(last, row["interval"], now):
            continue
        try:
            _fetch_with_retry(
                lambda sid=row["id"]: updater.refresh_snippet(
                    sid, AUTO_OPERATOR, automatic=True),
                f"自动抓取拓展模块 {row['name']}",
            )
            summary["snippets_fetched"] += 1
        except Exception as exc:
            summary["snippets_failed"] += 1
            summary["errors"].append(f"拓展模块 {row['name']}：{exc}")
            logger.warning("自动抓取拓展模块失败：%s：%s", row["name"], exc)


def _run_deps_sync(summary: dict, now: datetime, force: bool = False) -> None:
    """定时同步依赖仓库：到点拉取并把 rule/*.yaml 同步进规则来源。

    只 pull 不 push；冲突时停在冲突态等人工处理。
    """
    with db.connect() as conn:
        enabled = _setting(conn, "deps_enabled", "0") == "1"
        hours = int(_setting(conn, "deps_sync_hours", "12") or 12)
        last = _setting(conn, "deps_last_sync_at", "")
    if not enabled:
        return
    if not force and last and not _due(last, hours * 3600, now):
        return
    try:
        with db.tx() as conn:
            result = repo_sync.run_sync(conn, AUTO_OPERATOR, automatic=True)
        summary["deps_created"] += result["created"]
        summary["deps_updated"] += result["updated"]
        for message in result["errors"]:
            summary["errors"].append(f"依赖仓库：{message}")
    except Exception as exc:
        summary["deps_failed"] += 1
        summary["errors"].append(f"依赖仓库同步：{exc}")
        logger.warning("依赖仓库同步失败：%s", exc)


def _publish_tests_ready(conn) -> tuple[bool, list[str], list[str]]:
    """自动构建发布前检查：启用“只分发可用节点”的来源必须有新鲜且可用的测速结果。

    关闭了自动测速（auto_test=0）或测速间隔为 0 的来源不会产生测速结果，
    不参与门禁，否则会永久阻塞自动构建发布。
    """
    skipped = [
        r["name"] for r in db.all_(
            conn,
            "SELECT name FROM sources WHERE enabled=1 AND filter_unavailable=1 "
            "AND (auto_test=0 OR test_interval<=0) ORDER BY id",
        )
    ]

    rows = db.all_(
        conn,
        "SELECT name, test_results, tested_at, last_fetched_at FROM sources "
        "WHERE enabled=1 AND filter_unavailable=1 AND auto_test=1 "
        "AND test_interval>0 ORDER BY id",
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
    return not missing, missing, skipped


def _unchecked_core_targets(results: dict) -> list[str]:
    """找出"没做核心校验"的 Mihomo 目标。

    判据不能只看 core_checked 字段：历史构建的设备专属产物没有写这个字段，
    取不到就是 None（falsy），会被误判成"没做核心校验"，
    结果明明校验通过的产物一直发不出去。
    以 verification 为准：只有明确写着"核心校验通过"才放行。
    """
    return [
        name for name, item in (results or {}).items()
        if item.get("engine") == "mihomo"
        and item.get("core_checked") is not True
        and "核心校验通过" not in (item.get("verification") or "")
    ]


def _run_auto_build(summary: dict, now: datetime, force: bool = False) -> None:
    """自动构建与发布：读策略（只读）→ 构建（自管事务）→ 发布（短事务）。

    构建过程可能跑几十秒的 mihomo -t，绝不能占着写锁，
    否则设备拉取配置会因 database is locked 失败。
    """
    with db.connect() as conn:
        if not _enabled(conn, "auto_build_enabled", "1"):
            return
        try:
            interval_hours = max(1, int(_setting(conn, "auto_build_interval_hours", "1")))
        except ValueError:
            interval_hours = 1
        last_attempt = _setting(conn, "auto_build_last_attempt", "")
        if not force and not _due(last_attempt, interval_hours * 3600, now):
            return
        try:
            snapshot, policy_sha = builds.current_policy(conn)
        except Exception as exc:
            summary["build_error"] = f"读取策略失败：{exc}"
            return
        if not snapshot["targets"]:
            # 没有引擎平台时不推进检查时间，添加后可尽快自动构建
            summary["build_error"] = "尚未配置任何引擎平台"
            return
        publish = _enabled(conn, "auto_publish_enabled", "1")
        env = _setting(conn, "auto_publish_env", "production")
        if env not in ("production", "testing"):
            env = "production"
        # 判定基准是"该环境当前生效的构建"，不是"最近一次成功构建"——
        # 否则构建成功但没发布出去时，后续每轮都会因"策略未变化"被跳过，
        # 新产物永远上线不了。
        released = releases.current(conn, env)
        if released and released["policy_sha"] == policy_sha:
            with db.tx() as wconn:
                db.set_setting(wconn, "auto_build_last_attempt", db.now())
            summary["build"] = "策略未变化，跳过"
            return
        if publish:
            ready, missing, skipped = _publish_tests_ready(conn)
            if skipped:
                summary["skipped"] = "未开启测速的来源不参与门禁：" + "、".join(skipped)
            if not ready:
                summary["build_error"] = (
                    "自动构建发布等待测速结果：" + "、".join(missing)
                )
                if not _core_available():
                    # 核心缺失时永远等不到测速结果：退避到下一个周期，
                    # 不能每 30 秒空转一次。
                    with db.tx() as wconn:
                        db.set_setting(wconn, "auto_build_last_attempt", db.now())
                # 否则不推进自动构建时间：测速完成后下一轮立即重试
                return
    with db.tx() as conn:
        db.set_setting(conn, "auto_build_last_attempt", db.now())
    try:
        build_id, status = builds.create_build(
            AUTO_OPERATOR, note="自动构建", snapshot=snapshot,
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
    if status != "success" or not publish:
        return
    # 核心缺失时 Mihomo 产物只做了静态校验：自动构建发布到生产环境前必须确认
    # 每个 Mihomo 目标都过了核心校验，否则先降级为候选，等核心就位再发。
    try:
        with db.connect() as conn:
            row = db.one(conn, "SELECT results FROM builds WHERE id=?", (build_id,))
        results = json.loads(row["results"] or "{}")
        unchecked = _unchecked_core_targets(results) if _core_available() else []
        if unchecked:
            summary["build_error"] = (
                "以下 Mihomo 目标未做核心校验（mihomo -t），已跳过自动构建发布："
                + "、".join(unchecked)
            )
            return
    except Exception as exc:
        summary["build_error"] = f"读取构建结果失败：{exc}"
        return
    try:
        with db.tx(immediate=True) as conn:
            build = builds._get_build(conn, build_id)
            releases.publish_build(
                conn, build, AUTO_OPERATOR, "自动构建发布", releases.Env(env),
            )
    except Exception as exc:
        summary["build_error"] = f"自动构建发布失败：{exc}"
        logger.exception("自动构建发布失败")
        # 不推进 auto_build_last_attempt：发布没成功，下一轮要继续尝试
        with db.tx() as wconn:
            db.set_setting(wconn, "auto_build_last_attempt", "")
        return
    summary["published"] = env


def _run_retention(summary: dict) -> None:
    """磁盘留存清理：构建产物、审计日志、过期会话。最多每天一次。"""
    global _last_retention
    now = datetime.now(timezone.utc).astimezone()
    if _last_retention and _parse_time(_last_retention):
        if now - _parse_time(_last_retention) < timedelta(days=1):
            return
    try:
        result = retention.run_once()
        _last_retention = db.now()
        if result.get("artifacts") or result.get("audit") or result.get("sessions"):
            summary["retention"] = result
    except Exception as exc:
        summary["errors"].append(f"留存清理失败：{exc}")
        logger.warning("留存清理失败：%s", exc)


def _has_activity(summary: dict) -> bool:
    keys = ("sources_fetched", "sources_failed", "rules_fetched", "rules_failed",
            "snippets_fetched", "snippets_failed",
            "deps_created", "deps_updated", "deps_failed",
            "tests_run", "tests_errors", "build", "published")
    return any(summary.get(key) for key in keys) or bool(summary.get("errors"))


def _record_run(summary: dict, trigger: str, actor: str) -> None:
    """手动运行必记；定时运行在有实际动作或失败原因变化时记，避免每 30 秒刷屏。"""
    notice = (summary.get("build_error", "") or summary.get("test_skipped", "")
              or summary.get("skipped", ""))
    if trigger != "manual" and not _has_activity(summary):
        # 没有动作但有失败原因：仅在原因变化时记一条，便于回溯
        if not notice or notice == _state.get("last_notice", ""):
            return
    _state["last_notice"] = notice

    detail = {
        "trigger": trigger,
        "sources_fetched": summary["sources_fetched"],
        "sources_failed": summary["sources_failed"],
        "rules_fetched": summary["rules_fetched"],
        "rules_failed": summary["rules_failed"],
        "snippets_fetched": summary["snippets_fetched"],
        "snippets_failed": summary["snippets_failed"],
        "deps_created": summary["deps_created"],
        "deps_updated": summary["deps_updated"],
        "deps_failed": summary["deps_failed"],
        "tests_run": summary["tests_run"],
        "tests_ok": summary["tests_ok"],
        "tests_failed": summary["tests_failed"],
        "tests_errors": summary["tests_errors"],
        "build": summary.get("build"),
        "published": summary.get("published", ""),
        "retention": summary.get("retention"),
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
    """执行一轮检查；force=True 时忽略到期时间（用于“立即手动发布”）。"""
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
        "snippets_fetched": 0,
        "snippets_failed": 0,
        "deps_created": 0,
        "deps_updated": 0,
        "deps_failed": 0,
        "tests_run": 0,
        "tests_ok": 0,
        "tests_failed": 0,
        "tests_errors": 0,
        "build": None,
        "published": "",
        "retention": None,
        "errors": [],
    }
    try:
        with db.connect() as conn:
            master = _setting(conn, "scheduler_enabled", "1") == "1"
            fetch_sources = _enabled(conn, "auto_fetch_sources", "1")
            fetch_rules = _enabled(conn, "auto_fetch_rules", "1")
            fetch_snippets = _enabled(conn, "auto_fetch_snippets", "1")
            test_sources = _enabled(conn, "auto_test_sources", "1")
        if not master and not force:
            summary["skipped"] = "定时任务未启用"
        else:
            now = datetime.now(timezone.utc).astimezone()
            if fetch_sources:
                _run_source_fetch(summary, now, force=force)
            if fetch_rules:
                _run_rule_fetch(summary, now, force=force)
            if fetch_snippets:
                _run_snippet_fetch(summary, now, force=force)
            _run_deps_sync(summary, now, force=force)
            if test_sources:
                _run_source_test(summary, now, force=force)
            _run_auto_build(summary, now, force=force)
            _run_retention(summary)
        summary["finished_at"] = db.now()
        _state["last_tick_at"] = summary["finished_at"]
        _state["last_result"] = summary
        _state["last_error"] = ""
        logger.info(
            "定时任务完成：抓取节点 %s/%s，规则 %s/%s，模块 %s/%s，测速 %s，构建 %s",
            summary["sources_fetched"], summary["sources_fetched"] + summary["sources_failed"],
            summary["rules_fetched"], summary["rules_fetched"] + summary["rules_failed"],
            summary["snippets_fetched"],
            summary["snippets_fetched"] + summary["snippets_failed"],
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
                ("auto_build_interval_hours",
                 str(config.SETTINGS_DEFAULTS.get("auto_build_interval_hours", 1))),
                ("auto_publish_enabled", "1"),
                ("auto_publish_env", "production"),
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
