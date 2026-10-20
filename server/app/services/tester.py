"""节点连通性测试：调用固定版本的 Mihomo 核心，与 Clash 系客户端同机制。

原理：以节点集合生成临时配置启动本地核心，经其 external-controller
逐个发起 delay 测试（通过节点请求 generate_204）。它衡量的是从本服务器
所在网络出发的连通性与延迟，不等于带宽、解锁能力，也不代表客户端侧结果。
UDP 行为未单独验证。
"""
import gzip
import hashlib
import platform
import re
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

# 兜底版本：无法解析最新发布版本时使用
MIHOMO_FALLBACK_VERSION = "v1.19.32"
RELEASE_BASE = "https://github.com/MetaCubeX/mihomo/releases/download"
RELEASE_LATEST = "https://github.com/MetaCubeX/mihomo/releases/latest"
DELAY_URL = "https://www.gstatic.com/generate_204"
DELAY_TIMEOUT_MS = 5000
CONCURRENCY = 16
STARTUP_TIMEOUT = 8.0
UPLOAD_MAX_BYTES = 100 * 1024 * 1024
EXTRACT_MAX_BYTES = 300 * 1024 * 1024


class TestError(Exception):
    pass


def core_path() -> Path:
    return config.DATA_DIR / "bin" / "mihomo"


def core_status() -> dict:
    path = core_path()
    base = {"path": str(path),
            "platform": f"{platform.system().lower()}/{platform.machine().lower()}"}
    try:
        base["asset_hint"] = _asset_name("<版本>")
    except TestError:
        base["asset_hint"] = ""
    if not path.exists():
        return {"available": False, "version": "", **base}
    version = ""
    try:
        out = subprocess.run([str(path), "-v"], capture_output=True, text=True,
                             timeout=10)
        version = (out.stdout or out.stderr).strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return {"available": False, "version": "", **base,
                "error": "核心文件存在但无法执行，请重新安装"}
    return {"available": True, "version": version, **base}


def resolve_latest_version(proxy: str = "") -> str:
    """解析 Mihomo 最新发布版本；解析失败回退到内置版本。

    走 releases/latest 的 302 重定向取 tag，不占 GitHub API 配额。
    """
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, trust_env=False,
                          proxy=proxy or None) as client:
            resp = client.get(RELEASE_LATEST)
        tag = resp.url.path.rstrip("/").rsplit("/", 1)[-1]
        if re.match(r"^v?\d+\.\d+\.\d+", tag):
            return tag if tag.startswith("v") else f"v{tag}"
    except (httpx.HTTPError, ValueError, IndexError):
        pass
    return MIHOMO_FALLBACK_VERSION


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


def _asset_name(version: str) -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64",
            "aarch64": "arm64"}.get(machine)
    if system not in ("darwin", "linux") or not arch:
        raise TestError(f"当前平台不支持自动安装核心：{system}/{machine}")
    # amd64 不带后缀的发布包按 GOAMD64=v3 构建（需 AVX2，低功耗 NAS CPU 无法运行）；
    # 固定选 v1 基准变体，兼容性最好，拨测场景对指令集不敏感
    if arch == "amd64":
        arch = "amd64-v1"
    return f"mihomo-{system}-{arch}-{version}.gz"


def install_core(proxy: str = "") -> dict:
    """下载最新发布版本的核心；上游未提供逐文件校验值，记录实际摘要供核对。"""
    version = resolve_latest_version(proxy)
    name = _asset_name(version)
    url = f"{RELEASE_BASE}/{version}/{name}"
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
    return _verify_and_replace(binary, require_version=version)


def _verify_and_replace(binary: bytes, require_version: str = "") -> dict:
    """执行 -v 校验后原子替换核心；require_version 非空时要求版本一致。"""
    target = core_path()
    target.parent.mkdir(parents=True, exist_ok=True)
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
    if not first_line or "mihomo" not in first_line[0].lower():
        tmp.unlink(missing_ok=True)
        raise TestError("文件可执行但不是 Mihomo 核心，已丢弃")
    if require_version and require_version.lstrip("v") not in first_line[0]:
        tmp.unlink(missing_ok=True)
        raise TestError("核心版本校验失败，已丢弃下载文件")
    tmp.replace(target)
    return {"version": first_line[0], "sha256": hashlib.sha256(binary).hexdigest()}


def _looks_executable(data: bytes) -> bool:
    """常见可执行格式魔数：ELF / Mach-O（含通用二进制）/ PE / 脚本。"""
    return data.startswith((
        b"\x7fELF",
        b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",  # Mach-O 64 位两种字节序
        b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",  # Mach-O 32 位
        b"\xca\xfe\xba\xbe",                       # Mach-O 通用二进制
        b"MZ", b"#!",
    ))


def _extract_upload(blob: bytes) -> bytes:
    """识别上传格式并取出核心二进制：gzip 单文件 / zip 内的 mihomo 条目 / 裸二进制。"""
    if blob.startswith(b"\x1f\x8b"):
        try:
            data = gzip.decompress(blob)
        except OSError as exc:
            raise TestError(f"gzip 解压失败：{exc}") from exc
    elif blob.startswith(b"PK\x03\x04"):
        import io
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                candidates = [
                    i for i in zf.infolist()
                    if not i.is_dir()
                    and Path(i.filename).name.lower().startswith("mihomo")
                ]
                if not candidates:
                    raise TestError("zip 中没有找到 mihomo 可执行文件")
                entry = max(candidates, key=lambda i: i.file_size)
                if entry.file_size > EXTRACT_MAX_BYTES:
                    raise TestError("解压后的核心超过 300 MB，已拒绝")
                data = zf.read(entry)
        except zipfile.BadZipFile as exc:
            raise TestError(f"zip 解压失败：{exc}") from exc
    else:
        data = blob
    if len(data) > EXTRACT_MAX_BYTES:
        raise TestError("解压后的核心超过 300 MB，已拒绝")
    if not _looks_executable(data):
        raise TestError("文件不是可执行的核心程序（支持 .gz / .zip / 裸二进制）")
    return data


def install_core_from_upload(blob: bytes) -> dict:
    """本地上传安装 / 更新核心：自动解压、执行校验后替换。版本由上传文件决定。"""
    if not blob or len(blob) > UPLOAD_MAX_BYTES:
        raise TestError("上传文件需为 100 MB 以内")
    return _verify_and_replace(_extract_upload(blob))


# 核心校验使用固定工作目录：Geo 数据一旦下载成功即可长期复用，
# 不会每次校验都重新下载（重复下载既慢又可能因网络不可达而挂起）。
VALIDATE_WORKDIR = config.DATA_DIR / "core-work"

# 配置里出现这些引用时，核心需要对应的 Geo 数据文件
GEO_FILES = (
    ("geosite:", "geosite.dat", "GeoSite.dat"),
    ("geoip:", "geoip.dat", "GeoIP.dat"),
    ("mmdb", "country.mmdb", "Country.mmdb"),
)


def missing_geo_file(text: str) -> str:
    """返回配置所需但本地缺失的 Geo 数据文件名；都不缺时返回空串。"""
    workdir = VALIDATE_WORKDIR
    existing = {p.name.lower() for p in workdir.iterdir()} if workdir.exists() else set()
    for marker, filename, label in GEO_FILES:
        if marker in text and filename.lower() not in existing:
            return label
    return ""


def validate_config(text: str, feed_placeholder: str = "https://127.0.0.1") -> tuple[bool, str]:
    """用核心执行配置检查（mihomo -t）。

    返回 (是否执行了校验, 错误信息)。核心不可用时不执行，由调用方按静态校验处理。
    产物中的 {FEED} 占位先替换为回环地址，仅用于通过解析，不发生真实请求。
    """
    status = core_status()
    if not status["available"]:
        return False, ""
    missing = missing_geo_file(text)
    if missing:
        # 缺 Geo 数据时核心会尝试联网下载，境内常常下载不动并挂到超时；
        # 这里提前给出可执行的提示，而不是干等超时。
        return True, (f"核心校验缺少 {missing}（配置里用到了 geosite:/geoip: 等引用），"
                      "请把该数据文件放到 data/core-work/ 后重试，"
                      "或把这些引用改成显式域名")
    VALIDATE_WORKDIR.mkdir(parents=True, exist_ok=True)
    cfg = VALIDATE_WORKDIR / "config.yaml"
    try:
        cfg.write_text(text.replace("{FEED}", feed_placeholder), encoding="utf-8")
        try:
            out = subprocess.run(
                [str(core_path()), "-d", str(VALIDATE_WORKDIR), "-t", "-f", str(cfg)],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return True, "核心校验超时"
        if out.returncode != 0:
            tail = (out.stderr or out.stdout).strip().splitlines()
            return True, "核心校验未通过：" + (tail[-1] if tail else "未知错误")
        return True, ""
    finally:
        try:
            cfg.unlink(missing_ok=True)
        except OSError:
            pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def filter_snapshot(snapshot_yaml: str, failed_names: set[str]) -> str:
    """从节点快照中剔除测试失败的节点，返回新的 YAML 文本。"""
    try:
        data = yaml.safe_load(snapshot_yaml)
    except yaml.YAMLError as exc:
        raise TestError(f"快照 YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise TestError("快照内容不是有效的节点订阅")
    data["proxies"] = [
        p for p in data["proxies"]
        if not (isinstance(p, dict) and p.get("name") in failed_names)
    ]
    try:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096)
    except yaml.YAMLError as exc:
        raise TestError(f"快照序列化失败：{exc}") from exc


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
