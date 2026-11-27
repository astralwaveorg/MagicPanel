"""Loopback-only Hy2 interoperability check. Run: python -m studio.ops.check_hy2_auth /path/to/mihomo"""
import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from studio import compiler, subscription


def port(kind):
    with socket.socket(type=kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def core(binary, directory, cfg):
    directory.mkdir()
    f=directory/"config.yaml"
    f.write_text(compiler.dump(cfg))
    with subprocess.Popen([str(binary), "-d", str(directory), "-f", str(f)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as p:
        try:
            yield p
        finally:
            p.terminate()
            try:p.wait(3)
            except subprocess.TimeoutExpired:p.kill()


def check(binary):
    nonce=secrets.token_hex(24).encode()
    class Endpoint(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(nonce)
        def log_message(self,*args):pass
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        root=Path(tmp)
        endpoint=stack.enter_context(ThreadingHTTPServer(("127.0.0.1",0),Endpoint))
        threading.Thread(target=endpoint.serve_forever,daemon=True).start();stack.callback(endpoint.shutdown)
        remote=port(socket.SOCK_DGRAM)
        secret=secrets.token_urlsafe(28)
        key=ec.generate_private_key(ec.SECP256R1())
        issuer=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"localhost")])
        now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(issuer).issuer_name(issuer).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
              .not_valid_after(now+timedelta(hours=1)).sign(key,hashes.SHA256()))
        tls={"certificate":cert.public_bytes(serialization.Encoding.PEM).decode(),
             "private-key":key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()}
        server=stack.enter_context(core(binary,root/"server",{"listeners":[{"name":"fixture","type":"hysteria2","listen":"127.0.0.1","port":remote,"users":{"fixture":secret},**tls}],"rules":["MATCH,DIRECT"]}))
        def exchange(label,pw):
            local=port(socket.SOCK_STREAM)
            input_node={"type":"hysteria2","name":"test-hop","server":"127.0.0.1","port":remote,"sni":"localhost","auth":pw,"skip-cert-verify":True}
            cfg,_=compiler.compile_template({"rules":{"last":"MATCH,test-hop"}},{"engine":"mihomo","order":["last"],"base":{"proxies":[input_node],"mixed-port":local,"proxy-groups":[]}})
            delivered=compiler.load(subscription.render(compiler.dump(cfg),"http://localhost/sub/fixture",1,{"_engine":"mihomo"}))
            assert delivered["proxies"][0]["password"]==pw and "auth" not in delivered["proxies"][0]
            with core(binary,root/label,delivered) as client:
                for _ in range(100):
                    if client.poll() is not None or server.poll() is not None:raise RuntimeError("核心未启动")
                    try:
                        with socket.create_connection(("127.0.0.1",local),timeout=.1):break
                    except OSError:time.sleep(.05)
                else:raise RuntimeError("核心未就绪")
                try:
                    with httpx.Client(proxy=f"http://127.0.0.1:{local}",trust_env=False,timeout=5) as h:
                        r=h.get(f"http://127.0.0.1:{endpoint.server_port}/check")
                        return r.status_code==200 and r.content==nonce
                except httpx.HTTPError:return False
        if not exchange("valid",secret):raise RuntimeError("正确口令未能通过代理读取测试响应")
        if exchange("invalid",secrets.token_urlsafe(28)):raise RuntimeError("错误口令仍能读取测试响应")
    print("Hy2 认证通过：正确口令取得测试响应，错误口令未能取得响应。")


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("core",type=Path)
    check(parser.parse_args().core.resolve())
