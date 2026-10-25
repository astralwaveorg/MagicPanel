"""依赖文件库的 Git 操作层。

只做 Git 相关的动作：克隆、拉取、提交、推送、读写文件、看历史。
业务判断（哪些文件是规则集合、要不要建来源）不在这里。

设计要点：
- 统一用 subprocess 调 git，禁止 shell=True（仓库地址来自设置项，不能拼进 shell）
- 每次调用注入固定配置：禁用钩子、禁用签名、拉取不 rebase、信任目录
- SSH 私钥用时写临时文件（600），用完立即删；接口永不回显私钥
- 模块级锁串行化所有 Git 操作，定时同步与用户操作不并发
"""
import base64
import fnmatch
import os
import subprocess
import threading
from pathlib import Path

from .. import config, db, security

WORKDIR = config.DATA_DIR / "deps" / "rule-repo"
KEY_PATH = config.DATA_DIR / "deps" / ".mp_key"
MAX_FILE_BYTES = 2 * 1024 * 1024
DEFAULT_EXCLUDES = ".git,.github,.env,*.bak,.*"

# 所有 Git 操作串行：定时同步与用户手动操作抢锁时，用户优先
_lock = threading.RLock()


class RepoError(Exception):
    """Git 操作失败。消息面向用户，不回传原始 stderr。"""


# ---------------------------------------------------------------- 设置读写

def _setting(conn, key: str, default: str = "") -> str:
    row = db.one(conn, "SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def get_settings(conn) -> dict:
    """对外的设置视图：私钥与 token 只回显"是否已配置"。"""
    return {
        "enabled": _setting(conn, "deps_enabled", "0") == "1",
        "url": _setting(conn, "deps_url", ""),
        "branch": _setting(conn, "deps_branch", "main"),
        "auth": _setting(conn, "deps_auth", "ssh"),
        "has_private_key": bool(_setting(conn, "deps_private_key_enc", "")),
        "has_token": bool(_setting(conn, "deps_token_enc", "")),
        "commit_name": _setting(conn, "deps_commit_name", "MagicPanel"),
        "commit_email": _setting(conn, "deps_commit_email", "magicpanel@localhost"),
        "sync_hours": int(_setting(conn, "deps_sync_hours", "12") or 12),
        "auto_push": _setting(conn, "deps_auto_push", "1") == "1",
        "auto_create_rule_sources": _setting(conn, "deps_auto_create_rule_sources", "1") == "1",
        "exclude_paths": _setting(conn, "deps_exclude_paths", DEFAULT_EXCLUDES),
        "max_file_bytes": int(_setting(conn, "deps_max_file_bytes", str(MAX_FILE_BYTES))
                             or MAX_FILE_BYTES),
        "last_sync_at": _setting(conn, "deps_last_sync_at", ""),
        "last_commit": _setting(conn, "deps_last_commit", ""),
        "last_error": _setting(conn, "deps_last_error", ""),
    }


def save_settings(conn, values: dict) -> None:
    """保存设置。值为 None 表示清空该键。"""
    for key, value in values.items():
        if value is None:
            conn.execute("DELETE FROM settings WHERE key=?", (key,))
            continue
        db.set_setting(conn, key, str(value))


# ---------------------------------------------------------------- Git 底层

def _write_key(conn) -> str | None:
    """把私钥写成临时文件（600）；返回路径，用完由调用方删。"""
    enc = _setting(conn, "deps_private_key_enc", "")
    if not enc:
        return None
    plain = security.decrypt_text(enc)
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_text(plain, encoding="utf-8")
    try:
        KEY_PATH.chmod(0o600)
    except OSError:
        pass
    return str(KEY_PATH)


def _env(conn) -> dict:
    """组装子进程环境：SSH 私钥、HTTPS token、禁用交互提示。"""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"
    env["GCM_INTERACTIVE"] = "never"
    key_path = _write_key(conn)
    if key_path:
        # known_hosts 落在数据目录里：容器没有可写的 HOME，指到别处会写不进去
        known = config.DATA_DIR / "deps" / "known_hosts"
        known.parent.mkdir(parents=True, exist_ok=True)
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {key_path} -o IdentitiesOnly=yes "
            f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={known}"
        )
    token = _setting(conn, "deps_token_enc", "")
    if token:
        plain = security.decrypt_text(token)
        url = _setting(conn, "deps_url", "")
        if url.startswith("https://") and "@" not in url.split("://", 1)[1][:100]:
            scheme, rest = url.split("://", 1)
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "http.extraheader"
            env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {_b64(plain)}"
    return env


def _b64(text: str) -> str:
    import base64 as _b
    return _b.b64encode(text.encode()).decode()


def _git(args: list[str], conn=None, check: bool = True,
         timeout: int = 120) -> subprocess.CompletedProcess:
    """跑一条 git 命令。固定配置注入，不继承用户的 git 配置。"""
    base = [
        "git",
        "-c", "core.hooksPath=/dev/null",
        "-c", "commit.gpgsign=false",
        "-c", "pull.rebase=false",
        "-c", f"safe.directory={WORKDIR}",
        "-c", "advice.detachedHead=false",
    ]
    cmd = base + ["-C", str(WORKDIR)] + args
    env = _env(conn) if conn is not None else dict(os.environ)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=env, cwd=str(WORKDIR) if WORKDIR.exists() else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"git {args[0]} 超时") from exc
    except FileNotFoundError as exc:
        raise RepoError("容器里没有 git，请用带 git 的镜像重新部署") from exc
    finally:
        # 临时私钥用完即删，异常路径也删
        if conn is not None:
            _cleanup_key()
    if check and proc.returncode != 0:
        raise RepoError(_friendly_error(args, proc.stderr or proc.stdout))
    return proc


def _friendly_error(args: list[str], stderr: str) -> str:
    """把 git 的报错翻译成用户看得懂、能照着做的话。"""
    text = stderr.strip()
    lowered = text.lower()
    if "permission denied (publickey)" in lowered:
        return "私钥与 GitHub 上的公钥不匹配（检查部署密钥是否加在这个仓库）"
    if "denied to deploy key" in lowered:
        return "部署密钥是只读的，需要在 GitHub 上勾上 Allow write access"
    if "repository not found" in lowered:
        return "仓库地址错，或部署密钥没有加到这个仓库"
    if "could not resolve hostname" in lowered:
        return "容器出网不通，检查网络或代理设置"
    if "could not resolve host" in lowered:
        return "容器出网不通，检查网络或代理设置"
    if "host key verification failed" in lowered:
        return "SSH 主机密钥校验失败，检查仓库地址是否正确"
    if "authentication failed" in lowered:
        return "鉴权失败：检查凭据或部署密钥"
    if "non-fast-forward" in lowered:
        return "远端有新提交，先拉取再推送"
    if "conflict" in lowered:
        return "存在冲突，需要先解决冲突"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    useful = [ln for ln in lines
              if not ln.startswith("Cloning into") and not ln.startswith("warning:")]
    first = (useful or lines or [""])[0]
    return f"git {args[0]} 失败：{first}" if first else f"git {args[0]} 失败"


def _cleanup_key() -> None:
    """删掉临时私钥文件；异常路径也要删。"""
    try:
        if KEY_PATH.exists():
            KEY_PATH.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 仓库动作

def is_cloned() -> bool:
    return (WORKDIR / ".git").exists()


def require_cloned() -> None:
    if not is_cloned():
        raise RepoError("仓库还没有克隆，请先在设置里配置地址与密钥并克隆")


def clone(conn) -> dict:
    """首次克隆。目标目录存在且非空时拒绝，避免覆盖已有数据。"""
    url = _setting(conn, "deps_url", "")
    branch = _setting(conn, "deps_branch", "main") or "main"
    if not url:
        raise RepoError("没有配置仓库地址")
    if WORKDIR.exists() and any(WORKDIR.iterdir()):
        raise RepoError("工作目录已存在且非空，拒绝覆盖")
    WORKDIR.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
        "clone", "--branch", branch, "--single-branch", url, str(WORKDIR),
    ]
    env = _env(conn)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=600, env=env)
    except FileNotFoundError as exc:
        raise RepoError("容器里没有 git，请用带 git 的镜像重新部署") from exc
    finally:
        _cleanup_key()
    if proc.returncode != 0:
        raise RepoError(_friendly_error(["clone"], proc.stderr or proc.stdout))
    return {"commit": head_commit(conn), "branch": branch}


def head_commit(conn=None) -> str:
    proc = _git(["rev-parse", "--short", "HEAD"], conn, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def fetch(conn) -> None:
    require_cloned()
    branch = _setting(conn, "deps_branch", "main") or "main"
    _git(["fetch", "origin", branch], conn)


def pull(conn) -> None:
    """拉取并 rebase。有本地改动时先自动提交。"""
    require_cloned()
    branch = _setting(conn, "deps_branch", "main") or "main"
    if dirty_files(conn):
        commit_all(conn, "面板自动提交：同步前保留本地改动")
    _git(["pull", "--rebase", "origin", branch], conn)


def push(conn) -> None:
    require_cloned()
    branch = _setting(conn, "deps_branch", "main") or "main"
    _git(["push", "origin", f"HEAD:{branch}"], conn)


def commit_all(conn, message: str) -> str:
    """提交全部改动，返回新 commit。"""
    require_cloned()
    name = _setting(conn, "deps_commit_name", "MagicPanel")
    email = _setting(conn, "deps_commit_email", "magicpanel@localhost")
    _git(["add", "-A", "."], conn)
    _git(["-c", f"user.name={name}", "-c", f"user.email={email}",
          "commit", "-m", message], conn)
    return head_commit(conn)


def dirty_files(conn) -> list[str]:
    """有本地改动的文件（相对 HEAD）。"""
    proc = _git(["status", "--porcelain"], conn, check=False)
    if proc.returncode != 0:
        return []
    out = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:      # 重命名
            path = path.split(" -> ")[-1]
        out.append(path)
    return out


def conflicted_files(conn) -> list[str]:
    proc = _git(["diff", "--name-only", "--diff-filter=U"], conn, check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def ahead_behind(conn) -> tuple[int, int]:
    """领先 / 落后远端的提交数。"""
    branch = _setting(conn, "deps_branch", "main") or "main"
    proc = _git(["rev-list", "--left-right", "--count",
                 f"HEAD...origin/{branch}"], conn, check=False)
    if proc.returncode != 0:
        return (0, 0)
    parts = proc.stdout.split()
    if len(parts) < 2:
        return (0, 0)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (0, 0)


def remote_changed_files(conn) -> list[str]:
    """远端相对本地 HEAD 改动的文件（远端已更新）。"""
    branch = _setting(conn, "deps_branch", "main") or "main"
    proc = _git(["diff", "--name-only", "HEAD", f"origin/{branch}"], conn, check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def status(conn) -> dict:
    """仓库状态条要的信息。"""
    cfg = get_settings(conn)
    out = {
        "configured": bool(cfg["url"]) and cfg["enabled"],
        "enabled": cfg["enabled"],
        "cloned": is_cloned(),
        "url": cfg["url"],
        "branch": cfg["branch"],
        "commit": "",
        "ahead": 0,
        "behind": 0,
        "dirty": [],
        "conflicts": [],
        "remote_changed": [],
        "last_sync_at": cfg["last_sync_at"],
        "last_error": cfg["last_error"],
    }
    if not out["cloned"]:
        return out
    out["commit"] = head_commit(conn)
    out["dirty"] = dirty_files(conn)
    out["conflicts"] = conflicted_files(conn)
    out["ahead"], out["behind"] = ahead_behind(conn)
    out["remote_changed"] = remote_changed_files(conn)
    return out


# ---------------------------------------------------------------- 文件管理

def exclude_patterns(conn) -> list[str]:
    raw = _setting(conn, "deps_exclude_paths", DEFAULT_EXCLUDES)
    return [p.strip() for p in raw.split(",") if p.strip()]


def is_excluded(path: str, patterns: list[str]) -> bool:
    """排除清单按 glob 匹配仓库内路径；`.git` 永远不可碰。"""
    for pattern in patterns:
        if pattern == ".git":
            if path == ".git" or path.startswith(".git/"):
                return True
            continue
        if fnmatch.fnmatch(path, pattern):
            return True
        # 目录级排除：`.github` 排除 `.github/workflows/ci.yml`
        if fnmatch.fnmatch(path, pattern + "/*"):
            return True
        parts = path.split("/")
        if any(fnmatch.fnmatch(part, pattern) for part in parts[:-1]):
            return True
    return False


def list_files(conn) -> list[dict]:
    """仓库内可管理的文件清单（排除清单内的路径完全不显示）。"""
    require_cloned()
    patterns = exclude_patterns(conn)
    state = status(conn)
    dirty = set(state["dirty"])
    conflicts = set(state["conflicts"])
    remote = set(state["remote_changed"])
    out: list[dict] = []
    root = WORKDIR
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if is_excluded(rel, patterns):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        binary = _is_binary(path)
        out.append({
            "path": rel,
            "size": size,
            "binary": binary,
            "status": _file_status(rel, dirty, conflicts, remote),
            "rule_source": _rule_source_for(rel, conn),
        })
    return out


def _file_status(rel: str, dirty: set, conflicts: set, remote: set) -> str:
    if rel in conflicts:
        return "conflict"
    if rel in dirty:
        return "modified"
    if rel in remote:
        return "remote"
    return "clean"


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(4096)
    except OSError:
        return True
    return b"\x00" in chunk


def _rule_source_for(rel: str, conn) -> str:
    """这个文件是否已被规则来源引用（仓库托管的 rule/*.yaml）。"""
    if not rel.startswith("rule/"):
        return ""
    name = rel.rsplit("/", 1)[-1]
    if not name.endswith(".yaml"):
        return ""
    stem = name[:-len(".yaml")]
    row = db.one(conn, "SELECT name FROM rule_providers WHERE name=?", (stem,))
    return row["name"] if row else ""


def safe_path(conn, rel: str) -> Path:
    """把仓库内相对路径解析成绝对路径，拒绝越界与符号链接。"""
    patterns = exclude_patterns(conn)
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        raise RepoError("路径非法")
    if is_excluded(rel, patterns):
        raise RepoError("该路径在排除清单里，不允许访问")
    target = (WORKDIR / rel).resolve()
    root = WORKDIR.resolve()
    if root != target and root not in target.parents:
        raise RepoError("路径非法")
    if target.is_symlink():
        raise RepoError("不接受符号链接")
    return target


def read_file(conn, rel: str) -> dict:
    """读文件内容。文本给字符串，二进制给 base64。"""
    require_cloned()
    target = safe_path(conn, rel)
    if not target.exists() or not target.is_file():
        raise RepoError("文件不存在")
    limit = int(_setting(conn, "deps_max_file_bytes", str(MAX_FILE_BYTES))
                or MAX_FILE_BYTES)
    data = target.read_bytes()
    if len(data) > limit:
        raise RepoError(f"文件超过大小上限（{limit // 1024 // 1024} MB）")
    if _is_binary(target):
        return {"path": rel, "binary": True,
                "content": base64.b64encode(data).decode("ascii"), "size": len(data)}
    return {"path": rel, "binary": False, "content": data.decode("utf-8", "replace"),
            "size": len(data)}


def write_file(conn, rel: str, content: str) -> None:
    """写文件到工作树（不提交）。"""
    require_cloned()
    target = safe_path(conn, rel)
    limit = int(_setting(conn, "deps_max_file_bytes", str(MAX_FILE_BYTES))
                or MAX_FILE_BYTES)
    raw = content.encode("utf-8")
    if len(raw) > limit:
        raise RepoError(f"内容超过大小上限（{limit // 1024 // 1024} MB）")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def create_file(conn, rel: str, content: str) -> None:
    require_cloned()
    target = safe_path(conn, rel)
    if target.exists():
        raise RepoError("文件已存在")
    write_file(conn, rel, content)


def delete_file(conn, rel: str) -> None:
    require_cloned()
    target = safe_path(conn, rel)
    if not target.exists():
        raise RepoError("文件不存在")
    target.unlink()


def history(conn, limit: int = 30) -> list[dict]:
    require_cloned()
    proc = _git(["log", f"-{limit}", "--pretty=format:%H\t%h\t%an\t%ad\t%s",
                 "--date=iso"], conn, check=False)
    if proc.returncode != 0:
        return []
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        out.append({"commit": parts[0], "short": parts[1], "author": parts[2],
                    "date": parts[3], "message": parts[4]})
    return out


def show_commit(conn, commit: str) -> dict:
    require_cloned()
    proc = _git(["show", "--stat", "--pretty=format:%H%n%h%n%an%n%ad%n%s",
                 "--date=iso", commit], conn, check=False)
    if proc.returncode != 0:
        raise RepoError("找不到这个提交")
    return {"diff": proc.stdout}


def revert_commit(conn, commit: str, message: str = "") -> str:
    """生成一个 revert 提交（不改写历史）。"""
    require_cloned()
    msg = message or f"回滚到 {commit[:8]}"
    _git(["revert", "--no-edit", commit], conn)
    return head_commit(conn)


def conflict_stage(conn, rel: str, content: str | None, resolution: str) -> None:
    """解决冲突：manual 写内容；theirs/ours 直接取一侧。"""
    require_cloned()
    target = safe_path(conn, rel)
    if resolution == "manual":
        if content is None:
            raise RepoError("手工解决必须提供内容")
        target.write_text(content, encoding="utf-8")
    elif resolution == "theirs":
        _git(["checkout", "--theirs", "--", rel], conn)
    elif resolution == "ours":
        _git(["checkout", "--ours", "--", rel], conn)
    else:
        raise RepoError("解决方式仅支持 manual / theirs / ours")
    # 校验没有残留冲突标记
    text = target.read_text(encoding="utf-8", errors="replace")
    for mark in ("<<<<<<<", "=======", ">>>>>>>"):
        if mark in text:
            raise RepoError("内容里还有冲突标记，没有解决干净")
    _git(["add", rel], conn)


def three_way(conn, rel: str) -> dict:
    """冲突文件的三方内容：base / ours / theirs。"""
    require_cloned()
    out = {}
    for stage, label in (("1", "base"), ("2", "ours"), ("3", "theirs")):
        proc = _git(["show", f":{stage}:{rel}"], conn, check=False)
        out[label] = proc.stdout if proc.returncode == 0 else ""
    return out


def generate_keypair() -> tuple[str, str]:
    """生成 SSH 密钥对，返回 (私钥, 公钥)。私钥由调用方加密落库，不回显。"""
    import shutil
    import tempfile
    if not shutil.which("ssh-keygen"):
        raise RepoError("容器里没有 ssh-keygen，请用带 git 的镜像重新部署")
    tmp = Path(tempfile.mkdtemp())
    priv = tmp / "id_ed25519"
    try:
        proc = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "magicpanel",
             "-f", str(priv)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise RepoError("生成密钥失败")
        return priv.read_text(encoding="utf-8"), \
            (tmp / "id_ed25519.pub").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
