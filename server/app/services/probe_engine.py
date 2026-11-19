"""节点探测的单核心引擎：一次起 Mihomo，逐节点切换 + 探测。

为什么不用「每节点起一次核心」（旧实现）：
* 旧路径每检测一个节点就生成临时目录、起核心、等端口就绪、跑完再杀，
  实测约 7 秒/节点；199 个节点要 23 分钟，还要 199 次核心启动。
* 本模块一次起核心，把全部节点放进一个 ``select`` 组，用
  ``PUT /proxies/<组>`` 切换当前节点，本地 mixed-port 的后续请求就走新节点。
  切换成本约 0.1 秒，整批可压到分钟级。

网络纪律（2026-11-19 审计）：
* 核心进程用 ``direct_env()``：宿主的代理变量必须清空，否则节点的 CONNECT
  请求会先被宿主代理截走——测出来的是代理的延迟，不是节点的。
* 面板自身不直连目标站；所有对目标站的请求都经 mixed-port（被测节点出口）。
* DNS 不交给 Fake-IP：探测要访问真实站点，Fake-IP 会让「能否访问」失真。

切换后的探活：切换请求返回后立刻发一次轻量请求确认新节点真的接管了，
否则可能把上一个节点的残留结果算到新节点头上（端口跳跃型节点尤甚）。
"""
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

import httpx
import yaml

from .. import config

logger = logging.getLogger("magicpanel.probe_engine")

# 切换后确认节点接管用的探活目标（轻量、全球可达）
PROBE_LIVENESS_URL = "https://www.gstatic.com/generate_204"
PROBE_LIVENESS_TIMEOUT = 8.0


class EngineError(Exception):
    """探测引擎无法工作（核心起不来、配置不被接受等）。"""

    def __init__(self, message, *, index=None, types=()):
        super().__init__(message)
        self.index = index
        self.types = types


class NodeEngine:
    """一次起核心，逐节点切换并执行探测。

    用法::

        with NodeEngine(proxies) as engine:
            for name in names:
                engine.select(name)
                result = engine.probe(detector)
    """

    def __init__(self, proxies: list[dict], group_name: str = "mp-probe",
                 controller_port: int | None = None,
                 mixed_port: int | None = None):
        self.proxies = [p for p in proxies if isinstance(p, dict) and p.get("name")]
        if not self.proxies:
            raise EngineError("没有可探测的节点")
        self.group_name = group_name
        self.controller_port = controller_port or _free_port()
        self.mixed_port = mixed_port or _free_port(exclude=self.controller_port)
        self.workdir: Path | None = None
        self.proc: subprocess.Popen | None = None
        self.controller: httpx.Client | None = None
        self._log_lines: deque[str] = deque(maxlen=32)
        self._current: str = ""

    # ---------------------------------------------------------------- 生命周期
    def __enter__(self) -> "NodeEngine":
        try:
            self.start()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        self.workdir = Path(tempfile.mkdtemp(prefix="mp-probe-", dir=config.DATA_DIR))
        cfg = {
            "mixed-port": self.mixed_port,
            "allow-lan": False,
            "mode": "rule",
            "log-level": "error",
            "external-controller": f"127.0.0.1:{self.controller_port}",
            # 所有节点进一个 select 组，探测时切组即可换出口
            "proxies": self.proxies,
            "proxy-groups": [{"name": self.group_name, "type": "select",
                              "proxies": [p["name"] for p in self.proxies]}],
            "rules": [f"MATCH,{self.group_name}"],
            # DNS 交给系统解析：Fake-IP 会让「能否访问真实站点」的判定失真
            "dns": {"enable": False},
        }
        config_path = self.workdir / "config.yaml"
        with config_path.open("x", encoding="utf-8") as handle:
            config_path.chmod(0o600)
            handle.write(yaml.safe_dump(cfg, allow_unicode=True))
        from . import tester
        self.proc = subprocess.Popen(
            [str(tester.core_path()), "-d", str(self.workdir), "-f", str(config_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=tester.direct_env(), text=True, errors="replace",
        )
        threading.Thread(target=self._drain, args=(self.proc, self._log_lines),
                         daemon=True).start()
        self.controller = httpx.Client(trust_env=False, timeout=10.0)
        base = f"http://127.0.0.1:{self.controller_port}"
        deadline = time.monotonic() + 15
        while True:
            if self.proc.poll() is not None:
                index, types, _ = tester._start_failure(tuple(self._log_lines))
                raise EngineError("探测核心无法加载配置", index=index, types=types)
            try:
                if self.controller.get(f"{base}/version", timeout=1.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise EngineError("探测核心启动超时")
            time.sleep(0.2)
        # 等节点全部注册进 /proxies：抢跑时切换会 404
        expected = {p["name"] for p in self.proxies}
        have = set()
        ready_deadline = time.monotonic() + 10
        while expected and time.monotonic() < ready_deadline:
            try:
                listing = self.controller.get(f"{base}/proxies", timeout=2.0).json()
                have = set((listing.get("proxies") or {}).keys())
            except (httpx.HTTPError, ValueError, AttributeError):
                have = set()
            if expected <= have:
                break
            time.sleep(0.2)
        if expected and not expected <= have:
            raise EngineError("探测核心未加载全部节点")
        self._base = base

    def close(self) -> None:
        if self.controller is not None:
            try:
                self.controller.close()
            except Exception:
                pass
            self.controller = None
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None
        if self.workdir is not None:
            shutil.rmtree(self.workdir, ignore_errors=True)
            self.workdir = None

    @staticmethod
    def _drain(proc, sink) -> None:
        stream = getattr(proc, "stdout", None)
        if stream is None:
            return
        try:
            for line in stream:
                sink.append(line[-300:])
        except (ValueError, OSError):
            pass

    # ---------------------------------------------------------------- 切换与探测
    def select(self, name: str) -> bool:
        """把探测出口切到指定节点。返回是否切换成功。

        控制器读回选中节点后再发请求。
        """
        if self.controller is None:
            raise EngineError("探测核心未启动")
        if name == self._current:
            return True
        try:
            resp = self.controller.put(
                f"{self._base}/proxies/{self.group_name}",
                json={"name": name}, timeout=10.0)
        except httpx.HTTPError as exc:
            logger.warning("切换节点失败 %s：%s", name, exc)
            return False
        if resp.status_code >= 400:
            logger.warning("切换节点被拒 %s：HTTP %s", name, resp.status_code)
            return False
        self._current = ""
        if not self._selected(name):
            return False
        self._current = name
        return True

    def _selected(self, name: str) -> bool:
        """确认控制器读回的选中节点与本次请求一致。"""
        for _ in range(2):
            try:
                resp = self.controller.get(
                    f"{self._base}/proxies/{self.group_name}", timeout=2.0)
                if resp.status_code == 200 and resp.json().get("now") == name:
                    return True
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            time.sleep(0.4)
        return False

    def proxy_url(self) -> str:
        """给 httpx 用的本地代理地址（所有请求经被测节点出去）。"""
        return f"http://127.0.0.1:{self.mixed_port}"

    def delay_of(self, name: str, timeout_ms: int = 5000) -> int:
        """单节点延迟（毫秒）；失败返回 -1。"""
        if self.controller is None:
            return -1
        import urllib.parse
        quoted = urllib.parse.quote(name, safe="")
        try:
            resp = self.controller.get(
                f"{self._base}/proxies/{quoted}/delay",
                params={"timeout": timeout_ms, "url": PROBE_LIVENESS_URL},
                timeout=timeout_ms / 1000 + 3)
            if resp.status_code == 200:
                delay = resp.json().get("delay")
                if type(delay) is int and delay > 0:
                    return delay
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return -1

    def download_speed(self, name: str, url: str, size_bytes: int = 5 * 1024 * 1024,
                       timeout: float = 20.0) -> float:
        """下载吞吐（字节/秒）。

        经本地 mixed-port 下载固定大小文件，量字节数与耗时。
        用 ``Accept-Encoding: identity`` 避免压缩后的字节数失真。
        """
        if self.controller is None or name != self._current:
            return 0.0
        headers = {"Accept-Encoding": "identity"}
        started = time.monotonic()
        total = 0
        try:
            with httpx.Client(trust_env=False, proxy=self.proxy_url()) as client, client.stream(
                    "GET", url, headers=headers, timeout=timeout) as resp:
                if resp.status_code != 200 or resp.headers.get("content-encoding", "identity").lower() != "identity":
                    return 0.0
                for chunk in resp.iter_raw():
                    if time.monotonic() - started >= timeout:
                        return 0.0
                    total += min(len(chunk), size_bytes - total)
                    if total >= size_bytes:
                        break
        except httpx.HTTPError:
            return 0.0
        elapsed = max(time.monotonic() - started, 0.001)
        return total / elapsed if total == size_bytes else 0.0

    def probe_via_local(self, detectors, timeout: float, *, workers: int, retry: int) -> dict:
        """同一个节点的探测结束后才允许切换出口。"""
        from .probes import base as probe_base

        results = probe_base.detect_platforms(
            detectors=detectors, client_factory=probe_base.make_client_factory(self.proxy_url()),
            timeout=timeout, retry=retry, max_workers=workers)
        return {r.platform: r.to_dict() for r in results}


def _free_port(exclude: int = 0) -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        return port if port != exclude else _free_port(exclude)
