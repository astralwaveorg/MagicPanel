from fastapi.testclient import TestClient
from studio import api,compiler as cc,store as s,service
from studio.init import initialize

def test_single_subscription_release_and_carrier_isolation(tmp_path,monkeypatch):
    monkeypatch.setattr(s,"ROOT",tmp_path);monkeypatch.setattr(s,"DB",tmp_path/"studio.sqlite3")
    s.init()
    with s.tx(True) as c:
        initialize(c,"owner","fixture-private-secret")
        _,w=s.workspace(c)
        for t in w["templates"].values():
            t["base"]["proxies"]=[{"name":k,"type":"trojan","server":"invalid.example","port":443,"password":"fixture"} for k in ("B","A")]
            t["base"]["proxy-groups"][0]["proxies"]=["B","A"]
        c.execute("UPDATE draft SET body=?",(s.encode_workspace(w),))
        rev=1
        for key,order in (("telecom",["A","B"]),("mobile",["B","A"])):
            rev=service.edit(c,"owner",rev,"network_save",{"id":key,"name":w["networks"][key]["name"],"group":"默认出口","type":"fallback","prefer":order})
        rev=service.edit(c,"owner",rev,"network_save",{"id":"mobile","name":"中国移动","rule":"r-final","dest":"REJECT"})
        cc.publish(c,"owner",rev)
    with TestClient(api.app,base_url=api.ORIGIN) as client:
        client.headers["X-Studio"]="1"
        assert client.post("/api/login",json={"username":"owner","password":"fixture-private-secret"}).is_success
        meta=client.get("/api/subscription").json();base=meta["base"]
        assert len(meta["profiles"])==5 and len(meta["networks"])==4
        def fetch(q):
            r=client.get(base+"?"+q);assert r.is_success,r.text[:100];return cc.load(r.content)
        target="platform=ios&type=stash&network="
        for key,order,dest in (("telecom",["A","B"],"默认出口"),("mobile",["B","A"],"REJECT"),("unicom",["B","A"],"默认出口")):
            doc=fetch(target+key)
            assert doc["proxy-groups"][0]["proxies"]==order and doc["rules"]==["MATCH,"+dest]
        doc=fetch("type=mihomo&arch=win&name=AstralWindows&network=mobile&sort=true&tfo=false&scv=true")
        assert [n["name"] for n in doc["proxies"]]==["A","B"] and doc["proxy-groups"][0]["proxies"]==["B","A"]
        assert all(n["tfo"] is False and n["skip-cert-verify"] for n in doc["proxies"])
        assert set(fetch("type=mac&arch=aarch64&name=XXXMacmini&list=true"))=={"proxies"}
        assert "skip-cert-verify" not in fetch(target+"telecom")["proxies"][0]
        for q in ("type=mac&tfo=false","scv=off","platform=android&arch=mac","emoji=true","scv=false&skip-cert-verify=true","network=absent"):
            assert client.get(base+"?"+q).status_code==422
        assert client.get("/sub/"+"e"*43).status_code==404
        assert client.post("/api/subscription/rotate",json={}).is_success
        assert client.get(base).status_code==404

def test_managed_source_is_shared_between_engines(tmp_path,monkeypatch):
    from studio import sync
    monkeypatch.setattr(s,"ROOT",tmp_path);monkeypatch.setattr(s,"DB",tmp_path/"studio.sqlite3");s.init()
    with s.tx(True) as c:
        initialize(c,"owner","fixture-private-secret")
        service.edit(c,"owner",1,"source_save",{"name":"sample","url":"https://example.org/source","group":"默认出口","managed":True,"scope":"policy","template":"platform-windows-mihomo"})
        key=next(iter(s.workspace(c)[1]["sources"]))
    monkeypatch.setattr(sync.fetch,"get",lambda *a: b'proxies: [{name: fixture, type: hysteria2, server: example.org, password: abc, port: 443}]')
    assert sync.refresh("source",key,"fixture")["changed"]
    assert not sync.refresh("source",key,"fixture")["changed"]
    with s.tx() as c:
        rev,w=s.workspace(c)
        assert rev==3
        for t in w["templates"].values():
            node,=t["base"]["proxies"]
            assert node["name"]=="sample / fixture"
            assert set(node.keys())&{"auth","password"}==({"auth"} if t["engine"]=="stash" else {"password"})
