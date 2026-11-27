import json
from fastapi.testclient import TestClient
from studio import api,converter as cv,compiler as cc,store as s
from studio.init import initialize

SOURCE="proxies:\n  - {name: 日本 01, type: hysteria2, server: example.org, port: 443, auth: sample-pass}\n  - {name: 香港 02, type: trojan, server: example.net, port: 443, password: dummy-secondary}\n"
def test_saved_conversion_lifecycle(tmp_path,monkeypatch):
    monkeypatch.setattr(s,"ROOT",tmp_path);monkeypatch.setattr(s,"DB",tmp_path/"db");s.init()
    with s.tx(True) as c:initialize(c,"owner","fixture-super-secret")
    with TestClient(api.app,base_url=api.ORIGIN) as h:
        h.headers["X-Studio"]="1"
        assert h.get("/api/conversions").status_code==401
        h.post("/api/login",json={"username":"owner","password":"fixture-super-secret"}).raise_for_status()
        spec={"target":"mihomo","name":"Demo","sources":"https://example.net/private-source","preset":"custom","rules":"DOMAIN-SUFFIX,example.net,DIRECT","include":"日本|香港","exclude":"香港","rename":"日本@Japan","emoji":"region"}
        monkeypatch.setattr(cv.fetch,"get",lambda u:SOURCE.encode())
        r=h.post("/api/conversions",json=spec);r.raise_for_status();meta=r.json()
        assert meta["input"]==2 and meta["output"]==1 and "private" not in meta["url"] and "sample" not in json.dumps(meta)
        token=meta["url"].split("/")[-1]
        with TestClient(api.app,base_url=api.ORIGIN) as anon:
            r=anon.get(meta["url"]);doc=cc.load(r.content)
            assert doc["proxies"][0]["name"]=="🇯🇵 Japan 01" and doc["proxies"][0]["password"]=="sample-pass" and "auth" not in doc["proxies"][0]
            assert doc["rules"]==["DOMAIN-SUFFIX,example.net,DIRECT","MATCH,出口"]
            assert anon.get(meta["url"],headers={"If-None-Match":r.headers["etag"]}).status_code==304
            assert anon.post("/api/conversions/"+token+"/remove",headers={"X-Studio":"1"},json={}).status_code==401
            with s.tx(True) as c:
                c.execute("UPDATE conversions SET built=1,attempt=1")
                assert b"private-source" not in c.execute("SELECT recipe FROM conversions").fetchone()[0]
            monkeypatch.setattr(cv.fetch,"get",lambda u:(_ for _ in ()).throw(ValueError("test")))
            cached=anon.get(meta["url"])
            assert cached.content==r.content and cached.headers["x-studio-cache"]=="stale"
            assert h.get("/api/conversions").json()[0]["failed"]
            assert h.post("/api/conversions/"+token+"/remove",json={}).is_success
            assert anon.get(meta["url"]).status_code==404
        with s.tx() as c:assert s.workspace(c)[0]==1 and c.execute("SELECT release FROM live").fetchone()[0]==1

def test_tool_rejects_unsafe_or_unusable_input(tmp_path,monkeypatch):
    import pytest
    for d in [{"sources":"http://127.0.0.1/a"},{"sources":"file:///tmp/source"},{"sources":SOURCE,"include":"["},{"sources":SOURCE,"exclude":".*"},{"sources":"proxies: []\nproxy-providers: {x: {}}"},{"sources":SOURCE,"config":"https://example.net/remote-script"}]:
        with pytest.raises(ValueError):cv.compile_recipe(cv.opts({"target":"mihomo",**d}))
    monkeypatch.setattr(cv,"sidecar",lambda p:cc.dump({"proxies":[{"name":"fixture","type":"hysteria2","server":"example.org","port":443,"password":"wrong"}]}).encode())
    with pytest.raises(ValueError,match="凭据与输入不一致"):cv.compile_recipe(cv.opts({"target":"mihomo","sources":"hysteria2://dummy@example.org:443#fixture"}))
