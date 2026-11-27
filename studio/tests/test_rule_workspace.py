import base64
import hashlib
import pytest
from fastapi.testclient import TestClient
from studio import api, compiler as cc, rule_repo as rr, rule_view, service, store as s
from studio.init import initialize

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(s,"ROOT",tmp_path);monkeypatch.setattr(s,"DB",tmp_path/"studio.sqlite3");s.init()
    with s.tx(True) as c:initialize(c,"review","fixture-pass-for-review")

def blob_sha(raw):return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()

def test_repo_review_commit_conflict_and_apply(setup,monkeypatch):
    name="sample.yaml"; document={"raw":b"payload:\n  - DST-PORT,443\n"};writes=[]
    def remote(method,path,body=None,token=""):
        assert path.startswith("/contents/rule/"+name)
        raw=document["raw"];sha=blob_sha(raw)
        if method=="GET":return {"type":"file","encoding":"base64","sha":sha,"size":len(raw),"content":base64.b64encode(raw).decode()}
        assert method=="PUT" and token=="fixture_secret_only" and body["sha"]==sha and body["branch"]=="main"
        writes.append(1);document["raw"]=base64.b64decode(body["content"]);return {"commit":{"sha":"b"*40}}
    monkeypatch.setattr(rr,"github",remote)
    with TestClient(api.app,base_url=api.ORIGIN,headers={"X-Studio":"1"}) as client:
        url="/api/rule-repo/"
        assert client.get(url+"file?name="+name).status_code==401
        assert client.post("/api/login",json={"username":"review","password":"fixture-pass-for-review"}).is_success
        source=client.get(url+"file",params={"name":name}).json()
        params={**source,"content":"payload:\n  - DST-PORT,853\n"}
        reviewed=client.post(url+"review",json=params).json()
        assert "+  - DST-PORT,853" in reviewed["diff"] and not writes
        request={**params,**reviewed,"token":"fixture_secret_only","message":"Change port"}
        assert client.post(url+"commit",json={**request,"content":"payload: [just-changed]"}).status_code==422
        assert client.post(url+"commit",json=request).is_success and writes==[1]
        assert client.post(url+"commit",json=request).status_code==422 and writes==[1]
        current=client.get(url+"file",params={"name":name}).json()
        apply={"name":name,"sha":current["sha"],"template":"platform-ios-stash","behavior":"classical","revision":1}
        assert client.post(url+"apply",json={**apply,"sha":source["sha"]}).status_code==422
        assert client.post(url+"apply",json=apply).is_success
        assert client.post(url+"apply",json=apply).status_code==422
        with s.tx(True) as c:
            rev,w=s.workspace(c);assert rev==2 and w["resources"]["sample"]["repo_sha"]==current["sha"]
            with pytest.raises(ValueError):service.edit(c,"review",rev,"resource_edit",{"name":"sample","content":"payload: [example.com]"})
            rev=service.edit(c,"review",rev,"rule_save",{"line":"RULE-SET,sample,DIRECT","templates":["platform-ios-stash"]})
            rev=service.edit(c,"review",rev,"native_rules",{"profile":"platform-ios","engine":"surge","content":"DEST-PORT,443,REJECT"})
            cc.publish(c,"review",rev)
        def fetch(engine,**extra):
            return client.get("/api/released-rules",params={"engine":engine,"profile":"platform-ios","network":"mobile",**extra})
        for engine,port,final in [("surge","DEST-PORT","FINAL"),("shadowrocket","DST-PORT","FINAL"),("stash","DST-PORT","MATCH")]:
            v=fetch(engine).json()
            assert v["lines"][-1].startswith(final+",")
            assert ("DEST-PORT,443,REJECT" in v["lines"])==(engine=="surge")
            asset=next(a for a in v["resources"] if a["name"]=="sample")
            content=fetch(engine,asset=asset["key"]).json()["lines"]
            assert any(port+",853" in l for l in content)
            if engine!="stash":assert not any("payload:" in l for l in content)
            assert fetch(engine,asset="a"*64).status_code==422
        # The public feed really serves the text shown by the admin preview.
        root=client.get("/api/subscription").json()["base"]
        doc=client.get(root+"?platform=ios&type=surge&network=mobile").text
        target=next(l.split(",")[1] for l in doc.splitlines() if l.startswith("RULE-SET,"))
        assert client.get(target).text.strip()=="DEST-PORT,853" and "DEST-PORT,443,REJECT" in doc
        assert "DEST-PORT,443,REJECT" not in client.get(root+"?platform=ios&type=shadowrocket").text
        assert "DEST-PORT,443,REJECT" not in client.get(root+"?platform=macos&type=surge").text

def test_invalid_file_and_native_rule_leave_release_untouched(setup):
    for name in ["../main.yaml","rule/a.yaml",".hidden.yaml","a.yml?ref=x","x.txt"]:
        with pytest.raises(ValueError):rr.filename(name)
    with pytest.raises(ValueError):rr.validate("payload: [")
    for engine,line in [("surge","DST-PORT,53,DIRECT"),("shadowrocket","DEST-PORT,53,DIRECT"),("surge","DEST-PORT,65536,DIRECT"),("surge","FINAL,DIRECT"),("surge","DOMAIN,example.org,Missing")]:
        with pytest.raises(ValueError):rule_view.native_lines(line,engine,{"DIRECT"})
    with s.tx() as c:
        assert c.execute("SELECT release FROM live").fetchone()[0]==1

def test_ios_excludes_desktop_conditions_without_changing_macos(setup):
    from studio import apple
    with s.tx(True) as c:
        cid=s.put_blob(c,b'payload:\n  - PROCESS-NAME,example.exe\n')
        cfg={"proxy-groups":[],"rules":["RULE-SET,desktop,REJECT","DOMAIN,example.org,DIRECT","MATCH,REJECT"],
             "rule-providers":{"desktop":{"format":"yaml","behavior":"classical","url":"studio:"+cid}}}
        for engine,platform,skipped in [("surge","ios",1),("surge","macos",0),("shadowrocket","ios",1)]:
            ent=apple.build(c,cfg,engine,platform=platform)
            assert ent["desktop_rules_skipped"]==skipped and len(ent["resources"])==1-skipped
            raw=s.read_blob(c,ent["config"]).decode()
            assert raw.index("DOMAIN,example.org,DIRECT")<raw.index("FINAL,REJECT") and ("RULE-SET" in raw)==(not skipped)
        with pytest.raises(ValueError):apple.rule("NETWORK,udp,DIRECT","shadowrocket")
        assert apple.rule("NETWORK,udp,DIRECT","surge")=="PROTOCOL,UDP,DIRECT"

def test_renderer_upgrade_checks_release_and_preserves_history(setup):
    from studio.promote_rules import promote
    with s.tx(True) as c:
        with pytest.raises(ValueError):promote(c,9,1)
        assert promote(c,1,1)==2
        with pytest.raises(ValueError):promote(c,1,1)
        assert c.execute("select count(*) from client_catalogs").fetchone()[0]==2

def test_publish_keeps_working_client_when_new_rule_cannot_translate(setup):
    with s.tx(True) as c:
        rev=service.edit(c,"review",1,"rule_save",{"line":"NETWORK,udp,DIRECT","templates":["platform-ios-stash"]})
    with pytest.raises(ValueError,match="shadowrocket"):
        with s.tx(True) as c:cc.publish(c,"review",rev)
    with s.tx() as c:
        assert c.execute("select release from live").fetchone()[0]==1 and c.execute("select count(*) from releases").fetchone()[0]==1

def test_public_repo_quota_fallback(monkeypatch):
    import gzip,io,tarfile
    raw=b"payload: [example.org]";buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode="w") as tar:
        for path in ["magic-sets-main/rule/sample.yaml","magic-sets-main/nested/secret.yaml"]:
            item=tarfile.TarInfo(path);item.size=len(raw);tar.addfile(item,io.BytesIO(raw))
    def limited(*args):raise rr.ReadUnavailable("quota")
    monkeypatch.setattr(rr,"github",limited)
    monkeypatch.setattr(rr.fetch,"get",lambda url:gzip.compress(buf.getvalue()) if "codeload.github.com" in url else raw)
    assert rr.catalog()["files"]==["sample.yaml"]
    assert rr.file("sample.yaml")["sha"]==blob_sha(raw)
