"""Authenticated conversion recipes. The private sidecar only sees bounded inline node data."""
import base64
import ipaddress
import json
import os
import re
import secrets
import threading
import time
import zlib
from collections import Counter
from urllib.parse import quote, unquote

import httpx
import re2
import yaml
from fastapi import HTTPException
from . import apple, compiler as cc, fetch, store as s, subscription
from .dialects import hy2_secret, normalize

NATIVE={"mihomo","stash","surge","surge5","shadowrocket"}
OTHER={"singbox":"json","quanx":"conf","loon":"conf","surfboard":"conf","mixed":"txt","shadowrocket-nodes":"txt","v2rayn":"txt","v2rayng":"txt","ss":"txt","trojan":"txt","vless":"txt","hysteria2":"txt"}
SCHEMES={"ss","ssr","vmess","vless","trojan","hysteria2","hy2","hysteria","tuic","anytls","socks5","wireguard"}
LIMIT=500_000
WORK=threading.BoundedSemaphore(2)
PUBLIC_TEMPLATE="https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/a7bdd9c97c3c4a1d01a7259bba7c23c275794cc7/Clash/config/ACL4SSR_Online.ini"
STATES={"acl":"ACL4SSR","manual":"手动选择","auto":"自动测速","custom":"自定义规则"}
REGIONS=[("🇭🇰","香港|Hong Kong"),("🇹🇼","台湾|Taiwan"),("🇯🇵","日本|Japan"),("🇸🇬","新加坡|Singapore"),("🇺🇸","美国|United States"),("🇰🇷","韩国|Korea"),("🇬🇧","英国|United Kingdom"),("🇩🇪","德国|Germany")]
NAME=re.compile(r"[\w .()（）-]{1,64}")
EMOJI=re.compile(r"^[\U0001f1e6-\U0001f1ff]{2}\s*")
DDL="""CREATE TABLE IF NOT EXISTS conversions(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, secret BLOB NOT NULL, recipe BLOB NOT NULL,
 body BLOB NOT NULL, summary BLOB NOT NULL, built INTEGER NOT NULL, attempt INTEGER NOT NULL,
 failed INTEGER NOT NULL DEFAULT 0)"""
def opts(data):
    if not isinstance(data,dict) or set(data)-{"sources","target","name","preset","rules","include","exclude","rename","emoji","sort","list","scv","tfo"}:raise ValueError("转换选项无法识别")
    d=dict(data);target=d.get("target")
    if target not in NATIVE|set(OTHER):raise ValueError("目标格式无效")
    for key,limit,default in (("sources",LIMIT,""),("name",64,"转换订阅"),("rules",12000,""),("include",150,""),("exclude",150,""),("rename",180,""),("emoji",12,"keep"),("preset",12,"manual")):
        v=d.get(key,default)
        if not isinstance(v,str) or len(v)>limit:raise ValueError("输入过长或格式无效")
        d[key]=v.strip()
    if not d["sources"] or not NAME.fullmatch(d["name"]) or d["name"] in (".",".."):raise ValueError("请填写来源和有效的配置名称")
    if d["preset"] not in STATES or d["emoji"] not in ("keep","region","remove"):raise ValueError("模板或名称选项无效")
    if d["preset"]!="manual" and target not in NATIVE:raise ValueError("此格式使用转换器自带的模板")
    if d["preset"]=="acl" and (target!="mihomo" or d.get("list")):raise ValueError("公共分流模板用于 Mihomo 完整配置")
    for k in ("sort","list","scv","tfo"):
        if k in d and type(d[k]) is not bool:raise ValueError("开关格式无效")
    if d.get("list") and target not in ("mihomo","stash"):raise ValueError("此格式不支持 YAML 节点清单")
    if "tfo" in d and target!="mihomo" or "scv" in d and target not in ("mihomo","stash"):raise ValueError("此格式不支持指定的连接选项")
    return d

def sidecar(params):
    url=os.environ.get("STUDIO_CONVERTER","http://subconverter-extended:25500")+"/sub"
    if len(str(httpx.QueryParams(params)))>780000:raise ValueError("节点数据过大，请分开转换")
    try:
        with httpx.Client(timeout=httpx.Timeout(32,connect=3),trust_env=False,follow_redirects=False) as h, h.stream("GET",url,params=params) as r:
            if r.status_code!=200:raise ValueError("转换器未能生成此格式，请检查节点协议和数量")
            buf=bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf)>5_000_000:raise ValueError("转换结果过大")
            if not buf:raise ValueError("转换结果为空")
            return bytes(buf)
    except httpx.HTTPError:raise ValueError("内网转换器暂时不可用") from None

def get_nodes(text):
    nodes=[];uris=[];size=0;remote=0
    def add(data,allow_remote=False):
        nonlocal remote,size
        if not allow_remote:
            size+=len(data.encode())
            if size>LIMIT:raise ValueError("订阅展开后过大，请分开转换")
        if data.lstrip().startswith(("proxies:","- ","{","[")) or re.search(r"(?m)^proxies:\s*",data):
            try:
                if any(isinstance(t,(yaml.tokens.AliasToken,yaml.tokens.AnchorToken)) for t in yaml.scan(data,Loader=cc.LOAD)):raise ValueError("转换输入不支持 YAML 锚点")
                doc=cc.load(data)
            except yaml.YAMLError:raise ValueError("节点 YAML 格式无效") from None
            if isinstance(doc,dict) and doc.get("proxy-providers"):raise ValueError("来源含远程节点提供者，请直接添加其原始订阅")
            arr=doc.get("proxies") if isinstance(doc,dict) else doc
            if not isinstance(arr,list) or not arr:raise ValueError("YAML 中没有可转换节点")
            nodes.extend(arr);return
        for line in data.splitlines():
            u=line.strip()
            if not u or u.startswith("#"):continue
            if allow_remote and u.startswith("https://"):
                remote+=1
                if remote>8:raise ValueError("每次最多合并 8 个 HTTPS 订阅")
                try:payload=fetch.node_text(fetch.get(u))
                except Exception:raise ValueError("无法读取公开 HTTPS 来源，请检查地址或改为粘贴节点") from None
                add(payload)
            elif u.partition("://")[0].lower() in SCHEMES and "://" in u and "|" not in u and len(u)<16000:uris.append(u)
            else:raise ValueError("请输入 HTTPS 订阅、节点链接或含 proxies 的 YAML，每个链接单独一行")
    add(text,True)
    if len(uris)+len(nodes)>2500:raise ValueError("每次最多转换 2500 个节点")
    for i in range(0,len(uris),80):
        batch=uris[i:i+80]
        out=cc.load(sidecar({"target":"clash","list":"true","emoji":"false","url":"|".join(batch)}))
        group=out.get("proxies",[]) if isinstance(out,dict) else []
        if len(group)!=len(batch):raise ValueError("部分输入未被解析，请按协议分批检查")
        expected=Counter(unquote(u.split("://",1)[1].split("@",1)[0]) for u in batch if u.partition("://")[0].lower() in ("hy2","hysteria2"))
        actual=Counter(hy2_secret(n) for n in group if n.get("type") in ("hysteria2","hy2"))
        if expected!=actual:raise ValueError("Hysteria2 解析后的凭据与输入不一致")
        nodes.extend(group)
    if any(not isinstance(n,dict) or not isinstance(n.get("name"),str) or not n["name"].strip() or not n.get("type") or not n.get("server") or not n.get("port") for n in nodes):raise ValueError("节点缺少名称、协议、地址或端口")
    return nodes

def filtered(nodes,d):
    def pattern(v):
        if not v:return None
        try:
            o=re2.Options();o.log_errors=False
            return re2.compile(v,options=o)
        except re2.error:raise ValueError("筛选或重命名的正则表达式无效") from None
    inc,exc=pattern(d["include"]),pattern(d["exclude"]);rename=None;replacement=""
    if d["rename"]:
        a,sep,replacement=d["rename"].partition("@")
        if not sep or not a:raise ValueError("重命名格式为：正则表达式@新文字")
        rename=pattern(a)
    result=[];seen=set()
    for source in nodes:
        n=dict(source);name=n["name"]
        if inc and not inc.search(name) or exc and exc.search(name):continue
        if rename:name=rename.sub(lambda _:replacement,name)
        if d["emoji"]!="keep":
            old=EMOJI.match(name);name=EMOJI.sub("",name)
            if d["emoji"]=="region":
                flag=next((f for f,p in REGIONS if re.search(p,name,re.I)),old[0].strip() if old else "")
                if flag:name=flag+" "+name
        if not name.strip() or len(name)>180 or any(ord(c)<32 for c in name):raise ValueError("节点名称为空、过长或包含控制字符")
        base=name;num=2
        while name in seen or name.upper() in {"出口","DIRECT","REJECT","GLOBAL","PASS","COMPATIBLE","REJECT-DROP"}:
            name=f"{base} ({num})";num+=1
        n["name"]=name;seen.add(name);result.append(n)
    if not result:raise ValueError("没有符合条件的节点")
    if d.get("sort"):result.sort(key=lambda n:n["name"].casefold())
    return result

def rules(d):
    lines=[]
    if d["preset"]=="custom":
        for line in d["rules"].splitlines():
            line=line.strip()
            if not line or line.startswith("#"):continue
            v=[p.strip() for p in line.split(",")]
            if len(v)!=3 or v[0] not in ("DOMAIN","DOMAIN-SUFFIX","DOMAIN-KEYWORD","IP-CIDR","IP-CIDR6") or v[2] not in ("出口","DIRECT","REJECT"):raise ValueError("规则需包含匹配方式、匹配值和去向")
            if v[0].startswith("IP-"):
                try:
                    if ipaddress.ip_network(v[1],strict=False).version!=(6 if v[0]=="IP-CIDR6" else 4):raise ValueError
                except ValueError:raise ValueError("规则的网段无效") from None
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{1,253}",v[1]):raise ValueError("规则的域名或关键词无效")
            lines.append(",".join(v))
        if not lines:raise ValueError("请填写自定义规则")
    return [*lines,"MATCH,出口"]

def public_routing(nodes):
    # Only names participate in group selection. Never send original secrets to a template.
    tags=["trojan://dummy-template@example.org:"+str(10000+i)+"#"+quote(n["name"],safe="") for i,n in enumerate(nodes)]
    doc=cc.load(sidecar({"target":"clash","url":"|".join(tags),"config":PUBLIC_TEMPLATE,"expand":"true","emoji":"false","insert":"false"}))
    names={n["name"] for n in nodes}
    if not isinstance(doc,dict) or {n["name"] for n in doc.get("proxies",[])}!=names or doc.get("rule-providers") or doc.get("proxy-providers"):
        raise ValueError("公共模板未能保留节点名称或展开规则")
    groups=doc.get("proxy-groups");lines=doc.get("rules")
    if not groups or not lines or not lines[-1].startswith("MATCH,"):raise ValueError("公共模板缺少策略组或兜底规则")
    dest=names|{g["name"] for g in groups}|cc.BUILTINS
    if any(n not in dest for g in groups for n in g.get("proxies",[])) or any(cc.rule_target(l) not in dest for l in lines):
        raise ValueError("公共模板引用了不存在的节点或策略组")
    return {"proxy-groups":groups,"rules":lines}

def build(d):
    source=get_nodes(d["sources"]);nodes=filtered(source,d);kind=d["target"];info={"input":len(source),"selected":len(nodes)}
    if kind in NATIVE:
        eng="mihomo" if kind=="mihomo" else "stash"
        nodes=[normalize(n,eng) for n in nodes]
        g={"name":"出口","type":"select","proxies":[n["name"] for n in nodes]}
        if d["preset"]=="auto":g.update(type="url-test",interval=300,url="https://www.gstatic.com/generate_204")
        cfg={"mode":"rule","allow-lan":False,"proxies":nodes,"proxy-groups":[g],"rules":rules(d)}
        if d["preset"]=="acl":cfg.update(public_routing(nodes))
        if kind in ("stash","mihomo"):
            raw=subscription.render(cc.dump(cfg),"https://example.invalid/sub",0,{**d,"_engine":eng})
            if kind=="mihomo":
                import sqlite3
                from .corecheck import verify
                check=cc.load(raw)
                if d.get("list"):check={**cfg,"proxies":check["proxies"]}
                with sqlite3.connect(":memory:") as c:
                    c.execute("CREATE TABLE corechecks(key TEXT PRIMARY KEY)")
                    verify(c,check,cc.dump(check))
            return raw,{**info,"output":len(nodes),"ext":"yaml"}
        # No panel resources are needed for these standalone rules. Keep node secrets out of the global blob store.
        import sqlite3
        with sqlite3.connect(":memory:") as c:
            c.execute("CREATE TABLE blobs(id TEXT PRIMARY KEY,body BLOB)")
            ent=apple.build(c,cfg,kind);raw=s.read_blob(c,ent["config"])
        if not ent["nodes"]:raise ValueError("此格式不能表示选中的节点")
        return raw,{**info,"output":ent["nodes"],"ext":"conf"}
    intermediate=[]
    for n in nodes:
        n=normalize(n,"mihomo")
        if n["type"]=="hysteria2":n={**n,"auth":n["password"]}
        intermediate.append(n)
    inline="data:text/plain;base64,"+base64.b64encode(cc.dump({"proxies":intermediate}).encode()).decode()
    target="shadowrocket" if kind=="shadowrocket-nodes" else kind
    raw=sidecar({"target":target,"url":inline,"emoji":"false","insert":"false","upload":"false","expand":"true"})
    ext=OTHER[kind]
    try:
        if ext=="json":
            doc=json.loads(raw)
            if not isinstance(doc.get("outbounds"),list) or not any(x.get("server") for x in doc["outbounds"]):raise ValueError
        elif ext=="conf":
            if not all(x in raw.lower() for x in ((b"[general]",b"[server_local]") if kind=="quanx" else (b"[general]",b"[proxy]"))):raise ValueError
            raw=b"\n".join(l for l in raw.split(b"\n") if not l.startswith(b"#!MANAGED-CONFIG"))
        else:
            text=fetch.node_text(raw)
            if not any("://" in l for l in text.splitlines()):raise ValueError
        if b"subconverter-extended:25500" in raw or b"127.0.0.1:25500/" in raw:raise ValueError
    except (AttributeError,TypeError,ValueError,UnicodeError):raise ValueError("转换器未返回可识别的目标配置") from None
    return raw,{**info,"ext":ext}

def compile_recipe(d):
    if not WORK.acquire(blocking=False):raise ValueError("已有转换正在进行，请稍后重试")
    try:return build(d)
    except (httpx.HTTPError,yaml.YAMLError,KeyError):raise ValueError("来源格式无法解析") from None
    finally:WORK.release()

def create(owner,body):
    d=opts(body);raw,summary=compile_recipe(d);token=secrets.token_urlsafe(32);key=s.digest(token.encode());now=int(time.time())
    with s.tx(True) as c:
        if c.execute("SELECT count(*) FROM conversions WHERE owner=?",(owner,)).fetchone()[0]>=40:raise ValueError("最多保留 40 个转换地址，请先移除不用的地址")
        c.execute("INSERT INTO conversions VALUES(?,?,?,?,?,?,?,?,0)",(key,owner,s.seal(token.encode()),s.seal(s.encode(d)),s.seal(zlib.compress(raw)),s.seal(s.encode(summary)),now,now))
    return token

def lookup(token,c,owner=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}",token):raise HTTPException(404)
    row=c.execute("SELECT * FROM conversions WHERE id=?",(s.digest(token.encode()),)).fetchone()
    if not row or owner is not None and row["owner"]!=owner:raise HTTPException(404)
    return row

def artifact(token,owner=None,refresh=False):
    now=int(time.time())
    with s.tx() as c:r=lookup(token,c,owner)
    if refresh or now-r["built"]>=3600 and now-r["attempt"]>=300:
        with s.tx(True) as c:
            got=c.execute("UPDATE conversions SET attempt=? WHERE id=? AND attempt=? AND attempt!=?",(now,r["id"],r["attempt"],now)).rowcount
        if got:
            try:
                raw,stats=compile_recipe(json.loads(s.unseal(r["recipe"])))
                with s.tx(True) as c:c.execute("UPDATE conversions SET body=?,summary=?,built=?,failed=0 WHERE id=? AND attempt=?",(s.seal(zlib.compress(raw)),s.seal(s.encode(stats)),now,r["id"],now))
            except (ValueError,TypeError):
                with s.tx(True) as c:c.execute("UPDATE conversions SET failed=1 WHERE id=? AND attempt=?",(r["id"],now))
                if refresh:raise ValueError("刷新失败，仍使用上一次成功的结果") from None
        with s.tx() as c:r=lookup(token,c,owner)
    return r

def details(row):
    d=json.loads(s.unseal(row["recipe"]));stats=json.loads(s.unseal(row["summary"]))
    return {"name":d["name"],"target":d["target"],"built":row["built"],"failed":bool(row["failed"]),**stats}
