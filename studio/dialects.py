"""Protocol fields are chosen by the output engine, never by device name."""
import re
from decimal import Decimal

HY2_TYPES = {"hysteria2", "hy2"}


def hy2_secret(node):
    values = [node[k] for k in ("auth", "password") if k in node]
    if not values or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError("Hysteria2 需要非空的文本认证凭据")
    if len(values) == 2 and values[0] != values[1]:
        raise ValueError("Hysteria2 的 auth 与 password 不一致，请核对来源")
    return values[0]


def normalize(node, engine):
    if not isinstance(node, dict):
        raise ValueError("节点格式无效")
    typ=node.get("type")
    tls_types={"hysteria","hysteria2","hy2","tuic","trojan","vless","vmess","anytls","http","socks5","ss"}
    if typ not in tls_types:return node
    if engine not in ("stash","mihomo"):raise ValueError("未指定有效的 YAML 配置格式")
    out=dict(node)
    if typ in HY2_TYPES:
        secret=hy2_secret(out)
        out.pop("auth",None);out.pop("password",None)
        out["type"]="hysteria2";out["auth" if engine=="stash" else "password"]=secret
        if engine=="mihomo":out.pop("fast-open",None)
    if typ=="tuic":
        v=out.pop("version",None)
        token=out.get("token");uuid=out.get("uuid");pw=out.get("password")
        if token and (uuid or pw) or not token and not (uuid and pw):raise ValueError("TUIC v4 需要 token，v5 需要 uuid 和 password，不能混用")
        actual=4 if token else 5
        if v is not None and str(v)!=str(actual):raise ValueError("TUIC 版本与认证参数不一致")
        for k in (("uuid","password") if token else ("token",)):out.pop(k,None)
        if engine=="stash":out["version"]=actual
    if typ=="hysteria" and out.get("auth") and out.get("auth-str"):raise ValueError("Hysteria v1 请只保留一种认证编码")
    if typ=="hysteria" and engine=="stash" and out.get("protocol")=="faketcp":raise ValueError("Stash 不支持此 Hysteria v1 传输方式")
    for base in (("up","down") if typ in HY2_TYPES|{"hysteria"} else ()):
        for k in (base,base+"-speed"):
            if out.get(k) in ("",None):out.pop(k,None)
        alias=base+"-speed"
        if alias not in out and (engine=="mihomo" or base not in out):continue
        def mbps(value):
            m=re.fullmatch(r"(\d+(?:\.\d+)?)\s*(kbps|mbps|gbps|bps)?",str(value).strip(),re.I)
            if not m:raise ValueError("Hysteria 带宽单位无法转换")
            return Decimal(m[1])*{"bps":Decimal(".000001"),"kbps":Decimal(".001"),"mbps":1,"gbps":1000}[(m[2] or "mbps").lower()]
        vals=[mbps(out.pop(k)) for k in (base,alias) if k in out]
        if len(set(vals))>1:raise ValueError("Hysteria 带宽参数不一致")
        if engine=="stash" and int(vals[0])!=vals[0]:raise ValueError("Stash 带宽必须能表示为整数 Mbps")
        out[alias if engine=="stash" else base]=int(vals[0]) if int(vals[0])==vals[0] else f"{vals[0]} Mbps"
    pins=[]
    for k in ("fingerprint","server-cert-fingerprint"):
        if k in out:
            pin=out.pop(k)
            if pin:
                digest=str(pin).replace(":","").lower()
                if not re.fullmatch(r"[0-9a-f]{64}",digest):raise ValueError("TLS 证书指纹必须是 SHA-256")
                pins.append(digest)
    if len(set(pins))>1:raise ValueError("TLS 证书指纹不一致")
    if pins:out["server-cert-fingerprint" if engine=="stash" else "fingerprint"]=pins[0]
    return out
