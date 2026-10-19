"""节点连通性测试：调用固定版本的 Mihomo 核心，与 Clash 系客户端同机制。

原理：以节点集合生成临时配置启动本地核心，经其 external-controller
逐个发起 delay 测试（通过节点请求 generate_204）。它衡量的是从本服务器
所在网络出发的连通性与延迟，不等于带宽、解锁能力，也不代表客户端侧结果。
UDP 行为未单独验证。
"""
import gzip
import hashlib
import platform
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yaml

from .. import config

MIHOMO_VERSION = "v1.19.32"
RELEASE_BASE = "https://github.com/MetaCubeX/mihomo/releases/download"
DELAY_URL = "https://www.gstatic.com/generate_204"
DELAY_TIMEOUT_MS = 5000
CONCURRENCY = 16
STARTUP_TIMEOUT = 8.0


class TestError(Exception):
    pass


def core_path() -> Path:
    return config.DATA_DIR / "bin" / "mihomo"


def core_status() -> dict:
    path = core_path()
    if not path.exists():
        return {"available": False, "version": "", "path": str(path),
                "pinned_version": MIHOMO_VERSION}
    version = ""
    try:
        out = subprocess.run([str(path), "-v"], capture_output=True, text=True,
                             timeout=10)
        version = (out.stdout or out.stderr).strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return {"available": False, "version": "", "path": str(path),
                "pinned_version": MIHOMO_VERSION,
                "error": "核心文件存在但无法执行，请重新安装"}
    return {"available": True, "version": version, "path": str(path),
            "pinned_version": MIHOMO_VERSION}


def _download_with_curl(url: str, proxy: str) -> bytes | None:
    """httpx 失败时的回退通道；返回 None 表示失败。"""
    cmd = ["curl", "-fsSL", "--max-time", "120"]
    if proxy:
        cmd += ["-x", proxy]
    cmd += ["-o", "-", url]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=130)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 and out.stdout else None


def _asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64",
            "aarch64": "arm64"}.get(machine)
    if system not in ("darwin", "linux") or not arch:
        raise TestError(f"当前平台不支持自动安装核心：{system}/{machine}")
    return f"mihomo-{system}-{arch}-{MIHOMO_VERSION}.gz"


def install_core(proxy: str = "") -> dict:
    """从固定版本发布页下载核心；上游未提供逐文件校验值，记录实际摘要供核对。"""
    name = _asset_name()
    url = f"{RELEASE_BASE}/{MIHOMO_VERSION}/{name}"
    target = core_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True, trust_env=False,
                          proxy=proxy or None) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            raise TestError(f"下载失败：HTTP {resp.status_code}")
        blob = resp.content
    except httpx.HTTPError as exc:
        # 部分网络环境下 Python TLS 栈被干扰而 curl 可用，回退到系统 curl
        blob = _download_with_curl(url, proxy)
        if blob is None:
            raise TestError(f"下载失败：{exc}") from exc
    try:
        binary = gzip.decompress(blob)
    except OSError as exc:
        raise TestError(f"解压失败：{exc}") from exc
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(binary)
    tmp.chmod(0o755)
    try:
        out = subprocess.run([str(tmp), "-v"], capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        tmp.unlink(missing_ok=True)
        raise TestError(f"核心无法在当前平台运行：{exc}") from exc
    first_line = (out.stdout or out.stderr).strip().splitlines()
    if not first_line or MIHOMO_VERSION.lstrip("v") not in first_line[0]:
        tmp.unlink(missing_ok=True)
        raise TestError("核心版本校验失败，已丢弃下载文件")
    tmp.replace(target)
    return {"version": first_line[0], "sha256": hashlib.sha256(binary).hexdigest()}


def validate_config(text: str, feed_placeholder: str = "https://127.0.0.1") -> tuple[bool, str]:
    """用核心执行配置检查（mihomo -t）。

    返回 (是否执行了校验, 错误信息)。核心不可用时不执行，由调用方按静态校验处理。
    产物中的 {FEED} 占位先替换为回环地址，仅用于通过解析，不发生真实请求。
    """
    status = core_status()
    if not status["available"]:
        return False, ""
    workdir = Path(tempfile.mkdtemp(prefix="mihomo-validate-", dir=config.DATA_DIR))
    try:
        cfg = workdir / "config.yaml"
        cfg.write_text(text.replace("{FEED}", feed_placeholder), encoding="utf-8")
        try:
            out = subprocess.run(
                [str(core_path()), "-d", str(workdir), "-t", "-f", str(cfg)],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return True, "核心校验超时"
        if out.returncode != 0:
            tail = (out.stderr or out.stdout).strip().splitlines()
            return True, "核心校验未通过：" + (tail[-1] if tail else "未知错误")
        return True, ""
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def filter_snapshot(snapshot_yaml: str, failed_names: set[str]) -> str:
    """从节点快照中剔除测试失败的节点，返回新的 YAML 文本。"""
    data = yaml.safe_load(snapshot_yaml)
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise TestError("快照内容不是有效的节点订阅")
    data["proxies"] = [
        p for p in data["proxies"]
        if not (isinstance(p, dict) and p.get("name") in failed_names)
    ]
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096)


def test_nodes(snapshot_yaml: str) -> dict:
    """对快照中的全部节点做连通性测试，返回每个节点的延迟或失败标记。"""
    status = core_status()
    if not status["available"]:
        raise TestError("Mihomo 核心不可用，请先在设置中安装")
    try:
        data = yaml.safe_load(snapshot_yaml)
    except yaml.YAMLError as exc:
        raise TestError(f"快照 YAML 解析失败：{exc}") from exc
    proxies = (data or {}).get("proxies")
    if not isinstance(proxies, list) or not proxies:
        raise TestError("快照中没有节点，请先抓取来源")

    controller_port = _free_port()
    mixed_port = _free_port()
    workdir = Path(tempfile.mkdtemp(prefix="mihomo-test-", dir=config.DATA_DIR))
    cfg = {
        "mixed-port": mixed_port,
        "allow-lan": False,
        "mode": "global",
        "log-level": "error",
        "external-controller": f"127.0.0.1:{controller_port}",
        "proxies": proxies,
    }
    (workdir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
    )
    proc = subprocess.Popen(
        [str(core_path()), "-d", str(workdir), "-f", str(workdir / "config.yaml")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{controller_port}"
    try:
        controller = httpx.Client(trust_env=False, timeout=DELAY_TIMEOUT_MS / 1000 + 3)
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            try:
                controller.get(f"{base}/version", timeout=1.0)
                break
            except httpx.HTTPError:
                if proc.poll() is not None:
                    controller.close()
                    raise TestError("核心启动失败，请确认节点协议与核心版本兼容")
                if time.monotonic() > deadline:
                    controller.close()
                    raise TestError("核心启动超时")
                time.sleep(0.2)

        names = [str(p.get("name")) for p in proxies
                 if isinstance(p, dict) and p.get("name")]

        def probe(name: str):
            quoted = urllib.parse.quote(name, safe="")
            try:
                resp = controller.get(
                    f"{base}/proxies/{quoted}/delay",
                    params={"timeout": DELAY_TIMEOUT_MS, "url": DELAY_URL},
                )
                if resp.status_code == 200:
                    return name, int(resp.json().get("delay", 0))
            except (httpx.HTTPError, ValueError):
                pass
            return name, -1

        results: dict[str, int] = {}
        try:
            with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
                for name, delay in pool.map(probe, names):
                    results[name] = delay
        finally:
            controller.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)

    ok = sum(1 for d in results.values() if d >= 0)
    return {
        "total": len(results),
        "ok": ok,
        "failed": len(results) - ok,
        "results": results,
    }
