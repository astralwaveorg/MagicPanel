"""版本生命周期状态机。

一个构建在任意时刻只有一种状态：

    BUILT       已构建：产物已生成，从未发布过
    TESTING     预演中：预演通道生效的唯一版本（发布前的验证口子）
    PRODUCTION  已发布：当前生效的唯一版本（设备拉取这份）
    OFFLINE     已下线：曾发布过，被新版本替换或手动撤销（归档，不可彻底删除）

流转规则（全部在单个写事务内完成）：

    预演        BUILT / OFFLINE → TESTING        原预演版本自动下线
    发布        BUILT / TESTING / OFFLINE → PRODUCTION  原生效版本自动下线
    撤销预演    TESTING → OFFLINE                预演通道空置
    彻底删除    BUILT → 物理删除                 其余状态一律拒绝

「测试/生产」双渠道语义已收敛（2026-11-21）：常规流程改完直接发布，
预演只是发布前的验证口子；TESTING 内部值与历史数据保持兼容。

被替换的旧版本先置为 OFFLINE、目标版本后置为新状态，
配合 builds 表上的两条部分唯一索引，保证生效/预演通道全局至多一条版本。
"""
import json
import re
from enum import Enum

from .. import config, db, security
from .google_evidence import public_report


class BuildStatus(str, Enum):
    """构建的生命周期状态。"""

    BUILT = "BUILT"
    TESTING = "TESTING"
    PRODUCTION = "PRODUCTION"
    OFFLINE = "OFFLINE"


class Env(str, Enum):
    """发布通道（production=设备实际拉取；testing=预演验证口子）。"""

    TESTING = "testing"
    PRODUCTION = "production"


# 通道 → 该通道生效版本所处的状态
ENV_STATUS = {
    Env.TESTING: BuildStatus.TESTING,
    Env.PRODUCTION: BuildStatus.PRODUCTION,
}

STATUS_LABELS = {
    BuildStatus.BUILT: "已构建",
    BuildStatus.TESTING: "预演中",
    BuildStatus.PRODUCTION: "已发布",
    BuildStatus.OFFLINE: "已下线",
}

ENV_LABELS = {
    Env.TESTING: "预演",
    Env.PRODUCTION: "生效",
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
    """状态机拒绝的操作。调用方按 code 映射状态码转成 HTTP 响应。

    code 是机器可读的稳定标识：接口层据此决定 400/409，
    不再依赖中文文案字符串做前缀匹配（文案改动不应改变语义）。
    """

    def __init__(self, message: str, code: str = "release_rejected"):
        super().__init__(message)
        self.code = code


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
    # ORDER BY 纵深防御：正常由部分唯一索引保证单行，历史库索引缺失时
    # 不至于随机挑"生效版本"
    return db.one(conn, "SELECT * FROM builds WHERE status=? "
                        "ORDER BY status_updated_at DESC LIMIT 1", (status,))


def state_public(conn) -> dict:
    """当前发布状态（顶部概览区用）。"""
    out: dict = {}
    for env in (Env.PRODUCTION, Env.TESTING):
        row = current(conn, env)
        out[env.value] = build_public(row) if row else None
    out["release_revisions"] = {env.value: revision(conn, env)
                                for env in (Env.PRODUCTION, Env.TESTING)}
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
        results = json.loads(row["results"] or "{}")
        data["results"] = {}
        for name, item in results.items():
            safe = {key: item[key] for key in ('ok', 'engine', 'platform', 'device', 'target', 'variant', 'size', 'verification', 'core_checked') if key in item}
            digest = item.get('sha256')
            safe['sha256'] = digest if isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) else ''
            # 核心/渲染器诊断可能带回配置正文，普通读取只返回数量。
            safe['errors'] = ['构建校验未通过'] * len(item.get('errors', []))
            # 警告只含策略组、节点来源与本地节点的名称，不含凭据，可以原样返回。
            safe['warnings'] = [str(w) for w in item.get('warnings', [])]
            google = public_report(item.get('google_review'))
            if google is not None:
                safe['google_review'] = google
            data['results'][name] = safe
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


def revision(conn, env) -> int:
    """环境发布指针独立单调；不存在时按零版本兼容。"""
    row = db.one(conn, "SELECT revision FROM release_state WHERE env=?", (_env_of(env).value,))
    return int(row["revision"]) if row else 0


def _user_id(conn, operator: str) -> int:
    row = db.one(conn, "SELECT id FROM users WHERE username=?", (operator,))
    return int(row["id"]) if row else 0


def _operation_key(conn, action: str, env: Env, operator: str) -> tuple[str, str, int]:
    names = {"test": "publish", "prod": "publish", "both": "publish",
             "publish": "publish", "rollback": "rollback", "offline": "offline"}
    return names[action], _env_of(env).value, _user_id(conn, operator)


def _idempotent(conn, action: str, env: Env, operator: str,
                idempotency_key: str | None, payload_sha: str):
    if not idempotency_key:
        return None
    action_name, env_name, user_id = _operation_key(conn, action, env, operator)
    row = db.one(conn, "SELECT * FROM operation_requests WHERE action=? AND scope=? "
                       "AND actor_id=? AND idempotency_key=?",
                 (action_name, env_name, user_id, idempotency_key))
    if not row:
        return None
    if row["payload_sha"] != payload_sha:
        raise ReleaseError("release_idempotency_conflict")
    return json.loads(row["response_json"])


def _save_operation(conn, action: str, env: Env, operator: str,
                    idempotency_key: str | None, payload_sha: str,
                    response: dict) -> None:
    if not idempotency_key:
        return
    action_name, env_name, user_id = _operation_key(conn, action, env, operator)
    conn.execute("INSERT OR IGNORE INTO operation_requests(action,scope,actor_id,"
                 "idempotency_key,payload_sha,response_json,state,created_at) "
                 "VALUES(?,?,?,?,?,?,'completed',?)",
                 (action_name, env_name, user_id, idempotency_key, payload_sha,
                  json.dumps(response, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')), db.now()))


def _bump_release_state(conn, env: Env, build_id) -> int:
    now = db.now()
    conn.execute("INSERT OR IGNORE INTO release_state(env,revision,current_build_id,updated_at) "
                 "VALUES(?,0,?,?)", (env.value, str(build_id), now))
    conn.execute("UPDATE release_state SET revision=revision+1,current_build_id=?,updated_at=? "
                 "WHERE env=?", (str(build_id), now, env.value))
    return revision(conn, env)


def _switch(conn, build, env: Env, status: BuildStatus, action: str,
            operator: str, reason: str, record: bool = True,
            expected_revision: int | None = None,
            idempotency_key: str | None = None,
            bump_revision: bool = True) -> dict:
    """执行一次已验证状态切换；调用方必须已开启写事务。"""
    current_revision = revision(conn, env)
    if expected_revision is not None and expected_revision != current_revision:
        raise ReleaseError(
            f"发布版本已变化：期望 {expected_revision}，当前 {current_revision}",
            code="release_revision_changed")
    payload_sha = json.dumps({"build": int(build["id"]), "reason": reason,
                              "status": status.value}, ensure_ascii=False,
                             sort_keys=True, separators=(',', ':'))
    replay = _idempotent(conn, action, env, operator, idempotency_key, payload_sha)
    if replay is not None:
        return replay
    now = db.now()
    old = current(conn, env)
    replaced = None
    if old and int(old["id"]) != int(build["id"]):
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
    # bump_revision=False：publish_build 经测试环境的过渡步骤——
    # 测试指针马上会被生产切换覆盖，bump 只会留下幽灵 revision 变更，
    # 任何消费 release_state/revision 的对账都会看到无意义的 +1
    result = {"build_id": int(build["id"]), "status": status.value,
              "env": env.value, "action": action, "replaced": replaced,
              "release_revision": (
                  _bump_release_state(conn, env, build["id"]) if bump_revision
                  else revision(conn, env))}
    _save_operation(conn, action, env, operator, idempotency_key, payload_sha, result)
    return result


def _check_artifacts(build) -> None:
    """产物被留存清理的构建不能发布：设备会拿到 503。"""
    missing = _missing_artifacts(build)
    if missing:
        raise ReleaseError("该构建的产物已被清理，无法发布：" + "、".join(missing))


def publish_to_testing(conn, build, operator: str, reason: str = "",
                       record: bool = True, expected_revision: int | None = None,
                       idempotency_key: str | None = None,
                       bump_revision: bool = True) -> dict:
    """预演：BUILT / OFFLINE → TESTING。发布前的验证口子，不影响设备拉取。"""
    status = build["status"]
    if status == BuildStatus.TESTING.value:
        raise ReleaseError("该构建已在预演中")
    if status not in (BuildStatus.BUILT.value, BuildStatus.OFFLINE.value):
        raise ReleaseError("只有未发布过或已下线的构建可以进入预演")
    _check_publishable(build)
    _check_artifacts(build)
    return _switch(conn, build, Env.TESTING, BuildStatus.TESTING,
                   ACTION_PUBLISH, operator, reason, record=record,
                   expected_revision=expected_revision,
                   idempotency_key=idempotency_key,
                   bump_revision=bump_revision)


def publish_to_production(conn, build, operator: str, reason: str = "",
                          rollback: bool = False, record: bool = True,
                          expected_revision: int | None = None,
                          idempotency_key: str | None = None) -> dict:
    """发布：BUILT / TESTING / OFFLINE → PRODUCTION。

    常规流程改完直接发布（2026-11-21 收敛）；预演中的构建也可以直接转正。
    """
    status = build["status"]
    if status == BuildStatus.PRODUCTION.value:
        raise ReleaseError("该构建已是当前发布版本")
    if status not in (BuildStatus.BUILT.value, BuildStatus.TESTING.value,
                      BuildStatus.OFFLINE.value):
        raise ReleaseError("只有已构建、预演中或已下线的构建可以发布")
    _check_publishable(build)
    _check_artifacts(build)
    action = ACTION_ROLLBACK if rollback else ACTION_PUBLISH
    return _switch(conn, build, Env.PRODUCTION, BuildStatus.PRODUCTION,
                   action, operator, reason, record=record,
                   expected_revision=expected_revision,
                   idempotency_key=idempotency_key)


def offline(conn, build, operator: str, reason: str = "",
            expected_revision: int | None = None,
            idempotency_key: str | None = None) -> dict:
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
    result = {"build_id": int(build["id"]), "status": BuildStatus.OFFLINE.value,
              "env": Env.TESTING.value, "action": ACTION_OFFLINE, "replaced": None,
              "release_revision": _bump_release_state(conn, Env.TESTING, build["id"])}
    # 幂等键公式必须与 _switch 一致（build+reason+status 摘要）：
    # 原来存的是响应体 json.dumps(result)，接口层用 _switch 公式做重放比对，
    # 同 key 重试永远 conflict，幂等保护对 offline 形同虚设（2026-11-18 修复）
    payload_sha = json.dumps({"build": int(build["id"]), "reason": reason,
                              "status": BuildStatus.OFFLINE.value}, ensure_ascii=False,
                             sort_keys=True, separators=(',', ':'))
    _save_operation(conn, "offline", Env.TESTING, operator, idempotency_key,
                    payload_sha, result)
    return result


def publish_build(conn, build, operator: str, reason: str = "",
                  env: Env = Env.PRODUCTION,
                  expected_revisions: dict | None = None,
                  idempotency_keys: dict | None = None) -> dict:
    """一步到位地发布构建到指定通道。

    发布通道（production）允许 BUILT 直接上线，单步切换；
    预演通道走 publish_to_testing。
    """
    env = _env_of(env)
    if env is Env.TESTING:
        return publish_to_testing(conn, build, operator, reason,
            expected_revision=(expected_revisions or {}).get("testing"),
            idempotency_key=(idempotency_keys or {}).get("testing"))
    return publish_to_production(conn, build, operator, reason,
        expected_revision=(expected_revisions or {}).get("production"),
        idempotency_key=(idempotency_keys or {}).get("production"))
