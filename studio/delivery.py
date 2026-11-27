"""Supplement released templates with client outputs, independently of the mutable draft."""
import copy,json
from . import compiler as cc,store as s,apple

def portable(c,entry,engine,router=False):
    cfg=cc.load(s.read_blob(c,entry["config"]))
    cfg={k:v for k,v in cfg.items() if k in ("proxies","proxy-groups","rules","rule-providers","proxy-providers","mode","log-level")}
    if not router:cfg["allow-lan"]=False
    if engine=="mihomo":
        from .dialects import normalize
        if "proxies" in cfg:cfg["proxies"]=[normalize(n,engine) for n in cfg["proxies"]]
        for n in cfg.get("proxies",[]):
            for key in ("benchmark-url","benchmark-timeout","benchmark-disabled"):n.pop(key,None)
        for g in cfg.get("proxy-groups",[]):
            if g["type"] in ("fallback","url-test","load-balance"):g.setdefault("url","https://www.gstatic.com/generate_204")
        from .corecheck import verify
        verify(c,cfg,cc.dump(cfg))
    return {**entry,"config":s.put_blob(c,cc.dump(cfg).encode())}

def prepare(c,rid,cat):
    profiles=copy.deepcopy(cat["profiles"]);targets={};cache={}
    from .dialects import normalize
    from .corecheck import verify
    # Older releases may contain mixed source dialects even within one template.
    for p in profiles.values():
        for engine,tid in p["adapters"].items():
            if tid in targets:continue
            targets[tid]={}
            for net,entry in cat["targets"][tid].items():
                k=(entry["config"],engine,"base")
                if k not in cache:
                    cfg=cc.load(s.read_blob(c,entry["config"]))
                    if cfg.get("proxy-providers"):raise ValueError("请将节点来源展开为已校验的节点后发布")
                    if "proxies" in cfg:cfg["proxies"]=[normalize(n,engine) for n in cfg["proxies"]]
                    text=cc.dump(cfg)
                    if engine=="mihomo":verify(c,cfg,text)
                    cache[k]={**entry,"engine":engine,"config":s.put_blob(c,text.encode())}
                targets[tid][net]=cache[k]
    for pid,p in list(profiles.items()):
        if p["platform"] not in ("macos","ios","tvos"):continue
        tid=p["adapters"].get("stash") or p["adapters"].get("mihomo")
        if not tid:continue
        engines=[]
        if p["platform"] in ("ios","tvos") and "mihomo" not in p["adapters"]:engines+=["mihomo"]
        if p["platform"] in ("ios","macos"):engines+=["surge","surge5"]
        if p["platform"]=="ios":engines+=["shadowrocket"]
        for eng in engines:
            aid="client:"+pid+":"+eng;p["adapters"][eng]=aid;targets[aid]={}
            for net,ent in targets[tid].items():
                extra=tuple(p.get("native_rules",{}).get(eng,[]))
                k=(ent["config"],eng,extra,p["platform"])
                if k not in cache:
                    try:cache[k]=portable(c,ent,eng) if eng=="mihomo" else apple.build(c,cc.load(s.read_blob(c,ent["config"])),eng,extra,p["platform"])
                    except (ValueError,KeyError,TypeError) as e:
                        if extra:raise ValueError(p["name"]+" / "+eng+" · "+net+"："+str(e)) from None
                        cache[k]={"error":str(e)[:150] if isinstance(e,ValueError) else "模板字段不完整","resources":[]}
                targets[aid][net]=cache[k]
    win=profiles.get("platform-windows")
    if win and "mihomo" in win["adapters"]:
        for platform,label in (("linux","Linux"),("openwrt","OpenWrt")):
            pid="platform-"+platform;aid="client:"+platform+":mihomo"
            profiles[pid]={"platform":platform,"name":label,"adapters":{"mihomo":aid},"policy":win["policy"]}
            targets[aid]={}
            for net,ent in targets[win["adapters"]["mihomo"]].items():
                k=(ent["config"],platform)
                if k not in cache:cache[k]=portable(c,ent,"mihomo",router=platform=="openwrt")
                targets[aid][net]=cache[k]
    c.execute("INSERT OR REPLACE INTO client_catalogs VALUES(?,?)",(rid,s.seal(s.encode({"deliveryProfiles":profiles,"targets":targets}))))
def upgrade(c):
    for row in c.execute("SELECT release,body FROM catalogs WHERE release NOT IN (SELECT release FROM client_catalogs)").fetchall():
        prepare(c,row[0],json.loads(s.unseal(row[1])))

def protect_existing_outputs(c,previous,current):
    """An update cannot turn a working subscription into a permanent error response."""
    def catalog(rid):
        row=c.execute("SELECT body FROM client_catalogs WHERE release=?",(rid,)).fetchone()
        return json.loads(s.unseal(row[0])) if row else {}
    before,after=catalog(previous),catalog(current)
    for pid,p in after.get("deliveryProfiles",{}).items():
        prior=before.get("deliveryProfiles",{}).get(pid,{}).get("adapters",{})
        for engine,tid in p["adapters"].items():
            old=before.get("targets",{}).get(prior.get(engine),{})
            for net,entry in after["targets"][tid].items():
                if entry.get("error") and net in old and not old[net].get("error"):
                    raise ValueError(f"{p['name']} / {engine} / {net}：{entry['error']}。已保留原发布")
