"""Serve selected configurations only from a validated, immutable release."""
import json
import re
import secrets
from urllib.parse import quote
from fastapi import HTTPException
from . import compiler as cc,store as s

PLATFORMS={"openwrt":"openwrt","linux":"linux","win":"windows","windows":"windows","mac":"macos","macos":"macos","ios":"ios","android":"android","tvos":"tvos","appletv":"tvos"}
ENGINES={"surge":"surge","surge6":"surge","surge5":"surge5","shadowrocket":"shadowrocket","mihomo":"mihomo","clash":"mihomo","stash":"stash"}
CPUS={"arm64","aarch64","amd64","x86_64","x64","armv7","x86"}
DEFAULT_ENGINE={"windows":"mihomo","macos":"stash","ios":"stash","tvos":"stash","android":"mihomo"}
FLAGS={"scv","list","sort","tfo"}
def issue(c,rotate=False):
    row=c.execute("SELECT token FROM subscription_key WHERE id=1").fetchone()
    if row and not rotate:return s.unseal(row[0]).decode()
    token=secrets.token_urlsafe(32)
    c.execute("INSERT OR REPLACE INTO subscription_key VALUES(1,?,?)",(s.digest(token.encode()),s.seal(token.encode())))
    return token
def catalog(c,token,release=None):
    if len(token)!=43 or not c.execute("SELECT 1 FROM subscription_key WHERE digest=?",(s.digest(token.encode()),)).fetchone():raise HTTPException(404)
    if release is None:row=c.execute("SELECT a.release,a.body FROM catalogs a JOIN live l ON l.release=a.release").fetchone()
    else:row=c.execute("SELECT release,body FROM catalogs WHERE release=?",(release,)).fetchone()
    if not row:raise HTTPException(404)
    cat=json.loads(s.unseal(row[1]))
    extra=c.execute("SELECT body FROM client_catalogs WHERE release=?",(row[0],)).fetchone()
    if extra:
        data=json.loads(s.unseal(extra[0]));cat["deliveryProfiles"]=data["deliveryProfiles"];cat["targets"].update(data["targets"])
    return row[0],cat
def options(items,cat):
    opts={}
    for key,v in items:
        key={"skip-cert-verify":"scv","target":"type","os":"platform"}.get(key,key)
        if key not in {"type","platform","arch","name","network","template"}|FLAGS:raise ValueError("不支持的订阅参数："+key[:40])
        if key in opts:raise ValueError("参数重复："+key)
        if len(v)>160:raise ValueError("参数过长")
        if key in FLAGS:
            if v not in ("true","false"):raise ValueError(key+" 只接受 true 或 false")
            opts[key]=v=="true"
        else:opts[key]=v
    kind=opts.get("type","").lower();arch=opts.get("arch","").lower()
    aliases=[]
    if "platform" in opts:
        if opts["platform"].lower() not in PLATFORMS:raise ValueError("未知平台")
        aliases.append(PLATFORMS[opts["platform"].lower()])
    if kind in PLATFORMS:aliases.append(PLATFORMS[kind]);kind=""
    if arch in PLATFORMS:aliases.append(PLATFORMS[arch])
    elif arch and arch not in CPUS:raise ValueError("未知 CPU 架构")
    if len(set(aliases))>1:raise ValueError("平台参数冲突")
    platform=next(iter(aliases),None)
    if not platform and not opts.get("template") and (kind or arch):
        raise ValueError("请指定 platform；不能仅凭引擎或 CPU 判断平台")
    pid=opts.get("template","platform-"+(platform or "windows"))
    p=cat.get("deliveryProfiles",cat["profiles"]).get(pid)
    if not p or (platform and p["platform"]!=platform):raise ValueError("模板与平台不匹配")
    engine=ENGINES.get(kind) if kind else DEFAULT_ENGINE.get(p["platform"])
    if not kind and engine not in p["adapters"]:engine=next(iter(p["adapters"]))
    if engine not in p["adapters"]:raise ValueError("模板没有对应的客户端适配")
    tid=p["adapters"][engine];network=opts.get("network","default")
    if network not in cat["targets"][tid]:raise ValueError("线路方案不存在或尚未发布")
    if "tfo" in opts and engine!="mihomo":raise ValueError("此输出不支持 tfo；Stash 的 QUIC fast-open 不是 TCP Fast Open")
    name=opts.get("name",p["name"])
    if len(name)>80 or not re.fullmatch(r"[\w .()（）-]+",name) or name in (".","..") or not name.strip():raise ValueError("名称仅可包含文字、数字、空格、点、括号、连字符或下划线")
    entry=cat["targets"][tid][network]
    if "error" in entry:raise ValueError(entry["error"])
    if entry.get("format")=="conf" and FLAGS.intersection(opts):raise ValueError("此客户端使用完整配置，不接受 YAML 节点参数")
    opts["_engine"]=engine
    return entry,opts,name
def render(raw,root,rid,opts):
    from .dialects import normalize
    cfg=cc.load(raw);nodes=[normalize(n,opts["_engine"]) for n in cfg.get("proxies",[])]
    if "proxies" in cfg:cfg["proxies"]=nodes
    # Dynamic overrides cannot be applied honestly to external proxy providers.
    if cfg.get("proxy-providers") and any(k in opts for k in ("tfo","scv")):raise ValueError("带节点提供者的配置不支持全局节点参数")
    if cfg.get("proxy-providers") and opts.get("list"):raise ValueError("带节点提供者的模板不能仅导出静态节点")
    for n in nodes:
        typ=n.get("type")
        if "tfo" in opts and typ in {"http","socks5","ss","ssr","snell","vmess","vless","trojan","anytls","ssh"} and n.get("network")!="quic":n["tfo"]=opts["tfo"]
        if "scv" in opts and (n.get("tls") is True or typ in {"trojan","hysteria","hysteria2","tuic","anytls"}) and not n.get("reality-opts") and not n.get("server-cert-fingerprint") and not n.get("fingerprint"):
            n["skip-cert-verify"]=opts["scv"]
    if opts.get("sort"):nodes.sort(key=lambda n:n["name"].casefold())
    if opts.get("list"):return cc.dump({"proxies":nodes}).encode()
    return cc.materialize_cfg(cfg,root,rid)
def disposition(name,ext="yaml"):return "attachment; filename*=UTF-8''"+quote(name+"."+ext,safe="")
