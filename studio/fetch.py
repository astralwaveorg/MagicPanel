"""Bounded HTTPS fetch. Connect to the checked IP; TLS still verifies the source hostname."""
import base64
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit,urljoin

def get(url, ua="MagicPanel-Studio", headers=()):
    original=urlsplit(url)
    for hop in range(4):
        p=urlsplit(url)
        if p.scheme!="https" or not p.hostname or p.username or p.password:raise ValueError("仅接受公开 HTTPS 地址")
        port=p.port or 443;host=p.hostname
        addrs=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
        if not addrs or not all(ipaddress.ip_address(x[4][0]).is_global for x in addrs):raise ValueError("来源解析到了非公网地址")
        h={"User-Agent":ua,"Accept-Encoding":"identity","Connection":"close"}
        if (original.hostname,original.port or 443)==(p.hostname,port):
            for item in headers:
                k=item["name"]
                if k.lower() in ("authorization","cookie","accept","user-agent"):h[k]=item["value"]
        conn=http.client.HTTPSConnection(host,port,timeout=8,context=ssl.create_default_context())
        conn._create_connection=lambda address,timeout,source_address=None:socket.create_connection((addrs[0][4][0],port),timeout)
        try:
            conn.request("GET",(p.path or "/")+("?"+p.query if p.query else ""),headers=h)
            res=conn.getresponse()
            if res.status in (301,302,303,307,308):
                url=urljoin(url,res.getheader("Location",""));continue
            if res.status!=200:raise ValueError("来源返回 HTTP "+str(res.status))
            data=res.read(8_000_001)
            if not data or len(data)>8_000_000:raise ValueError("来源为空或超过 8 MB")
            return data
        finally:conn.close()
    raise ValueError("来源重定向次数过多")

def node_text(body):
    raw=body.decode("utf-8-sig").strip()
    if "://" in raw or "proxies:" in raw:return raw
    try:return base64.b64decode(raw+"="*(-len(raw)%4),altchars=b"-_",validate=True).decode()
    except (ValueError,UnicodeError):raise ValueError("无法解析订阅编码") from None
