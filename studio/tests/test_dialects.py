import hashlib
from urllib.parse import parse_qs,urlsplit
import pytest
from fastapi.testclient import TestClient
from studio import api,apple,assistant,compiler as cc,dialects,store as s,subscription
from studio.init import initialize

NODE={"name":"fixture","server":"example.org","port":443,"type":"hysteria2"}
SECRET="sample@exact+value:END"
@pytest.mark.parametrize("src",[{"auth":SECRET},{"password":SECRET},{"auth":SECRET,"password":SECRET}])
def test_hy2_roundtrip_dialects(src):
    n={**NODE,**src,"up":"40 Mbps","down-speed":80,"server-cert-fingerprint":"AB"*32}
    for engine,expect in (("stash","auth"),("mihomo","password")):
        got,=assistant.convert(cc.dump({"proxies":[n]}),engine)
        assert {k:v for k,v in got.items() if k in ("auth","password")}=={expect:SECRET}
        assert got["up-speed" if engine=="stash" else "up"]==(40 if engine=="stash" else "40 Mbps")
        assert got["server-cert-fingerprint" if engine=="stash" else "fingerprint"]=="ab"*32
        assert ("fingerprint" in got)==(engine=="mihomo")
    assert n["server-cert-fingerprint"]=="AB"*32

@pytest.mark.parametrize("fields",[{},{"auth":" "},{"auth":123},{"auth":"a","password":SECRET},{"auth":"","password":SECRET}])
def test_bad_credentials_fail_before_release(tmp_path,monkeypatch,fields):
    monkeypatch.setattr(s,"ROOT",tmp_path);monkeypatch.setattr(s,"DB",tmp_path/"db");s.init()
    with s.tx(True) as c:
        initialize(c,"owner","fixture-super-secret")
        _,w=s.workspace(c)
        for t in w["templates"].values():t["base"]["proxies"]=[{**NODE,**fields}]
        c.execute("UPDATE draft SET revision=2, body=?",(s.encode_workspace(w),))
    api.tick()
    with s.tx() as c:
        assert c.execute("SELECT release FROM live").fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM releases").fetchone()[0]==1
        assert c.execute("SELECT failed_revision FROM automation").fetchone()[0]==2
    with pytest.raises(ValueError) as err:dialects.normalize({**NODE,**fields},"mihomo")
    assert SECRET not in str(err.value)

def test_native_resources_and_format_from_real_subscription(tmp_path,monkeypatch):
    monkeypatch.setattr(s,"ROOT",tmp_path);monkeypatch.setattr(s,"DB",tmp_path/"db");s.init()
    with s.tx(True) as c:
        initialize(c,"owner","fixture-super-secret")
        _,w=s.workspace(c);key=s.put_blob(c,b"payload: ['+.example.org', 'exact.example.net']")
        w["rules"]["first"]="RULE-SET,demo,默认出口"
        for t in w["templates"].values():
            t["base"]["rule-providers"]={"demo":{"type":"http","url":"studio:"+key,"behavior":"domain","format":"yaml"}}
            t["order"]=["first","r-final"];t["base"]["proxies"]=[{**NODE,"auth":SECRET}]
            t["base"]["proxy-groups"][0]["proxies"]=["fixture"]
        w["policies"]["default"]["order"]=["first","r-final"]
        c.execute("UPDATE draft SET revision=2,body=?",(s.encode_workspace(w),));rid=cc.publish(c,"fixture",2);token=subscription.issue(c)
    with TestClient(api.app,base_url=api.ORIGIN) as h:
        root=f"/sub/{token}"
        for eng,field in (("mihomo","password"),("stash","auth")):
            cfg=cc.load(h.get(root,params={"platform":"ios","type":eng}).content)
            assert {k:v for k,v in cfg["proxies"][0].items() if k in ("auth","password")}=={field:SECRET}
        router=h.get(root,params={"platform":"openwrt","type":"mihomo"});router.raise_for_status()
        router_cfg=cc.load(router.content)
        assert router_cfg["proxies"][0]["password"]==SECRET and "auth" not in router_cfg["proxies"][0]
        assert not ({"dns","tun","allow-lan","external-controller","mixed-port"}&router_cfg.keys())
        for eng,field in (("surge","password"),("surge5","password"),("shadowrocket","auth")):
            r=h.get(root,params={"type":eng,"platform":"ios","network":"mobile","name":"Test Config"})
            assert r.is_success and r.headers["content-type"].startswith("text/plain") and ".conf" in r.headers["content-disposition"]
            assert f"{field}={SECRET}" in r.text and "[Proxy Group]" in r.text
            assert r.text.rstrip().endswith("FINAL,默认出口")
            if eng.startswith("surge"):
                managed=r.text.splitlines()[0].split()[1]
                assert parse_qs(urlsplit(managed).query)["type"]==[eng] and h.get(managed).text==r.text
            else:assert "#!MANAGED-CONFIG" not in r.text
            uri=next(x.split(",")[1] for x in r.text.splitlines() if x.startswith("RULE-SET,"))
            rules=h.get(uri)
            assert rules.text=="DOMAIN-SUFFIX,example.org\nDOMAIN,exact.example.net\n"
            assert hashlib.sha256(rules.content).hexdigest()==uri.rsplit("/",1)[1] and f"/r/{rid}/" in uri
            assert h.get(uri.replace(token,"z"*43)).status_code==404

def test_security_options_not_silently_weakened():
    for key in ("name-cert-verify","realm-opts"):
        with pytest.raises(ValueError):apple.node({**NODE,"auth":SECRET,key:"present"},"surge")
    with pytest.raises(ValueError):dialects.normalize({**NODE,"auth":SECRET,"up-speed":4,"up":"5 Mbps"},"mihomo")

def test_hy1_and_tuic_do_not_use_hy2_aliases():
    raw={**NODE,"type":"hysteria","auth":"AAE=","up-speed":30,"down-speed":60}
    got=dialects.normalize(raw,"mihomo")
    assert got["auth"]=="AAE=" and "password" not in got and got["up"]==30
    for v,auth in ((4,{"token":"v4-fixture"}),(5,{"uuid":"fixture","password":"v5-fixture"})):
        n={**NODE,"type":"tuic",**auth}
        assert dialects.normalize(n,"stash")["version"]==v and "version" not in dialects.normalize({**n,"version":v},"mihomo")
        with pytest.raises(ValueError):dialects.normalize({**n,"version":9},"stash")
    with pytest.raises(ValueError):dialects.normalize({**NODE,"type":"tuic","token":"v4","password":"v5"},"mihomo")
    n=dialects.normalize({**NODE,"auth":SECRET,"up":"","down":""},"stash")
    assert "up-speed" not in n and "down-speed" not in n
