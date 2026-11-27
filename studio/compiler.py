"""Compile isolated, immutable device releases. Feed URLs are materialized on delivery."""
import copy
import json
import re
import time
from urllib.parse import urlsplit

import yaml
from . import store as s

LOAD = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
DUMP = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
BUILTINS = {"DIRECT","REJECT","REJECT-DROP","PASS","COMPATIBLE","GLOBAL"}
CID = re.compile(r"studio:([a-f0-9]{64})\Z")

def load(text):
    return yaml.load(text, Loader=LOAD)

def dump(obj):
    return yaml.dump(obj, Dumper=DUMP, sort_keys=False, allow_unicode=True, width=4096)

def rule_target(line):
    fields = line.split(",")
    while len(fields)>1 and fields[-1].strip().lower() in ("no-resolve", "no-track", "pre-matching", "src"):
        fields.pop()
    return fields[-1].strip()

def compile_template(ws, template):
    cfg = copy.deepcopy(template["base"])
    try:
        lines = [ws["rules"][rid] for rid in template["order"]]
    except KeyError:
        raise ValueError("引用了已删除的规则") from None
    if not lines or not lines[-1].startswith(("MATCH,","FINAL,")):
        raise ValueError("最后一条必须是 MATCH 兜底规则")
    if any(l.startswith(("MATCH,","FINAL,")) for l in lines[:-1]):
        raise ValueError("兜底之前存在提前匹配全部的规则")
    cfg["rules"] = lines
    if not isinstance(cfg.get("proxy-groups"),list):
        raise ValueError("缺少策略组")
    proxies = [n["name"] for n in cfg.get("proxies",[])]
    groups = {g["name"]:g for g in cfg["proxy-groups"]}
    names = set(proxies) | set(groups) | BUILTINS
    if len(proxies)!=len(set(proxies)) or len(groups)!=len(cfg["proxy-groups"]) or set(groups)&set(proxies):
        raise ValueError("节点或策略组重名")
    providers = cfg.get("proxy-providers",{})
    rule_sets = cfg.get("rule-providers",{})
    for line in lines:
        if not isinstance(line,str) or "\n" in line or len(line.split(","))<2:
            raise ValueError("规则须为单行")
        if rule_target(line) not in names:
            raise ValueError("规则目标不存在："+rule_target(line))
        if line.startswith("RULE-SET,") and line.split(",")[1] not in rule_sets:
            raise ValueError("规则引用了不存在的规则集："+line.split(",")[1])
    done = set()
    def visit(name,path):
        if name in path:
            raise ValueError("策略组循环引用："+name)
        if name in done:
            return
        g = groups[name]
        for nxt in g.get("proxies",[]):
            if nxt not in names:
                raise ValueError("组成员不存在："+name+" → "+nxt)
            if nxt in groups:
                visit(nxt,path|{name})
        if set(g.get("use",[]))-set(providers):
            raise ValueError("策略组引用的节点来源不存在："+name)
        done.add(name)
    for name in groups:
        visit(name,set())
    resources = set()
    for section in (providers,rule_sets):
        for name,entry in section.items():
            if entry.get("type","http")=="http":
                m=CID.fullmatch(entry.get("url",""))
                if not m:
                    raise ValueError("远程资源尚未固定："+name)
                resources.add(m[1])
    return cfg,sorted(resources)

def publish(c,actor,expected):
    rev,ws=s.workspace(c)
    if expected!=rev:
        raise ValueError("草稿已更新，请重新载入差异")
    active=c.execute("SELECT r.id,r.revision FROM live l JOIN releases r ON r.id=l.release").fetchone()
    if active and active["revision"]==rev:
        return active["id"]
    manifests={}
    for tid,t in ws["templates"].items():
        try:
            cfg,resources=compile_template(ws,t)
            for key in resources:
                if not c.execute("SELECT 1 FROM blobs WHERE id=?",(key,)).fetchone():
                    raise ValueError("依赖资源缺失")
        except (ValueError,TypeError,KeyError) as e:
            raise ValueError(f"{t['name']}：{e}") from None
        text=dump(cfg)
        if t["engine"]=="mihomo":
            from .corecheck import verify
            verify(c,cfg,text)
        manifests[tid]={"config":s.put_blob(c,text.encode()),"resources":resources}
    devices={did:manifests[d["template"]] for did,d in ws["devices"].items() if d["enabled"]}
    if not devices:
        raise ValueError("没有启用的设备")
    rid=c.execute("INSERT INTO releases(revision,at,actor,manifest) VALUES(?,?,?,?)",
                  (rev,int(time.time()),actor,s.seal(s.encode(devices)))).lastrowid
    c.execute("INSERT OR REPLACE INTO live VALUES(1,?)",(rid,))
    s.event(c,actor,f"发布 #{rid} · 草稿 {rev}")
    return rid

def materialize(raw, root, release):
    cfg=load(raw)
    for section in ("rule-providers","proxy-providers"):
        for entry in cfg.get(section,{}).values():
            m=CID.fullmatch(entry.get("url",""))
            if m:
                entry["url"]=f"{root}/r/{release}/{m[1]}"
    host=urlsplit(root).hostname
    cfg["rules"]=[l.replace("{FEED_HOST}",host) for l in cfg["rules"]]
    filt=cfg.get("dns",{}).get("fake-ip-filter")
    if isinstance(filt,list) and "+."+host not in filt:
        filt.append("+."+host)
    return dump(cfg).encode()
