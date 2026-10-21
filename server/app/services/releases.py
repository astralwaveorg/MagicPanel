"""版本生命周期状态机。

一个构建在任意时刻只有一种状态：

    BUILT       已构建：产物已生成，从未发布过
    TESTING     测试中：当前测试环境生效的唯一版本
    PRODUCTION  生产中：当前生产环境生效的唯一版本（受保护）
    OFFLINE     已下线：曾发布过，被新版本替换或手动撤销（归档，不可彻底删除）

流转规则（全部在单个写事务内完成）：

    发布至测试  BUILT / OFFLINE → TESTING     原 TESTING 版本自动下线
    发布至生产  TESTING / OFFLINE → PRODUCTION 原 PRODUCTION 版本自动下线
    手动下线    TESTING → OFFLINE              测试环境空置
    彻底删除    BUILT → 物理删除               其余状态一律拒绝

被替换的旧版本先置为 OFFLINE、目标版本后置为新状态，
配合 builds 表上的两条部分唯一索引，保证生产/测试环境全局至多一条生效版本。
"""
import json
from enum import Enum

from .. import config, db, security


class BuildStatus(str, Enum):
    """构建的生命周期状态。"""

    BUILT = "BUILT"
    TESTING = "TESTING"
    PRODUCTION = "PRODUCTION"
    OFFLINE = "OFFLINE"


class Env(str, Enum):
    """发布环境（取代旧的"通道"概念）。"""

    TESTING = "testing"
    PRODUCTION = "production"


# 环境 → 该环境生效版本所处的状态
ENV_STATUS = {
    Env.TESTING: BuildStatus.TESTING,
    Env.PRODUCTION: BuildStatus.PRODUCTION,
}

STATUS_LABELS = {
    BuildStatus.BUILT: "已构建",
    BuildStatus.TESTING: "测试中",
    BuildStatus.PRODUCTION: "生产中",
    BuildStatus.OFFLINE: "已下线",
}

ENV_LABELS = {
    Env.TESTING: "测试环境",
    Env.PRODUCTION: "生产环境",
}

# 发布历史里的动作
ACTION_PUBLISH = "publish"
ACTION_ROLLBACK = "rollback"
ACTION_OFFLINE = "offline"

ACTION_LABELS = {
    ACTION_PUBLISH: "发布",
    ACTION_ROLLBACK: "回滚",
    ACTION_OFFLINE: "下线",
}


class ReleaseError(Exception):
    """状态机拒绝的操作。调用方转成 400 返回给界面。"""


def _env_of(env) -> Env:
    if isinstance(env, Env):
        return env
    try:
        return Env(str(env))
    except ValueError:
        raise ReleaseError(f"环境仅支持 production / testing，收到：{env}")


def current(conn, env):
    """取某环境当前生效的构建行，没有则返回 None。"""
    env = _env_of(env)
    status = ENV_STATUS[env].value
    return db.one(conn, "SELECT * FROM builds WHERE status=? LIMIT 1", (status,))


def state_public(conn) -> dict:
    """当前发布状态（顶部概览区用）。"""
    out: dict = {}
    for env in (Env.PRODUCTION, Env.TESTING):
        row = current(conn, env)
        out[env.value] = build_public(row) if row else None
    return out


def build_public(row, with_results: bool = False) -> dict:
    """构建的对外结构。"""
    if row is None:
        return {}
    data = {
        "id": row["id"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "status": row["status"],
        "verify_status": row["verify_status"],
        "policy_sha": row["policy_sha"],
        "note": row["note"],
        "published_at": row["published_at"] or "",
        "published_by": row["published_by"] or "",
        "publish_reason": row["publish_reason"] or "",
        "status_updated_at": row["status_updated_at"] or "",
    }
    if with_results:
        data["results"] = json.loads(row["results"] or "{}")
        data["snapshot"] = json.loads(
            security.decrypt_payload(row["snapshot"] or "{}") or "{}")
    return data


def _missing_artifacts(build) -> list[str]:
    """构建产物是否已被留存清理；缺产物的构建不能上线（设备会拿到 503）。"""
    results = json.loads(build["results"] or "{}")
    missing = []
    for name, item in results.items():
        if not item.get("ok"):
            continue
        if not (config.BUILDS_DIR / str(build["id"]) / f"{name}.yaml").exists():
            missing.append(name)
    return missing


def _check_publishable(build) -> None:
    if build["verify_status"] != "success":
        raise ReleaseError("该构建未通过校验，不能发布")


def _switch(conn, build, env: Env, status: BuildStatus, action: str,
            operator: str, reason: str, record: bool = True) -> dict:
    """执行一次状态切换（调用方必须已开启写事务）。

    record=False 时不写发布历史：两步流转（自动发布到生产）算一次操作，
    只留最终那一条历史，否则 10 条上限会被一轮操作吃掉两条。
    """
    now = db.now()
    old = current(conn, env)
    replaced = None
    if old and int(old["id"]) != int(build["id"]):
        # 先下线旧版本：唯一索引要求同一环境至多一条生效记录
        conn.execute(
            "UPDATE builds SET status=?, status_updated_at=? WHERE id=?",
            (BuildStatus.OFFLINE.value, now, old["id"]))
        replaced = int(old["id"])
    conn.execute(
        "UPDATE builds SET status=?, status_updated_at=?, published_at=?, "
        "published_by=?, publish_reason=? WHERE id=?",
        (status.value, now, now, operator, reason, build["id"]))
    if record:
        conn.execute(
            "INSERT INTO releases(build_id, env, action, operator, reason, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (build["id"], env.value, action, operator, reason, now))
        # 发布历史只保留最近 N 条；完整操作仍可在审计日志中追溯
        conn.execute(
            "DELETE FROM releases WHERE id NOT IN "
            "(SELECT id FROM releases ORDER BY id DESC LIMIT ?)",
            (config.RELEASE_HISTORY_LIMIT,))
    security.audit(
        conn, operator,
        {"publish": f"发布到{ENV_LABELS[env]}",
         "rollback": "回滚到生产版本",
         "offline": "下线构建"}[action],
        "build", build["id"],
        {"status": status.value, "env": env.value, "action": action,
         "reason": reason, "replaced": replaced})
    return {"build_id": int(build["id"]), "status": status.value,
            "env": env.value, "action": action, "replaced": replaced}


def _check_artifacts(build) -> None:
    """产物被留存清理的构建不能发布：设备会拿到 503。"""
    missing = _missing_artifacts(build)
    if missing:
        raise ReleaseError("该构建的产物已被清理，无法发布：" + "、".join(missing))


def publish_to_testing(conn, build, operator: str, reason: str = "",
                       record: bool = True) -> dict:
    """发布至测试环境：BUILT / OFFLINE → TESTING。"""
    status = build["status"]
    if status == BuildStatus.TESTING.value:
        raise ReleaseError("该构建已是当前测试版本")
    if status not in (BuildStatus.BUILT.value, BuildStatus.OFFLINE.value):
        raise ReleaseError("只有未发布过或已下线的构建可以发布至测试环境")
    _check_publishable(build)
    _check_artifacts(build)
    return _switch(conn, build, Env.TESTING, BuildStatus.TESTING,
                   ACTION_PUBLISH, operator, reason, record=record)


def publish_to_production(conn, build, operator: str, reason: str = "",
                          rollback: bool = False, record: bool = True) -> dict:
    """发布至生产环境：TESTING / OFFLINE → PRODUCTION。

    未经过测试的构建（BUILT）不允许直接上线。
    """
    status = build["status"]
    if status == BuildStatus.PRODUCTION.value:
        raise ReleaseError("该构建已是当前生产版本")
    if status not in (BuildStatus.TESTING.value, BuildStatus.OFFLINE.value):
        raise ReleaseError("请先发布至测试环境，再发布至生产环境")
    _check_publishable(build)
    _check_artifacts(build)
    action = ACTION_ROLLBACK if rollback else ACTION_PUBLISH
    return _switch(conn, build, Env.PRODUCTION, BuildStatus.PRODUCTION,
                   action, operator, reason, record=record)


def offline(conn, build, operator: str, reason: str = "") -> dict:
    """手动下线：TESTING → OFFLINE（测试环境空置）。"""
    if build["status"] != BuildStatus.TESTING.value:
        raise ReleaseError("只有当前测试版本可以下线")
    now = db.now()
    conn.execute(
        "UPDATE builds SET status=?, status_updated_at=? WHERE id=?",
        (BuildStatus.OFFLINE.value, now, build["id"]))
    conn.execute(
        "INSERT INTO releases(build_id, env, action, operator, reason, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (build["id"], Env.TESTING.value, ACTION_OFFLINE, operator, reason, now))
    conn.execute(
        "DELETE FROM releases WHERE id NOT IN "
        "(SELECT id FROM releases ORDER BY id DESC LIMIT ?)",
        (config.RELEASE_HISTORY_LIMIT,))
    security.audit(conn, operator, "下线构建", "build", build["id"],
                   {"status": BuildStatus.OFFLINE.value, "reason": reason})
    return {"build_id": int(build["id"]), "status": BuildStatus.OFFLINE.value,
            "env": Env.TESTING.value, "action": ACTION_OFFLINE, "replaced": None}


def publish_build(conn, build, operator: str, reason: str = "",
                  env: Env = Env.PRODUCTION) -> dict:
    """一步到位地发布构建到指定环境。

    规格要求"发布至生产"的来源状态必须是 TESTING 或 OFFLINE，
    而自动任务与"保存并构建发布"要在同一轮里把新构建推上线，
    因此这里先置 TESTING、再置 PRODUCTION，两步同处一个事务，状态原子切换。

    两步算**一次**发布：发布历史只记最终那一条（否则 10 条上限一轮就吃掉两条）。
    """
    env = _env_of(env)
    if env is Env.TESTING:
        return publish_to_testing(conn, build, operator, reason)
    publish_to_testing(conn, build, operator, reason, record=False)
    fresh = db.one(conn, "SELECT * FROM builds WHERE id=?", (build["id"],))
    return publish_to_production(conn, fresh, operator, reason)
