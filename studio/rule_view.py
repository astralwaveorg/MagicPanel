"""Display only the rule sections of the actual release. Do not return feed keys or proxies."""
import ipaddress
import json
import re
from . import apple, compiler as cc, store as s

def engines(platform):
    return {"macos":["surge","surge5"],"ios":["surge","surge5","shadowrocket"]}.get(platform,[])

def native_lines(text,engine,names):
    if not isinstance(text,str) or len(text)>100_000:raise ValueError("专属规则超过 100 KB")
    out=[]
    for i,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line or line.startswith("#"):continue
        fields=line.split(",")
        if len(fields)!=3 or any(not x or x!=x.strip() or any(c in x for c in "#;\r\x00[]") for x in fields):
            raise ValueError(f"第 {i} 行需要「类型,匹配值,去向」")
        typ,value,dest=fields
        try:
            if dest not in names:raise ValueError()
            if typ in ("IP-CIDR","IP-CIDR6"):
                if ipaddress.ip_network(value,strict=False).version!=(6 if typ.endswith("6") else 4):raise ValueError()
            elif typ in ("DOMAIN","DOMAIN-SUFFIX","DOMAIN-KEYWORD"):
                if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*",value):raise ValueError()
            elif typ==("DST-PORT" if engine=="shadowrocket" else "DEST-PORT"):
                if not value.isascii() or not value.isdigit() or not 1<=int(value)<=65535:raise ValueError()
            else:raise ValueError()
        except ValueError:raise ValueError(f"第 {i} 行的类型、匹配值或去向不受此格式支持") from None
        out.append(line)
    if len(out)>500 or len(set(out))!=len(out):raise ValueError("专属规则重复或超过 500 条")
    return out

def inspect(c,pid,engine,network,asset="",offset=0):
    row=c.execute("SELECT releases.id,client_catalogs.body FROM live JOIN releases ON live.release=releases.id JOIN client_catalogs ON client_catalogs.release=releases.id").fetchone()
    if not row:raise ValueError("尚无客户端产物")
    cat=json.loads(s.unseal(row[1]));p=cat["deliveryProfiles"].get(pid)
    tid=p and p["adapters"].get(engine)
    entry=cat["targets"].get(tid,{}).get(network)
    if entry is None:raise ValueError("所选平台、格式和线路尚未发布")
    info={"release":row[0],"engine":engine,"error":entry.get("error",""),"desktop_skipped":entry.get("desktop_rules_skipped",0)}
    if info["error"]:return info
    if not 0<=offset<=20_000_000:raise ValueError("页码无效")
    if asset and asset not in entry["resources"]:raise ValueError("此输出未引用该资源")
    raw=s.read_blob(c,asset or entry["config"])
    if asset:
        if raw[:3]==b"MRS" or raw[:4]==bytes.fromhex("28b52ffd"):
            return {**info,"lines":[],"count":0,"binary":True,"bytes":len(raw)}
        rows=raw.decode("utf-8-sig").splitlines();resources=[]
    elif entry.get("format")=="conf":
        _,sep,text=raw.decode().partition("\n[Rule]\n")
        if not sep:raise ValueError("缺少原生规则段")
        rows=text.splitlines()
        # Rules keep their order across rendering. Recover source names for the frozen references.
        base_id=p["adapters"].get("stash") or p["adapters"].get("mihomo")
        base=cat["targets"][base_id][network]
        canonical=cc.load(s.read_blob(c,base["config"]))["rules"]
        names=dict(entry.get("resource_names",{}))
        originals=[l.split(",")[1] for l in canonical if l.startswith("RULE-SET,")]
        ids=[l.split(",")[1].removeprefix(apple.MARK+"/") for l in rows if l.startswith("RULE-SET,")]
        if len(originals)==len(ids):
            for key,label in zip(ids,originals):names.setdefault(key,label)
        resources=[{"key":k,"name":names.get(k,"规则集 "+k[:10])} for k in entry["resources"]]
        rows=[re.sub(re.escape(apple.MARK)+r"/([0-9a-f]{64})",lambda m:names.get(m[1],"规则集 "+m[1][:10]),l) for l in rows]
    else:
        cfg=cc.load(raw);rows=cfg["rules"];resources=[]
        for k,v in cfg.get("rule-providers",{}).items():
            m=cc.CID.fullmatch(v.get("url",""))
            if m:resources.append({"key":m[1],"name":k})
    return {**info,"count":len(rows),"offset":offset,"lines":rows[offset:offset+100],"resources":resources}
