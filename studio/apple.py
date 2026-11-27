"""Render native Apple profiles from one frozen, validated routing configuration."""
import hashlib
import ipaddress
import os
import re
import subprocess
import tempfile
from pathlib import Path
from . import compiler as cc,store as s

KINDS={"surge","surge5","shadowrocket"}
MARK="__STUDIO_RESOURCE__"
def scalar(v):
    if isinstance(v,bool):return str(v).lower()
    if not isinstance(v,(str,int,float)) or not str(v) or any(ch in str(v) for ch in (",","\n","\r","\x00","#",";","\u2028","\u2029",MARK)):raise ValueError("节点参数含有此格式不能安全表示的字符")
    if isinstance(v,str) and v!=v.strip():raise ValueError("参数包含不能保留的首尾空格")
    return str(v)
def node(n,kind):
    from .dialects import hy2_secret
    sr=kind=="shadowrocket"; typ=n["type"];transport=n.get("network","tcp")
    if n.get("reality-opts") and typ!="vless":raise ValueError("此协议的 Reality 握手未经目标验证")
    if transport not in ("ws","tcp","") or n.get("dialer-proxy"):raise ValueError("不支持此传输方式")
    if any(n.get(k) for k in ("ech-opts","reality-config","private-key-passphrase","certificate","name-cert-verify","smux","packet-addr","realm-opts","ip-version-required")):
        raise ValueError("此节点有未适配的握手参数")
    if n.get("private-key") and typ!="wireguard":raise ValueError("客户端证书未适配")
    if n.get("encryption") not in (None,"","none") and (typ!="vless" or kind!="surge"):raise ValueError("不支持此加密方式")
    args=[typ,scalar(n["server"]),str(int(n["port"]))]
    def opt(k,v):
        if v is not None and v!="":args.append(k+"="+scalar(v))
    if typ=="ss":
        if n.get("plugin"):raise ValueError("不支持此插件")
        opt("method" if sr else "encrypt-method",n["cipher"]);opt("password",n["password"])
    elif typ in ("vmess","vless"):
        if typ=="vless" and kind=="surge5":raise ValueError("VLESS 需要 Surge 6")
        if typ=="vmess" and int(n.get("alterId",0))!=0:raise ValueError("不支持旧 VMess 握手")
        if typ=="vless" and n.get("encryption") not in (None,"","none"):opt("encryption",n["encryption"])
        opt("password" if sr else "username",n["uuid"]);opt("tls",n.get("tls"));opt("flow",n.get("flow"))
        reality=n.get("reality-opts")
        if reality:
            if sr or reality.get("support-x25519mlkem768"):raise ValueError("此 Reality 配置未经匹配验证")
            opt("reality-public-key",reality["public-key"]);opt("reality-short-id",reality.get("short-id"))
            opt("client-fingerprint",n.get("client-fingerprint"))
    elif typ=="hysteria2":
        opt("auth" if sr else "password",hy2_secret(n))
        if n.get("obfs") or n.get("obfs-password"):raise ValueError("此混淆未适配")
        if n.get("ports") or n.get("mport"):
            if sr:raise ValueError("此格式未适配跳端口")
            ports=str(n.get("ports") or n["mport"])
            if not re.fullmatch(r"[\d,;\-: ]+",ports):raise ValueError("端口范围无效")
            args.append("port-hopping="+ports.replace(":","-").replace(",",";").replace(" ",""))
        speed=n.get("down-speed") or n.get("down")
        if speed and re.fullmatch(r'\d+(?:\s*Mbps)?',str(speed),re.I):opt("downmbps" if sr else "download-bandwidth",re.match(r'\d+',str(speed))[0])
    elif typ in ("trojan","anytls"):
        if typ=="anytls" and kind!="surge":raise ValueError("兼容格式不包含 AnyTLS")
        opt("password",n["password"])
    elif typ in ("http","socks5"):
        if n.get("tls"):args[0]="https" if typ=="http" else ("socks5-tls" if sr else "socks5-tls")
        if n.get("username") or n.get("password"):args.extend([scalar(n["username"]),scalar(n["password"])])
    elif typ=="wireguard" and sr:
        if any(n.get(k) for k in ("peers","reserved","pre-shared-key","ipv6","amnezia-wg-option")):raise ValueError("此 WireGuard 配置未适配")
        for k,key in (("privateKey","private-key"),("publicKey","public-key"),("ip","ip"),("mtu","mtu")):opt(k,n.get(key))
    else:raise ValueError("协议未适配")
    if transport=="ws":
        ws=n.get("ws-opts",{})
        if ws.get("max-early-data") or ws.get("early-data-header-name"):raise ValueError("不支持此 WebSocket 扩展")
        path=ws.get("path",n.get("ws-path","/"));headers=ws.get("headers",n.get("ws-headers",{}))
        if sr:
            if set(k.lower() for k in headers)-{"host"}:raise ValueError("无法表达此请求头")
            opt("obfs","websocket");opt("obfs-uri",path);opt("obfs-host",next(iter(headers.values()),None))
        else:
            opt("ws",True);opt("ws-path",path)
            if headers:opt("ws-headers","|".join(scalar(k)+":"+scalar(v) for k,v in headers.items()))
    opt("peer" if sr else "sni",n.get("servername") or n.get("sni"))
    if n.get("skip-cert-verify"):opt("allowInsecure" if sr else "skip-cert-verify",True)
    pin=n.get("server-cert-fingerprint") or n.get("fingerprint")
    if pin:
        if sr:raise ValueError("无法确认此证书固定格式")
        digest=str(pin).replace(":","")
        if not re.fullmatch("[a-fA-F0-9]{64}",digest):raise ValueError("指纹格式无法转换")
        opt("server-cert-fingerprint-sha256",digest)
    if n.get("alpn"):opt("alpn",",".join(n["alpn"]) if isinstance(n["alpn"],list) else n["alpn"])
    return ", ".join(args)

def literal(line):
    if not isinstance(line,str) or len(line)>5000 or any(x in line for x in ("\n","\r","\0",MARK)):raise ValueError("规则包含非法字符")
    return line
def rule(line,kind):
    literal(line)
    if line.rsplit(",",1)[-1] in ("no-track","pre-matching","src"):raise ValueError("规则带有无法等价转换的选项")
    sr=kind=="shadowrocket";port="DST-PORT" if sr else "DEST-PORT"
    typ,_,rest=line.partition(",")
    if typ=="DOMAIN-REGEX":
        pat,sep,dest=rest.rpartition(",")
        m=re.fullmatch(r'\^([\w-]+)\[\^\.\]\*\\\.([a-zA-Z0-9-]+)\$',pat)
        if not m or not sep:raise ValueError("存在无法等价转换的 DOMAIN-REGEX")
        a,b=m.groups()
        return f"AND,((DOMAIN-WILDCARD,{a}*.{b}),(NOT,((DOMAIN-WILDCARD,*.*.{b})))),{dest}"
    if typ in ("AND","OR","NOT"):
        kinds=re.findall(r'\(([A-Z][A-Z0-9-]*),',rest)
        if not kinds or any(k not in ("NETWORK","DST-PORT","DOMAIN","DOMAIN-SUFFIX","IP-CIDR","IP-CIDR6","AND","OR","NOT") for k in kinds):raise ValueError("存在无法转换的复合规则")
        return typ+","+rest.replace("(NETWORK,udp)","(PROTOCOL,UDP)").replace("(NETWORK,tcp)","(PROTOCOL,TCP)").replace("(DST-PORT,","("+port+",")
    if sr and typ in ("NETWORK","PROTOCOL"):raise ValueError("Shadowrocket 仅支持在逻辑条件内使用 PROTOCOL")
    if typ=="NETWORK" and rest.split(",")[0] in ("tcp","udp"):return "PROTOCOL,"+rest.split(",")[0].upper()+rest[len(rest.split(",")[0]):]
    if typ in ("MATCH","FINAL"):return "FINAL,"+rest
    if typ in ("DST-PORT","DEST-PORT"):return port+","+rest
    if typ in ("DOMAIN","DOMAIN-SUFFIX","DOMAIN-KEYWORD","DOMAIN-WILDCARD","IP-CIDR","IP-CIDR6","GEOIP","SRC-PORT","PROCESS-NAME","RULE-SET","IP-ASN","PROTOCOL"):return line
    raise ValueError("未支持的规则类型："+typ[:36])

def resource(c,entry,kind):
    m=cc.CID.fullmatch(entry["url"])
    if not m:raise ValueError("规则资源未固定")
    cid=m[1];behavior=entry["behavior"];fmt=entry.get("format","yaml")
    flavor="shadowrocket" if kind=="shadowrocket" and behavior=="classical" else "surge"
    key=s.digest(s.encode([cid,fmt,behavior,flavor,3 if flavor=="shadowrocket" else 2]))
    cache=c.execute("SELECT blob FROM text_rules WHERE key=?",(key,)).fetchone()
    if cache:return cache[0]
    raw=s.read_blob(c,cid)
    if fmt=="mrs":
        core=Path(os.getenv("STUDIO_CORE_DIR","/opt/studio-core"))/"mihomo"
        if not core.is_file():raise ValueError("转换 MRS 需要 Mihomo 核心")
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/"input";b=a.with_name("output");a.write_bytes(raw)
            try:r=subprocess.run([str(core),"convert-ruleset",behavior,"mrs",str(a),str(b)],capture_output=True,timeout=20)
            except (OSError,subprocess.TimeoutExpired):raise ValueError("MRS 转换未完成") from None
            if r.returncode or not b.is_file():raise ValueError("无法转换 MRS")
            lines=b.read_text().splitlines()
    elif fmt=="yaml":lines=cc.load(raw)["payload"]
    elif fmt=="text":lines=raw.decode().splitlines()
    else:raise ValueError("不支持的规则资源格式")
    out=[]
    for l in lines:
        l=literal(l).strip()
        if not l or l.startswith(("#","//")):continue
        if behavior=="domain":
            if "," in l:raise ValueError("域名资源格式错误")
            if l.startswith(("+.",".")):out.append("DOMAIN-SUFFIX,"+l.lstrip("+."))
            elif "*" in l or "+" in l:raise ValueError("域名通配符无法等价转换")
            else:out.append("DOMAIN,"+l)
        elif behavior=="ipcidr":out.append(("IP-CIDR6," if ipaddress.ip_network(l,strict=False).version==6 else "IP-CIDR,")+l)
        elif behavior=="classical":out.append(rule(l,kind))
        else:raise ValueError("未知的资源类型")
    blob=s.put_blob(c,("\n".join(out)+"\n").encode())
    c.execute("INSERT OR REPLACE INTO text_rules VALUES(?,?)",(key,blob));return blob

def build(c,cfg,kind,extra=(),platform=None):
    mobile=platform=="ios" or kind=="shadowrocket"
    if cfg.get("proxy-providers") or cfg.get("sub-rules"):raise ValueError("此模板使用了尚未支持的外部节点或子规则")
    lines=["[General]","dns-server = system","","[Proxy]"]; names={"DIRECT","REJECT"};dropped=0
    from .dialects import normalize
    for original in cfg.get("proxies",[]):
        n=normalize(original,"stash")
        try:
            nm=scalar(n["name"])
            if nm.strip()!=nm or "=" in nm or nm.startswith(("[","!")) or nm.upper() in ("DIRECT","REJECT"):raise ValueError()
            row=node(n,kind)
        except (KeyError,TypeError,ValueError):dropped+=1;continue
        names.add(nm);lines.append(nm+" = "+row)
    groups=cfg.get("proxy-groups",[]);names.update(g["name"] for g in groups)
    lines+=["","[Proxy Group]"];empty=0
    for g in groups:
        key=scalar(g["name"]);typ=g["type"]
        if "=" in key or key.startswith(("[","!")) or g.get("use") or typ not in ("select","fallback","url-test"):raise ValueError("策略组不能安全转换")
        members=[scalar(n) for n in g.get("proxies",[]) if n in names]
        if not members:members=["REJECT"];typ="select";empty+=1
        if typ!="select":
            members.extend(["url="+scalar(g.get("url") or "https://www.gstatic.com/generate_204"),"interval="+str(int(g.get("interval",600)))])
        if g.get("hidden"):members.append("hidden=1")
        lines.append(key+" = "+", ".join([typ,*members]))
    lines+=["","[Rule]"];assets=set();skipped=0;asset_names={}
    if extra:
        from .rule_view import native_lines
        lines.extend(native_lines("\n".join(extra),kind,{"DIRECT","REJECT",*(g["name"] for g in groups)}))
    for l in cfg["rules"]:
        if mobile and l.startswith("PROCESS-NAME,"):
            skipped+=1;continue
        dest=cc.rule_target(l)
        if dest not in names:
            if dest in {n["name"] for n in cfg.get("proxies",[])}:
                parts=l.split(",");ix=len(parts)-1
                while ix>0 and parts[ix] in ("no-resolve","no-track","pre-matching","src"):ix-=1
                parts[ix]="REJECT";l=",".join(parts)
            else:raise ValueError("规则目标不能转换")
        if l.startswith("RULE-SET,"):
            rule(l,kind)  # Reject unsupported modifiers before replacing the source.
            parts=l.split(",");ref=parts[1];provider=cfg["rule-providers"][ref]
            key=resource(c,provider,kind)
            if mobile and provider["behavior"]=="classical":
                original=s.read_blob(c,key).decode().splitlines()
                retained=[x for x in original if not x.startswith("PROCESS-NAME,")]
                skipped+=len(original)-len(retained)
                if not retained:continue
                if len(retained)!=len(original):key=s.put_blob(c,("\n".join(retained)+"\n").encode())
            asset_names.setdefault(key,ref)
            assets.add(key);parts[1]=MARK+"/"+key;l=",".join(parts)
            lines.append(l)
        else:lines.append(rule(l,kind))
    if not lines[-1].startswith("FINAL,"):raise ValueError("缺少最终分流规则")
    return {"config":s.put_blob(c,("\n".join(lines)+"\n").encode()),"resources":sorted(assets),"resource_names":asset_names,"desktop_rules_skipped":skipped,"format":"conf","nodes":len(cfg.get("proxies",[]))-dropped,"excluded":dropped,"empty":empty}
