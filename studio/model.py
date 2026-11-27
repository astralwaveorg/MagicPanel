"""Business policies are edited once; each renderer gets a projection with explicit exceptions."""
import copy
import hashlib
import json
from difflib import SequenceMatcher

def common_order(lists):
    common=list(lists[0]) if lists else []
    for other in lists[1:]:
        if common==other:continue
        common=[r for a,b,n in SequenceMatcher(None,common,other,autojunk=False).get_matching_blocks() for r in common[a:a+n]]
    return common

def offsets(shared,local):
    if shared==local:return {}
    if len(set(shared))!=len(shared) or len(set(local))!=len(local):
        return {"explicit":local}
    shared_set=set(shared)
    if [r for r in local if r in shared_set]!=[r for r in shared if r in set(local)]:return {"explicit":local}
    extra={};batch=[]
    for rid in local:
        if rid in shared_set:
            if batch:extra[rid]=batch;batch=[]
        else:batch.append(rid)
    if batch:extra["$end"]=batch
    return {"omit":[r for r in shared if r not in set(local)],"before":extra}

def project(shared,diff):
    if "explicit" in diff:return list(diff["explicit"])
    omit=set(diff.get("omit",[]));before=diff.get("before",{})
    if set(before)-set(shared)-{"$end"}:raise ValueError("规则仍被设备例外用作顺序锚点")
    out=[]
    for rid in shared:
        out.extend(before.get(rid,[]))
        if rid not in omit:out.append(rid)
    return out+before.get("$end",[])

def ensure(w):
    if not w.get("policies"):
        ts=list(w["templates"].values())
        w["policies"]={"default":{"name":"日常分流","order":common_order([t["order"] for t in ts])}}
        for t in ts:t["policy"]="default"
    return w

def pack(work):
    w=ensure(copy.deepcopy(work));tables={"nodes":{},"groups":{}}
    for t in w["templates"].values():
        pid=t["policy"]
        t["exceptions"]=offsets(w["policies"][pid]["order"],t.pop("order"))
        for table,field in (("nodes","proxies"),("groups","proxy-groups")):
            if field not in t["base"]:continue
            refs=[]
            for val in t["base"].pop(field):
                raw=json.dumps(val,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
                key=hashlib.sha256(raw).hexdigest()[:32]
                tables[table].setdefault(key,val);refs.append(key)
            t[table]=refs
    w["libraries"]=tables;w["format"]=2
    return w

def expand(w):
    if w.get("format")!=2:return ensure(w)
    tables=w.pop("libraries")
    for t in w["templates"].values():
        t["order"]=project(w["policies"][t["policy"]]["order"],t.pop("exceptions"))
        for table,field in (("nodes","proxies"),("groups","proxy-groups")):
            if table in t:t["base"][field]=[copy.deepcopy(tables[table][k]) for k in t.pop(table)]
    w.pop("format",None)
    return w

def change_order(w,pid,order):
    old=w["policies"][pid]["order"]
    for t in w["templates"].values():
        if t["policy"]==pid:t["order"]=project(order,offsets(old,t["order"]))
    w["policies"][pid]["order"]=order
