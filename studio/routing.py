"""Network plans override business routing independently of device platform or renderer."""
from copy import deepcopy
from . import model

DEFAULTS=(("telecom","中国电信"),("mobile","中国移动"),("unicom","中国联通"))
def ensure(w):
    plans=w.setdefault("networks",{"default":{"name":"默认线路","rules":{},"groups":{}}})
    for k,name in DEFAULTS: plans.setdefault(k,{"name":name,"rules":{},"groups":{}})
    return plans

def effective(w,t,network):
    plans=ensure(w)
    if network not in plans:raise ValueError("线路方案不存在")
    cfg=deepcopy(t)
    base=plans["default"]
    for plan in ([base] if network=="default" else [base,plans[network]]):
        overrides=plan.get("rules",{})
        suppress=set(overrides.get("omit",[]));ordered=overrides.get("first",[])
        cfg["order"]=[k for k in ordered if k in cfg["order"] and k not in suppress]+[k for k in cfg["order"] if k not in suppress and k not in ordered]
        for rid,dest in overrides.get("targets",{}).items():
            if rid in cfg["order"]:
                fields=w["rules"][rid].split(",");i=len(fields)-1
                while i>0 and fields[i].lower().strip() in ("no-resolve","no-track","pre-matching","src"):i-=1
                fields[i]=dest;cfg.setdefault("resolved_rules",{})[rid]=",".join(fields)
        groups={g["name"]:g for g in cfg["base"].get("proxy-groups",[])}
        names=set(groups)|{"DIRECT","REJECT"}|{n["name"] for n in cfg["base"].get("proxies",[])}
        for name,o in plan.get("groups",{}).items():
            g=groups.get(name)
            if g is None:continue  # A platform-private group has no effect outside that platform.
            priority=[n for n in o.get("prefer",[]) if n in names]
            g["proxies"]=priority+[n for n in g.get("proxies",[]) if n not in priority]
            if o.get("type"):g["type"]=o["type"]
            if g["type"] in ("url-test","fallback","load-balance"):
                g.setdefault("interval",600)
                if t["engine"]=="mihomo":g.setdefault("url","https://www.gstatic.com/generate_204")
    return cfg

def save(w,p):
    from . import service,compiler
    plans=ensure(w);pid=p.get("id") or service.uid("net-")
    name=service.label(p["name"])
    if any(k!=pid and v["name"]==name for k,v in plans.items()):raise ValueError("方案名称重复")
    original=plans.get(pid,{"name":name,"rules":{},"groups":{}})
    plan=deepcopy(original)
    if p.get("copy") and pid not in plans:plan=deepcopy(plans[p["copy"]])
    plan["name"]=name
    if "group" in p and p["group"]:
        group=p["group"]
        available={g["name"] for t in w["templates"].values() for g in t["base"].get("proxy-groups",[])}
        if group not in available:raise ValueError("策略组不存在")
        prefer=p["prefer"];typ=p.get("type","")
        if typ not in ("","fallback","select","url-test") or not isinstance(prefer,list) or len(set(prefer))!=len(prefer):raise ValueError("候选顺序或策略组类型不正确")
        names=available|{"DIRECT","REJECT"}|{n["name"] for t in w["templates"].values() for n in t["base"].get("proxies",[])}
        if set(prefer)-names:raise ValueError("引用了不存在的节点或策略组")
        if typ or prefer:plan["groups"][group]={"type":typ,"prefer":prefer}
        else:plan["groups"].pop(group,None)
    if "first" in p or "omit" in p:
        first=p.get("first",[]);omit=p.get("omit",[])
        if not all(isinstance(v,list) and len(set(v))==len(v) for v in (first,omit)) or (set(first)|set(omit))-w["rules"].keys() or set(first)&set(omit):raise ValueError("方案规则标识无效或冲突")
        plan["rules"].update(first=first,omit=omit)
    if "rule" in p:
        rid=p["rule"];dest=p.get("dest","")
        if rid not in w["rules"]:raise ValueError("规则不存在")
        targets=plan["rules"].setdefault("targets",{})
        if dest:targets[rid]=service.label(dest)
        else:targets.pop(rid,None)
    plans[pid]=plan
    for target in w["templates"].values():
        compiler.compile_template(w,effective(w,target,pid))
    return pid
