"""Transactional editor. Secrets and large config objects stay off the summary route."""
import copy
import json
import secrets
from . import compiler as cc, store as s

def uid(prefix): return prefix+secrets.token_hex(10)

def label(value):
    if not isinstance(value,str) or not value.strip() or len(value)>160:
        raise ValueError("名称须为 1–160 个字符")
    return value.strip()

def summary(c):
    rev,w=s.workspace(c)
    live=c.execute("SELECT r.id,r.revision FROM releases r JOIN live l ON r.id=l.release").fetchone()
    return dict(revision=rev,live=dict(live) if live else None,origin=w.get("origin_build"),
        templates=[dict(id=k,name=t["name"],engine=t["engine"],platform=t["platform"],rules=len(t["order"]),
                        nodes=len(t["base"].get("proxies",[])),groups=[g["name"] for g in t["base"].get("proxy-groups",[])]) for k,t in w["templates"].items()],
        devices=[dict(id=k,**d) for k,d in w["devices"].items()],
        rules=w["rules"],resources=[{"name":k,"format":r["format"],"behavior":r["behavior"]} for k,r in w["resources"].items()],
        sources=[{"id":k,**{x:v.get(x) for x in ("name","managed","snapshot_count","last_success","issue","interval","template","group")}} for k,v in w["sources"].items()],
        releases=[dict(r) for r in c.execute("SELECT id,revision,at,actor FROM releases ORDER BY id DESC LIMIT 30")],
        auto=dict(c.execute("SELECT enabled,error FROM automation").fetchone()))

def template_detail(t):
    # Node credentials are deliberately separate from frequently edited target settings.
    return dict(name=t["name"],engine=t["engine"],platform=t["platform"],order=t["order"],
                groups=t["base"].get("proxy-groups",[]),nodes=[{"name":n["name"],"type":n["type"]} for n in t["base"].get("proxies",[])],
                settings={k:v for k,v in t["base"].items() if k not in ("proxy-groups","proxies","proxy-providers","rule-providers","rules")})

def edit(c,actor,rev,op,p):
    old,w=s.workspace(c)
    if rev!=old: raise ValueError("草稿已变化，请刷新后重试")
    templates=w["templates"]; rules=w["rules"]; devices=w["devices"]
    t=templates.get(p.get("template"))
    if op in ("template_copy","template_edit","node_add","node_remove","node_batch","rule_order","device_save") and t is None:
        raise ValueError("请选择有效模板")
    if op=="template_copy":
        v=copy.deepcopy(t); v["name"]=label(p["name"]); templates[uid("t")]=v
    elif op=="template_edit":
        t["name"]=label(p["name"])
        groups=p["groups"]; settings=p["settings"]
        if not isinstance(groups,list) or not isinstance(settings,dict) or set(settings)&{"rules","proxies","proxy-providers","proxy-groups","rule-providers"}: raise ValueError("高级设置不能覆盖结构段")
        for k in list(t["base"]):
            if k not in ("proxy-groups","proxies","proxy-providers","rule-providers"): del t["base"][k]
        t["base"].update(settings); t["base"]["proxy-groups"]=groups
        cc.compile_template(w,t)
    elif op=="template_import":
        doc=cc.load(p["yaml"])
        if not isinstance(doc,dict) or not isinstance(doc.get("rules"),list):raise ValueError("模板需要 rules 和策略组")
        if any(k in doc for k in ("script","scripts","mitm","http","external-ui-url","external-controller","listeners")):raise ValueError("公共模板含需要单独审查的扩展或监听设置")
        if doc.get("proxy-providers"):raise ValueError("请先将节点来源导入并固定为本地节点")
        for rn,entry in doc.get("rule-providers",{}).items():
            res=w["resources"].get(rn)
            if not res or res["behavior"]!=entry.get("behavior"):raise ValueError("请先维护规则资源："+rn)
            entry["url"]="studio:"+res["blob"];entry["format"]=res["format"]
        order=[]
        lookup={v:k for k,v in rules.items()}
        for l in doc.pop("rules"):
            rid=lookup.get(l) or uid("r");rules[rid]=l;lookup[l]=rid;order.append(rid)
        eng=p["engine"]
        if eng not in ("stash","mihomo"):raise ValueError("未知引擎")
        tmpl=dict(name=label(p["name"]),engine=eng,platform=label(p["platform"]),base=doc,order=order)
        cc.compile_template(w,tmpl);templates[uid("t")]=tmpl
    elif op=="source_save":
        sid=p.get("id") or uid("s")
        existing=w["sources"].get(sid,{})
        if existing.get("owned") and (existing.get("template")!=p["template"] or existing.get("group")!=p["group"]):raise ValueError("已有托管节点时请新建绑定或保持原组")
        tmpl=templates[p["template"]]
        if p["group"] not in [g["name"] for g in tmpl["base"]["proxy-groups"]]:raise ValueError("分组不存在")
        url=p.get("url") or existing.get("url","")
        if not url.startswith("https://"):raise ValueError("需要 HTTPS 订阅地址")
        existing.update(name=label(p["name"]),url=url,template=p["template"],group=p["group"],managed=bool(p.get("managed")),interval=max(300,min(604800,int(p.get("interval",21600)))))
        w["sources"][sid]=existing
    elif op=="resource_bind":
        name=label(p["name"]); fmt=p["format"]; beh=p["behavior"];url=p.get("url","")
        if fmt not in ("mrs","yaml") or beh not in ("classical","domain","ipcidr") or (fmt=="mrs" and beh=="classical"):raise ValueError("格式与行为不兼容")
        existing=w["resources"].get(name)
        if existing and (fmt!=existing["format"] or beh!=existing["behavior"]):raise ValueError("不得改变现有资源类型，请使用新名称")
        if url and not url.startswith("https://"):raise ValueError("需要 HTTPS 规则地址")
        if not existing:
            if fmt!="yaml":raise ValueError("新建资源请先导入 YAML 正文")
            content=p["content"];content_doc=cc.load(content)
            if not isinstance(content_doc,dict) or not isinstance(content_doc.get("payload"),list) or not content_doc["payload"]:raise ValueError("请提供非空 payload")
            existing=dict(blob=s.put_blob(c,content.encode()),format=fmt,behavior=beh);w["resources"][name]=existing
        existing.update(managed=bool(p.get("managed")) and bool(url or existing.get("url")),interval=86400)
        if url:existing["url"]=url;existing["kind"]="remote"
        if t:
            import hashlib
            path="./rules/"+hashlib.sha256(name.encode()).hexdigest()[:16]+"."+fmt
            t["base"].setdefault("rule-providers",{}).setdefault(name,dict(type="http",behavior=beh,format=fmt,url="studio:"+existing["blob"],path=path,interval=86400))
    elif op=="rule_order":
        order=p["order"]
        if not isinstance(order,list) or set(order)-rules.keys(): raise ValueError("规则标识无效")
        t["order"]=order; cc.compile_template(w,t)
    elif op=="rule_save":
        line=p["line"].strip()
        if not line or len(line)>1500 or "\n" in line or len(line.split(","))<2: raise ValueError("请输入完整的一行规则")
        rid=p.get("id")
        if rid and rid not in rules: raise ValueError("规则不存在")
        if not rid:
            rid=uid("r")
            selected=p["templates"]
            if not selected or set(selected)-templates.keys(): raise ValueError("请选择应用模板")
            for k in set(selected):
                templates[k]["order"].insert(0 if p.get("first") else max(0,len(templates[k]["order"])-1),rid)
        rules[rid]=line
        for tmp in templates.values():
            if rid in tmp["order"]: cc.compile_template(w,tmp)
    elif op=="rule_remove":
        rid=p["id"]
        for tmp in templates.values():
            if rid in tmp["order"]:
                tmp["order"]=[x for x in tmp["order"] if x!=rid]; cc.compile_template(w,tmp)
        del rules[rid]
    elif op in ("node_add","node_batch"):
        members=next((g for g in t["base"]["proxy-groups"] if g["name"]==p["group"]),None)
        if not members: raise ValueError("目标策略组不存在")
        nodes=p["nodes"] if op=="node_batch" else [p["node"]]
        if not isinstance(nodes,list) or not nodes or len(nodes)>3000:raise ValueError("节点数量无效")
        for n in nodes:
            if not isinstance(n,dict) or not n.get("server") or not n.get("type") or not 1<=int(n.get("port",0))<=65535: raise ValueError("节点缺少协议、地址或有效端口")
            name=label(n["name"])
            t["base"].setdefault("proxies",[]).append(n); members.setdefault("proxies",[]).append(name)
        cc.compile_template(w,t)
    elif op=="node_remove":
        name=p["name"]; t["base"]["proxies"]=[n for n in t["base"]["proxies"] if n["name"]!=name]
        for g in t["base"]["proxy-groups"]:
            if "proxies" in g: g["proxies"]=[x for x in g["proxies"] if x!=name]
        cc.compile_template(w,t)
    elif op=="device_save":
        did=p.get("id") or uid("d")
        if p.get("id") and did not in devices: raise ValueError("设备不存在")
        if did not in devices: s.new_token(c,did)
        devices[did]=dict(name=label(p["name"]),enabled=bool(p.get("enabled",True)),template=p["template"])
    elif op=="device_rotate":
        if p["id"] not in devices: raise ValueError("设备不存在")
        s.new_token(c,p["id"])
    elif op=="resource_edit":
        name=label(p["name"]); text=p["content"]
        if not isinstance(text,str) or len(text)>1000000: raise ValueError("规则资源太大")
        data=cc.load(text)
        if not isinstance(data,dict) or not isinstance(data.get("payload"),list) or not all(isinstance(x,str) for x in data["payload"]): raise ValueError("资源须包含 payload 字符串列表")
        oldres=w["resources"].get(name)
        if not oldres or oldres["format"]!="yaml": raise ValueError("仅支持编辑已有 YAML 规则资源")
        key=s.put_blob(c,text.encode())
        for tt in templates.values():
            entry=tt["base"].get("rule-providers",{}).get(name)
            if entry:entry["url"]="studio:"+key
        oldres.update(blob=key,kind="inline",url="")
    else: raise ValueError("未知操作")
    c.execute("UPDATE draft SET revision=?,body=? WHERE id=1",(old+1,s.seal(s.encode(w))))
    s.event(c,actor,op)
    return old+1
