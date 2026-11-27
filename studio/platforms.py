"""Five product templates; an engine adapter is not a user-facing template."""
from copy import deepcopy

PLATFORMS=[("windows","Windows"),("macos","macOS"),("tvos","Apple TV"),("ios","iOS"),("android","Android")]

def fresh(w):
    profiles={}
    targets={}
    for platform,name in PLATFORMS:
        pid="platform-"+platform
        engines=["stash"] if platform in ("ios","tvos") else ["mihomo","stash"]
        adapters={}
        for eng in engines:
            tid=pid+"-"+eng;adapters[eng]=tid
            targets[tid]={"name":name+" / "+("Mihomo" if eng=="mihomo" else "Stash"),"engine":eng,"platform":platform,"policy":"default","order":["r-final"],
                "base":{"mode":"rule","log-level":"info","allow-lan":False,"proxies":[],"proxy-groups":[{"name":"默认出口","type":"select","proxies":["DIRECT"]}]}}
        profiles[pid]={"name":name,"platform":platform,"policy":"default","adapters":adapters}
    w.update(profiles=profiles,templates=targets,policies={"default":{"name":"日常分流","order":["r-final"]}})
    return w

def from_baseline(w):
    """Deliberate product change: shared platform defaults, no per-person configuration."""
    if w.get("profiles"):return
    if not w.get("origin_build"):raise ValueError("需要新的平台模板初始化器")
    ts=w["templates"]; profiles={}; keep={}
    old=len(ts)
    for platform,name in PLATFORMS:
        base={t["engine"]:k for k,t in ts.items() if t["platform"]==platform and k.startswith("t") and k[1:].isdigit()}
        if not base:raise ValueError("缺少共享平台基线："+name)
        pid="platform-"+platform
        for eng,k in base.items():keep[k]=ts[k]
        profiles[pid]={"name":name,"platform":platform,"policy":"default","adapters":base}
    for d in w["devices"].values():
        old_target=ts[d["template"]];pid="platform-"+old_target["platform"]
        d.update(profile=pid,engine=old_target["engine"],template=profiles[pid]["adapters"][old_target["engine"]])
    w.update(profiles=profiles,templates=keep)
    return {"previous_renderers":old,"profiles":len(profiles),"renderers":len(keep),"devices":len(w["devices"])}

def duplicate(w,source,name,pid,new_policy=None):
    p=deepcopy(w["profiles"][source]);p["name"]=name
    if new_policy:p["policy"]=new_policy
    for eng,src in list(p["adapters"].items()):
        tid=pid+"-"+eng
        t=deepcopy(w["templates"][src]);t.update(name=name+" / "+eng,policy=p["policy"])
        w["templates"][tid]=t;p["adapters"][eng]=tid
    w["profiles"][pid]=p
