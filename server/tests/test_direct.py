"""测速链路必须直连：代理变量剥离、直连自检与核心子进程环境。

背景：NAS 的 Docker 配了代理（docker.service 的 HTTP_PROXY 注入容器），
面板进程会继承这些变量；测速衡量的是"本机直连节点服务器的延迟"，
一旦被代理接管，延迟数字就失去意义。
"""
from app.services import direct
from conftest import auth_headers, setup_admin


def test_direct_env_strips_proxy_vars():
    """子进程环境必须没有代理变量，并写死 NO_PROXY=*。"""
    base = {
        "PATH": "/usr/bin",
        "HTTP_PROXY": "http://10.0.1.8:6152",
        "http_proxy": "http://10.0.1.8:6152",
        "HTTPS_PROXY": "http://10.0.1.8:6152",
        "https_proxy": "http://10.0.1.8:6152",
        "ALL_PROXY": "socks5://10.0.1.8:6153",
        "NO_PROXY": "localhost",
    }
    env = direct.direct_env(base)
    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                "ALL_PROXY"):
        assert key not in env, key
    # NO_PROXY 不继承原值，改写成通配符
    assert env["NO_PROXY"] == "*" and env["no_proxy"] == "*"
    assert env["PATH"] == "/usr/bin"


def test_check_reports_state(monkeypatch):
    """自检结果要给出状态、结论与出口信息。"""
    monkeypatch.setattr(direct, "_fetch_egress", lambda: {
        "ip": "1.2.3.4", "country": "中国", "country_code": "CN", "org": "ISP",
    })
    result = direct.check(refresh=True)
    assert result["state"] == "ok"
    assert result["egress"]["ip"] == "1.2.3.4"
    assert result["notes"]

    # 出口不在境内 → 提示可能被透明代理接管
    monkeypatch.setattr(direct, "_fetch_egress", lambda: {
        "ip": "5.6.7.8", "country": "美国", "country_code": "US", "org": "x",
    })
    result = direct.check(refresh=True)
    assert result["state"] == "risk"

    # 检测不到出口 → unknown，而不是假装正常
    monkeypatch.setattr(direct, "_fetch_egress", lambda: {})
    result = direct.check(refresh=True)
    assert result["state"] == "unknown"


def test_check_lists_env_proxies(monkeypatch):
    """环境里的代理变量要被列出来（面板不用它们，但要让人看见）。"""
    monkeypatch.setenv("HTTP_PROXY", "http://10.0.1.8:6152")
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.1.8:6152")
    monkeypatch.setattr(direct, "_fetch_egress", lambda: {
        "ip": "1.2.3.4", "country": "中国", "country_code": "CN", "org": "ISP",
    })
    result = direct.check(refresh=True)
    assert "HTTP_PROXY" in result["env_proxies"]
    assert any("HTTP_PROXY" in n for n in result["notes"])


def test_core_subprocess_gets_clean_env(monkeypatch):
    """测速核心子进程必须用剥离过代理变量的环境启动。"""
    import subprocess

    from app.services import tester

    captured = {}

    class FakeProc:
        def __init__(self):
            self.pid = 1
            self.returncode = 0

        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setenv("HTTP_PROXY", "http://10.0.1.8:6152")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(tester, "core_status",
                        lambda: {"available": True, "version": "v1.19.32"})

    # 核心接口不通时会抛错，这里只要确认 env 已经传下去
    try:
        tester.test_nodes("proxies:\n  - name: a\n    type: ss\n")
    except Exception:
        pass
    env = captured.get("env") or {}
    assert "HTTP_PROXY" not in env
    assert env.get("NO_PROXY") == "*"


def test_direct_check_api(client, monkeypatch):
    """管理端自检接口可用。"""
    monkeypatch.setattr(direct, "_fetch_egress", lambda: {
        "ip": "1.2.3.4", "country": "中国", "country_code": "CN", "org": "ISP",
    })
    csrf = setup_admin(client)
    h = auth_headers(csrf)
    r = client.get("/api/v1/direct-check", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["state"] in ("ok", "risk", "unknown")
    assert "notes" in data and "egress" in data
