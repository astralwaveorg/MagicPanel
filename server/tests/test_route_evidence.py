"""服务出口必须来自本次连接或同域响应，不能套用通用出口。"""
import httpx

from app.services.probes import detector_by_id
from app.services.probes.route_evidence import ConnectionReader, RoutedDetector, matching_chain


def test_router_connection_requires_unique_exact_match():
    source = {"network": "tcp", "host": "claude.ai", "sourceIP": "10.0.1.2",
              "sourcePort": "43210", "destinationPort": "443"}
    wanted = {"metadata": source, "chains": ["美国 NTT", "Claude"]}
    others = [{"metadata": {**source, key: value}, "chains": ["其他"]}
              for key, value in (("host", "www.perplexity.ai"), ("sourceIP", "10.0.1.8"),
                                 ("sourcePort", "43211"), ("network", "udp"))]
    assert matching_chain([wanted, *others], "claude.ai", {"10.0.1.2"}, "43210") == wanted["chains"]
    assert not matching_chain([wanted, wanted], "claude.ai", {"10.0.1.2"}, "43210")
    assert not matching_chain(others, "claude.ai", {"10.0.1.2"}, "43210")


def test_cloudflare_challenge_and_same_host_exit_remain_separate(monkeypatch):
    monkeypatch.delenv("MAGICPANEL_ROUTE_CONTROLLER", raising=False)
    called = []
    def handler(request):
        called.append(str(request.url))
        if request.url.path == "/cdn-cgi/trace":
            return httpx.Response(200, text="h=claude.ai\nip=192.0.2.8\nloc=US\n",
                                  headers={"Content-Type": "text/plain"})
        return httpx.Response(403, headers={"cf-mitigated": "challenge"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = RoutedDetector(detector_by_id("claude"), ConnectionReader()).probe(client)
    assert result.state == "unknown"
    assert result.extra["reason"] == "challenge"
    assert result.extra["route"] == {"ip": "192.0.2.8", "country": "US",
                                    "domain": "claude.ai", "source": "domain_trace"}
    assert called == ["https://claude.ai/", "https://claude.ai/cdn-cgi/trace"]


def test_panel_reports_challenge_and_does_not_reuse_legacy_cache(client, monkeypatch):
    from app.services import unlock_check
    from app.services.probes import ProbeResult
    import app.services.probes as probes
    from conftest import auth_headers, setup_admin

    headers = auth_headers(setup_admin(client))
    monkeypatch.setattr(probes, "detect_platforms", lambda **kwargs: [
        ProbeResult("claude", "unknown", 403, extra={"reason": "challenge",
            "route": {"source": "domain_trace", "ip": "192.0.2.8", "domain": "claude.ai"}})])
    monkeypatch.setattr(unlock_check, "exit_ip", lambda: {"ip": "192.0.2.15"})
    assert client.get("/api/v1/unlock/last?exit=panel", headers=headers).json() == {}
    response = client.post("/api/v1/unlock/run", headers=headers,
                           json={"exit": "panel", "ids": ["claude"]})
    assert response.status_code == 200, response.json()
    result = response.json()["results"][0]
    assert result["state"] == "unknown"
    assert result["extra"]["route"]["ip"] != response.json()["ip"]["ip"]
    assert client.get("/api/v1/unlock/last?exit=panel", headers=headers).json() == response.json()
    assert unlock_check.last_results("panel") == {}
