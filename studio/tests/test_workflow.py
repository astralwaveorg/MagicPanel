import hashlib
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from studio import api, store as s, compiler as cp

def sample(c):
    salt='ab'*16
    c.execute("INSERT INTO users VALUES(?,?,?)",("fixture",salt,hashlib.pbkdf2_hmac("sha256",b"fixture-login",bytes.fromhex(salt),600000).hex()))
    key=s.put_blob(c,b"payload:\n  - '+.example.com'\n")
    base={"proxy-groups":[{"type":"select","name":"Default","proxies":["DIRECT"]}],
        "proxies":[],"rule-providers":{"demo":{"type":"http","behavior":"domain","url":"studio:"+key}}}
    w={"templates":{"t":{"name":"桌面","engine":"mihomo","platform":"windows","base":base,"order":["first","last"]}},
        "devices":{"d":{"name":"测试设备","template":"t","enabled":True}},
        "rules":{"first":"RULE-SET,demo,Default","last":"MATCH,Default"},"sources":{},"resources":{"demo":{"blob":key,"behavior":"domain","format":"yaml"}}}
    c.execute("INSERT INTO draft VALUES(1,1,?)",(s.seal(s.encode(w)),))
    token=s.new_token(c,"d");cp.publish(c,"fixture",1)
    return token

def test_authenticated_edit_publish_rollback_resource(tmp_path,monkeypatch):
    monkeypatch.setattr(s,"ROOT",tmp_path);monkeypatch.setattr(s,"DB",tmp_path/"studio.sqlite3")
    s.init()
    with s.tx(True) as c:tok=sample(c)
    with TestClient(api.app,base_url="https://v2.magichub.top:8443") as client:
        assert client.get("/api/state").status_code==401
        client.headers.update({"X-Studio":"1"})
        assert client.post("/api/login",json={"username":"fixture","password":"fixture-login"}).is_success
        path=f"/feed/{tok}/config.yaml"
        old=cp.load(client.get(path).content);resource=old["rule-providers"]["demo"]["url"]
        res=client.post("/api/edit",json={"revision":1,"op":"rule_save","data":{"line":"DOMAIN,example.org,DIRECT","templates":["t"],"first":True}})
        assert res.json()=={"revision":2}
        assert cp.load(client.get(path).content)==old
        assert client.post("/api/release",json={"revision":1}).status_code==422
        assert client.post("/api/release",json={"revision":2}).json()=={"release":2}
        assert cp.load(client.get(path).content)["rules"][0]=="DOMAIN,example.org,DIRECT"
        assert client.get(resource).is_success
        assert client.post("/api/rollback",json={"release":1,"expected":2}).is_success
        assert cp.load(client.get(path).content)==old
        assert client.get("/feed/unknown/config.yaml").status_code==404
        assert client.post("/api/edit",json={"revision":2,"op":"device_rotate","data":{"id":"d"}}).is_success
        assert client.get(path).status_code==404
