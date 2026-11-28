"""Anonymous, same-origin access to a private OmniSub. No recipe database or access logs."""
import base64
import csv
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit

import yaml
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 8192
seal = Fernet(Path("/run/secrets/link-key").read_bytes().strip())
targets = {"clash", "stash", "surge", "shadowrocket"}
schemes = {"ss", "ssr", "vmess", "vless", "trojan", "hy2", "hysteria2", "tuic", "hysteria", "anytls"}
LIMIT = 512_000
blocked = set(os.environ.get("DENY_IPS", "").split(","))
assets = Path(__file__).parent / "www"


class InputError(ValueError):
    pass


def check(ok, message):
    if not ok:
        raise InputError(message)


def b64(text):
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)


def remote(url):
    for _ in range(3):
        p = urlsplit(url)
        check(p.scheme == "https" and p.hostname and not p.username and not p.password
              and p.port in (443, None) and p.hostname.lower().rstrip(".") != os.environ["PUBLIC_HOST"],
              "订阅来源必须是其他站点的公开 HTTPS 地址（443 端口）。")
        addresses = [x[4][0] for x in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)]
        for addr in addresses:
            ip = ipaddress.ip_address(addr)
            check(ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local)
                  and not (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo
                      or ip in ipaddress.ip_network("64:ff9b::/96"))) and addr not in blocked, "来源不能指向内网或本机。")
        check(addresses, "订阅来源没有公网地址。")
        conn = http.client.HTTPSConnection(p.hostname, timeout=6, context=ssl.create_default_context())
        conn._create_connection = lambda _, timeout, source_address=None: socket.create_connection((addresses[0], 443), timeout)
        try:
            conn.request("GET", (p.path or "/") + ("?" + p.query if p.query else ""),
                         headers={"User-Agent":"clash.meta (OmniSub)", "Accept-Encoding":"identity"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                url = urljoin(url, r.getheader("Location", "")); continue
            check(r.status == 200, "订阅来源未返回可用内容。")
            data = r.read(LIMIT + 1)
            check(0 < len(data) <= LIMIT, "每份来源最多 500 KB。")
            return data.decode("utf-8-sig").strip()
        finally:
            conn.close()
    raise InputError("订阅来源重定向次数过多。")


def recipe(obj):
    check(isinstance(obj, dict) and set(obj) <= {"target", "sources", "list", "ver"}, "含有不支持的选项。")
    t, src = obj.get("target"), obj.get("sources")
    check(isinstance(t, str) and t in targets and isinstance(src, str) and 0 < len(src.encode()) <= 4200, "请选择格式，来源合计最多 4.2 KB。")
    check(type(obj.get("list", False)) is bool and (not obj.get("list") or t in {"clash", "stash"}), "仅 YAML 支持节点列表。")
    check("ver" not in obj or (t == "surge" and str(obj["ver"]) in ("5","6")), "Surge 仅支持版本 5 或 6。")
    return {"target": t, "sources": src.strip(), "list": bool(obj.get("list")), **({"ver":str(obj.get("ver","6"))} if t=="surge" else {})}


def inspect_sources(src):
    parts, count, pins, auth = [], 0, False, []
    volume = 0
    def add(text, root=False):
        nonlocal count, pins, volume
        volume += len(text.encode())
        check(volume <= LIMIT * 2, "合并后的订阅过大。")
        lines = [s.strip() for s in text.splitlines() if s.strip() and not s.lstrip().startswith("#")]
        if not lines:
            raise InputError("没有找到节点。")
        if not all("://" in s and re.match(r"^[A-Za-z0-9+.-]+://",s) for s in lines):
            if len(lines)==1 and re.fullmatch(r"[\w+/=_-]+",lines[0],re.ASCII):
                decoded=b64(lines[0]).decode()
                check("://" in decoded or "proxies:" in decoded,"未识别的订阅内容。")
                return add(decoded)
            check(not any(isinstance(t,(yaml.tokens.AnchorToken,yaml.tokens.AliasToken)) for t in yaml.scan(text)), "暂不接受带 YAML 锚点的来源。")
            doc=yaml.safe_load(text)
            check(isinstance(doc,dict) and not doc.get("proxy-providers") and isinstance(doc.get("proxies"),list), "请提供节点链接或带 proxies 的 YAML，嵌套订阅请直接填写原地址。")
            rows=doc["proxies"]
            for n in rows:
                check(isinstance(n,dict) and isinstance(n.get("name"),str) and n.get("server") and n.get("port"),"YAML 节点缺少名称、地址或端口。")
                pins |= any(str(k).lower() in ("fingerprint","server-cert-fingerprint","pinsha256","certificate-public-key-sha256") and n[k] for k in n)
                if n.get("type") in ("hysteria2","hy2"):
                    pw=n.get("auth",n.get("password"))
                    check(isinstance(pw,str) and pw and pw==n.get("password",pw),"Hysteria2 的认证字段为空或不一致。")
                    n.update(auth=pw,password=pw)
                    auth.append((str(n["server"]).lower(),int(n["port"]),pw))
            count+=len(rows)
            parts.append("data:text/plain;base64,"+base64.b64encode(yaml.safe_dump({"proxies":rows},allow_unicode=True).encode()).decode())
            return
        for line in lines:
            check("|" not in line, "每个来源请单独写一行。")
            p=urlsplit(line)
            if p.scheme=="https" and root:
                add(remote(line)); continue
            check(p.scheme in schemes and len(line)<=16384,"存在不支持的来源或嵌套网址。")
            pins |= any(k.lower() in ("pinsha256","fingerprint","server-cert-fingerprint") for k,_ in parse_qsl(p.query))
            if p.scheme in ("hy2","hysteria2"):
                secret=unquote(p.netloc.rpartition("@")[0])
                check(secret and p.hostname,"Hysteria2 节点缺少认证或服务器地址。")
                # Current release can leave percent escapes in exported credentials.
                check("%" not in p.netloc.rpartition("@")[0], "此版本不能可靠转换含转义口令的 Hysteria2 链接，请改用节点 YAML。")
                auth.append((p.hostname.lower(),p.port or 443,secret))
            count+=1;parts.append(line)
    check(sum(s.strip().startswith("https://") for s in src.splitlines())<=4,"一次最多合并 4 个订阅。")
    add(src,True)
    check(0<count<=512,"一次可转换 1 至 512 个节点。")
    check(not pins,"此版本尚不能在所有格式保留证书指纹，已停止转换。请在对应客户端使用原配置。")
    return parts,count,auth


def build(d):
    parts,total,auth=inspect_sources(d["sources"])
    t=d["target"]
    params={"target":t,"url":"|".join(parts),"config":"base/public.ini","expand":"true","insert":"false","emoji":"false","upload":"false"}
    if d["list"]:params["list"]="true"
    if t=="surge":params["ver"]=d["ver"]
    path="/sub?"+urlencode(params)
    check(len(path)<750_000,"合并后的节点过大。")
    c=http.client.HTTPConnection("engine",25500,timeout=16)
    try:
        c.request("GET",path); r=c.getresponse()
        check(r.status==200,"OmniSub 无法生成所选格式，请检查来源和客户端。")
        raw=r.read(3_000_001)
    finally:c.close()
    check(0<len(raw)<=3_000_000,"转换结果为空或过大。")
    if t in ("clash","stash"):
        rows=yaml.safe_load(raw).get("proxies",[])
        field="auth" if t=="stash" else "password"
        actual=[(str(n.get("server")).lower(),int(n["port"]),n.get(field)) for n in rows if n.get("type")=="hysteria2"]
        check(Counter(actual)==Counter(auth),"转换后的 Hysteria2 认证与来源不一致，已停止交付。")
        written=len(rows)
    elif t=="surge":
        raw=b"\n".join(line for line in raw.split(b"\n") if not line.startswith(b"#!MANAGED-CONFIG"))
        block=re.search(rb"(?ims)^\[Proxy\]\s*\n(.*?)(?=^\[|\Z)",raw)
        check(block,"OmniSub 没有生成 Surge 代理配置。")
        surge_auth=[]
        for line in block[1].decode().splitlines():
            _,sep,params=line.partition("=")
            if not sep:continue
            values=next(csv.reader([params.strip()],skipinitialspace=True))
            if len(values)>=4 and values[0].lower() in ("hysteria2","hy2"):
                options=dict(v.strip().split("=",1) for v in values[3:] if "=" in v)
                surge_auth.append((values[1].strip().lower(),int(values[2]),options.get("password")))
        check(Counter(surge_auth)==Counter(auth),"Surge 不能等价表示这组 Hysteria2 认证，已停止交付。")
        written=sum(bool(re.match(rb"^[^#;][^=]*=\s*(?!direct\b|reject\b)[\w-]+\s*,",l.strip(),re.I)) for l in block[1].splitlines())
    else:
        lines=b64(raw.decode().strip()).decode().splitlines()
        links=[urlsplit(line) for line in lines if "://" in line]
        sr_auth=[(p.hostname.lower(),p.port or 443,unquote(p.netloc.rpartition("@")[0])) for p in links if p.scheme in ("hysteria2","hy2")]
        check(Counter(sr_auth)==Counter(auth),"Shadowrocket 输出的 Hysteria2 认证与来源不一致。")
        written=len(links)
    check(written==total,"所选格式不能完整保留这组节点，已停止生成。请按协议拆分或更换格式。")
    return raw,written


@app.errorhandler(Exception)
def failed(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e,HTTPException):return jsonify(error=e.name),e.code
    return jsonify(error=str(e) if isinstance(e,InputError) else "读取来源或转换失败，请检查来源后重试。"),422


@app.after_request
def headers(r):
    r.headers.update({"Cache-Control":"no-store","Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff",
                      "Content-Security-Policy":"default-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'","X-Robots-Tag":"noindex"})
    return r


@app.get("/")
def index():return send_from_directory(assets,"index.html")


@app.get("/favicon.svg")
@app.get("/favicon.ico")
@app.get("/apple-touch-icon.png")
def brand_icon():return send_from_directory(assets,request.path.lstrip("/"))


@app.get("/assets/<name>")
def asset(name):
    check(name in {"app.js","style.css"},"资源不存在。")
    return send_from_directory(assets,name)


@app.get("/healthz")
def health():
    c=http.client.HTTPConnection("engine",25500,timeout=2)
    try:
        c.request("GET","/healthz");r=c.getresponse()
        return ("ok\n",200) if r.status==200 and r.read(16).strip()==b"ok" else ("unavailable\n",503)
    finally:c.close()


@app.post("/api/links")
def create():
    d=recipe(request.get_json())
    raw,count=build(d)
    token=seal.encrypt(json.dumps(d,ensure_ascii=False,separators=(",",":")).encode()).decode()
    check(len(token)<6500,"更新地址过长，请改用原订阅网址。")
    return jsonify(path="/s/"+token,count=count)


@app.get("/s/<token>")
@app.get("/sub",defaults={"token":None})
def feed(token):
    if token:
        try:d=recipe(json.loads(seal.decrypt(token.encode())))
        except (InvalidToken,ValueError):return jsonify(error="更新地址无效。"),404
    else:
        q=request.args
        check(set(q)<={"url","target","list","ver"} and all(len(q.getlist(k))==1 for k in q) and q.get("list","false") in {"true","false"}, "转换参数无效。")
        d=recipe({"sources":q.get("url","").replace("|","\n"),"target":q.get("target"),"list":q.get("list")=="true",**({"ver":q["ver"]} if "ver" in q else {})})
    raw,_=build(d)
    ext={"clash":"yaml","stash":"yaml","surge":"conf","shadowrocket":"txt"}[d["target"]]
    return Response(raw,content_type="text/plain; charset=utf-8",headers={"Content-Disposition":f'attachment; filename="omnisub-{d["target"]}.{ext}"'})
