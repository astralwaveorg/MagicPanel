import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from . import compiler as cc, store as s, service

ORIGIN=os.environ.get("STUDIO_ORIGIN","https://v2.magichub.top:8443").rstrip("/")
COOKIE="studio_session"
WEB=Path(os.getenv("STUDIO_WEB",str(Path(__file__).parent/"web")))
if not WEB.exists():WEB=Path(__file__).parent/"client/dist"
attempts={}; limiter=Lock()
def tick():
    with s.tx(True) as c:
        row=c.execute("SELECT enabled,failed_revision FROM automation").fetchone()
        draft=c.execute("SELECT revision FROM draft").fetchone()
        if row["enabled"] and draft and row["failed_revision"]!=draft[0]:
            try: cc.publish(c,"自动发布",draft[0])
            except (KeyError,ValueError,TypeError):
                c.execute("UPDATE automation SET failed_revision=?,error='候选校验失败，请检查发布预览'",(draft[0],))
            else:c.execute("UPDATE automation SET failed_revision=NULL,error=''")
async def worker():
    while True:
        await asyncio.sleep(35)
        try:
            from .sync import due
            await asyncio.to_thread(due)
            await asyncio.to_thread(tick)
            from .maintenance import backup
            await asyncio.to_thread(backup)
        except Exception:
            import logging
            logging.getLogger(__name__).error("自动任务未完成，稍后重试")
@asynccontextmanager
async def lifespan(app):
    s.init(); task=asyncio.create_task(worker())
    try:yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):await task
app=FastAPI(title="MagicPanel Studio",docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
@app.middleware("http")
async def protect(req,call):
    if req.method not in ("GET","HEAD","OPTIONS"):
        if req.headers.get("origin") not in (None,ORIGIN) or req.headers.get("x-studio")!="1":
            return JSONResponse({"detail":"请求来源无效"},403)
        if int(req.headers.get("content-length") or 0)>4_000_000:
            return JSONResponse({"detail":"请求过大"},413)
    resp=await call(req)
    resp.headers["Cache-Control"]="no-store"
    resp.headers["X-Content-Type-Options"]="nosniff"
    resp.headers["Referrer-Policy"]="no-referrer"
    resp.headers["Content-Security-Policy"]="default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
    return resp
@app.exception_handler(ValueError)
async def value_error(req,e): return JSONResponse({"detail":str(e)[:300]},422)
@app.exception_handler(KeyError)
async def key_error(req,e):return JSONResponse({"detail":"缺少字段或引用记录不存在"},422)
def actor(req:Request):
    token=req.cookies.get(COOKIE,"")
    with s.tx() as c:
        row=c.execute("SELECT user FROM sessions WHERE digest=? AND expires>?",(s.digest(token.encode()),time.time())).fetchone()
    if not row:raise HTTPException(401,"请登录")
    return row[0]
@app.get("/healthz")
def health():
    with s.tx() as c:ready=c.execute("SELECT release FROM live").fetchone()
    return JSONResponse({"ready":bool(ready),"service":"studio"},200 if ready else 503)
@app.post("/api/login")
def login(p:dict,req:Request):
    user=str(p.get("username",""))[:160]; pw=str(p.get("password",""))[:4096]
    ip=req.client.host if req.client else "unknown"
    now=time.time()
    with limiter:
        for k in list(attempts):
            if attempts[k] and attempts[k][-1]<now-300: del attempts[k]
        for k in (("ip",ip),("user",user)):
            q=attempts.setdefault(k,deque(maxlen=15))
            if len([x for x in q if x>now-300])>=12:raise HTTPException(429,"稍后再试")
        for k in (("ip",ip),("user",user)):attempts[k].append(now)
    with s.tx() as c: row=c.execute("SELECT salt,verifier FROM users WHERE name=?",(user,)).fetchone()
    test=hashlib.pbkdf2_hmac("sha256",pw.encode(),bytes.fromhex(row[0] if row else "0"*32),600000).hex()
    if not row or not hmac.compare_digest(row[1],test):raise HTTPException(401,"账号或密码不正确")
    tok=secrets.token_urlsafe(40)
    with s.tx(True) as c:
        c.execute("DELETE FROM sessions WHERE expires<=?",(now,))
        c.execute("INSERT INTO sessions VALUES(?,?,?)",(s.digest(tok.encode()),user,int(now)+43200))
    resp=JSONResponse({"user":user})
    resp.set_cookie(COOKIE,tok,secure=ORIGIN.startswith("https:"),httponly=True,samesite="strict",max_age=43200)
    return resp
@app.post("/api/logout")
def logout(req:Request,user=Depends(actor)):
    with s.tx(True) as c:c.execute("DELETE FROM sessions WHERE digest=?",(s.digest(req.cookies[COOKIE].encode()),))
    resp=JSONResponse({});resp.delete_cookie(COOKIE);return resp
@app.get("/api/state")
def state(user=Depends(actor)):
    with s.tx() as c:return dict(user=user,**service.summary(c))
@app.get("/api/templates/{tid}")
def template(tid:str,network:str="default",user=Depends(actor)):
    from .routing import effective
    with s.tx() as c:
        _,w=s.workspace(c)
        return service.template_detail(effective(w,w["templates"][tid],network))
@app.get("/api/resources/{name}")
def resource(name:str,user=Depends(actor)):
    with s.tx() as c:
        item=s.workspace(c)[1]["resources"][name]
        return {"content":s.read_blob(c,item["blob"]).decode() if item["format"]=="yaml" else None}
@app.post("/api/edit")
def edit(body:dict,user=Depends(actor)):
    with s.tx(True) as c:return {"revision":service.edit(c,user,body["revision"],body["op"],body["data"])}
@app.post("/api/release")
def release(body:dict,user=Depends(actor)):
    with s.tx(True) as c:return {"release":cc.publish(c,user,body["revision"])}
@app.post("/api/automation")
def automation(body:dict,user=Depends(actor)):
    with s.tx(True) as c:
        c.execute("UPDATE automation SET enabled=?,failed_revision=NULL,error=''",(int(bool(body["enabled"])),));s.event(c,user,"更新自动发布")
    return {"ok":True}
@app.post("/api/rollback")
def rollback(body:dict,user=Depends(actor)):
    with s.tx(True) as c:
        rid=int(body["release"])
        live=c.execute("SELECT release FROM live").fetchone()[0]
        if body.get("expected")!=live:raise ValueError("发布已更新，请刷新")
        if not c.execute("SELECT 1 FROM releases WHERE id=?",(rid,)).fetchone():raise ValueError("版本不存在")
        if c.execute("SELECT 1 FROM catalogs").fetchone() and not c.execute("SELECT 1 FROM catalogs WHERE release=?",(rid,)).fetchone():raise ValueError("此旧版没有统一订阅产物，不能在线回滚")
        c.execute("UPDATE live SET release=?",(rid,));c.execute("UPDATE automation SET enabled=0")
        s.event(c,user,f"回滚至 #{rid}，暂停自动发布")
    return {"release":rid}
@app.get("/api/devices/{did}/link")
def link(did:str,user=Depends(actor)):
    with s.tx() as c:r=c.execute("SELECT token FROM devices WHERE id=?",(did,)).fetchone()
    if not r:raise HTTPException(404)
    return {"url":ORIGIN+"/feed/"+s.unseal(r[0]).decode()+"/config.yaml"}
def feed_entry(c,token,release=None):
    d=c.execute("SELECT id FROM devices WHERE digest=?",(s.digest(token.encode()),)).fetchone()
    if not d:raise HTTPException(404)
    if not s.workspace(c)[1]["devices"].get(d[0],{}).get("enabled"):raise HTTPException(404)
    if release is None: row=c.execute("SELECT r.id,r.manifest FROM releases r JOIN live l ON l.release=r.id").fetchone()
    else:row=c.execute("SELECT id,manifest FROM releases WHERE id=?",(release,)).fetchone()
    if not row:raise HTTPException(404)
    f=json.loads(s.unseal(row[1])).get(d[0])
    if not f:raise HTTPException(404)
    return row[0],f
def raw_response(req,raw,mime):
    tag='"'+s.digest(raw)+'"'
    if req.headers.get("if-none-match")==tag:return Response(status_code=304,headers={"ETag":tag})
    return Response(b"" if req.method=="HEAD" else raw,media_type=mime,headers={"ETag":tag})
@app.api_route("/feed/{token}/config.yaml",methods=["GET","HEAD"])
def feed(token:str,req:Request):
    with s.tx() as c:
        rev,f=feed_entry(c,token)
        raw=cc.materialize(s.read_blob(c,f["config"]),ORIGIN+"/feed/"+token,rev)
    return raw_response(req,raw,"text/yaml")
@app.api_route("/feed/{token}/r/{rev}/{key}",methods=["GET","HEAD"])
def feed_resource(token:str,rev:int,key:str,req:Request):
    with s.tx() as c:
        _,f=feed_entry(c,token,rev)
        if key not in f["resources"]:raise HTTPException(404)
        raw=s.read_blob(c,key)
    return raw_response(req,raw,"application/octet-stream")
@app.get("/")
def index():return FileResponse(WEB/"index.html")
app.mount("/assets",StaticFiles(directory=WEB/"assets",check_dir=False),name="assets")

from . import assistant as ai
@app.post("/api/assistant")
def assistance(body:dict,user=Depends(actor)):
    with s.tx() as c:rev,w=s.workspace(c)
    return {"revision":rev,**ai.proposal(body["mode"],body.get("text",""),w,body["template"])}
@app.post("/api/node-preview")
def node_preview(body:dict,user=Depends(actor)):
    with s.tx() as c:rev,w=s.workspace(c)
    if body.get("scope")=="policy":
        pid=w["templates"][body["template"]]["policy"]
        engines={t["engine"] for t in w["templates"].values() if t["policy"]==pid}
        variants={eng:ai.convert(body["text"],eng) for eng in engines}
        return {"revision":rev,"summary":f"为方案的 {len(engines)} 种引擎添加节点到 "+body["group"],"op":"policy_nodes","data":{"policy":pid,"group":body["group"],"variants":variants}}
    nodes=ai.convert(body["text"],w["templates"][body["template"]]["engine"])
    return {"revision":rev,"summary":f"识别到 {len(nodes)} 个节点","op":"node_batch","data":{"template":body["template"],"group":body["group"],"nodes":nodes}}
@app.get("/api/preview/{tid}")
def preview(tid:str,network:str="default",user=Depends(actor)):
    from .routing import effective
    with s.tx() as c:
        rev,w=s.workspace(c); t=effective(w,w["templates"][tid],network); cfg,assets=cc.compile_template(w,t)
        line_count=len(cfg["rules"]); old=None
        d=next((k for k,v in w["devices"].items() if v["template"]==tid and v.get("network","default")==network),None)
        live=c.execute("SELECT manifest FROM releases JOIN live ON live.release=releases.id").fetchone()
        if live and d:
            ent=json.loads(s.unseal(live[0])).get(d)
            if ent:old=cc.load(s.read_blob(c,ent["config"]))
        before=(old or {}).get("rules",[]); after=cfg["rules"]
        return {"revision":rev,"rules":line_count,"resources":len(assets),"nodes":len(cfg.get("proxies",[])),
                "sections":[k for k in set(cfg)|set(old or {}) if cfg.get(k)!=(old or {}).get(k)],
                "added":[v for v in after if v not in before],"removed":[v for v in before if v not in after],
                "order_changed":before!=after}

@app.post("/api/refresh")
def refresh_source(body:dict,user=Depends(actor)):
    from .sync import refresh
    if body["kind"] not in ("source","resource"):raise ValueError("未知来源类型")
    return refresh(body["kind"],body["key"],user)

@app.get("/api/checks")
def checks(user=Depends(actor)):
    with s.tx() as c:return [dict(r) for r in c.execute("SELECT * FROM checks ORDER BY at DESC")]

@app.get("/api/templates/{tid}/yaml")
def template_yaml(tid:str,network:str="default",user=Depends(actor)):
    from .routing import effective
    with s.tx() as c:
        _,w=s.workspace(c);cfg,_=cc.compile_template(w,effective(w,w["templates"][tid],network))
        return {"yaml":cc.dump(cfg)}

from . import subscription as subs
@app.get("/api/subscription")
def subscription_info(user=Depends(actor)):
    with s.tx(True) as c:
        key=subs.issue(c);_,cat=subs.catalog(c,key)
        return {"base":ORIGIN+"/sub/"+key,"profiles":cat["profiles"],"networks":cat["networks"]}
@app.post("/api/subscription/rotate")
def subscription_rotate(user=Depends(actor)):
    with s.tx(True) as c:
        subs.issue(c,rotate=True);s.event(c,user,"轮换统一订阅密钥")
    return {"ok":True}
@app.api_route("/sub/{token}",methods=["GET","HEAD"])
def subscription_config(token:str,req:Request):
    with s.tx() as c:
        rid,cat=subs.catalog(c,token)
        entry,opts,name=subs.options(req.query_params.multi_items(),cat)
        raw=subs.render(s.read_blob(c,entry["config"]),ORIGIN+"/sub/"+token,rid,opts)
    resp=raw_response(req,raw,"text/yaml")
    resp.headers["Content-Disposition"]=subs.disposition(name)
    resp.headers["X-Studio-Release"]=str(rid)
    return resp
@app.api_route("/sub/{token}/r/{rid}/{key}",methods=["GET","HEAD"])
def subscription_resource(token:str,rid:int,key:str,req:Request):
    with s.tx() as c:
        _,cat=subs.catalog(c,token,rid)
        if not any(key in e["resources"] for plans in cat["targets"].values() for e in plans.values()):raise HTTPException(404)
        raw=s.read_blob(c,key)
    return raw_response(req,raw,"application/octet-stream")
