"""最小 WebDAV 服务端（仅测试用）。

支持面板实际用到的几个方法：MKCOL / PUT / GET / DELETE / PROPFIND。
放在测试里而不是依赖外部服务，是为了能离线验证：
上传、列举、下载、恢复、轮转清理这一整条链路。
"""
import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse


class DavState:
    """内存里的"远端磁盘"：路径 -> 内容。"""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.lock = threading.Lock()


def make_handler(state: DavState, auth: tuple[str, str] | None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # 静音
            pass

        # ---- 工具 ----
        def _path(self) -> str:
            return unquote(urlparse(self.path).path)

        def _authorized(self) -> bool:
            if not auth:
                return True
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                raw = base64.b64decode(header[6:]).decode()
            except Exception:
                return False
            return raw == f"{auth[0]}:{auth[1]}"

        def _deny(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="dav"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0") or 0)
            return self.rfile.read(length) if length else b""

        # ---- 方法 ----
        def _handle(self, method: str):
            if not self._authorized():
                return self._deny()
            path = self._path()
            with state.lock:
                if method == "MKCOL":
                    if path in state.dirs or any(
                            f.startswith(path.rstrip("/") + "/") for f in state.files):
                        self.send_response(405)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    state.dirs.add(path)
                    self.send_response(201)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif method == "PUT":
                    data = self._body()
                    state.files[path] = data
                    self.send_response(201)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif method == "GET":
                    data = state.files.get(path)
                    if data is None:
                        self.send_response(404)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Type", "application/octet-stream")
                    self.end_headers()
                    self.wfile.write(data)
                elif method == "DELETE":
                    existed = state.files.pop(path, None) is not None
                    self.send_response(204 if existed else 404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif method == "PROPFIND":
                    self._body()
                    prefix = path.rstrip("/") + "/"
                    entries = []
                    for name in sorted(state.files):
                        if name.startswith(prefix):
                            entries.append((name, state.files[name]))
                    body = ['<?xml version="1.0" encoding="utf-8"?>',
                            '<D:multistatus xmlns:D="DAV:">']
                    for name, data in entries:
                        body.append(
                            "<D:response><D:href>" + name + "</D:href>"
                            "<D:propstat><D:prop>"
                            f"<D:getcontentlength>{len(data)}</D:getcontentlength>"
                            "<D:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT"
                            "</D:getlastmodified>"
                            "</D:prop><D:status>HTTP/1.1 200 OK</D:status>"
                            "</D:propstat></D:response>")
                    body.append("</D:multistatus>")
                    payload = "".join(body).encode()
                    self.send_response(207)
                    self.send_header("Content-Type", "application/xml")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(405)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

        def do_MKCOL(self):
            self._handle("MKCOL")

        def do_PUT(self):
            self._handle("PUT")

        def do_GET(self):
            self._handle("GET")

        def do_DELETE(self):
            self._handle("DELETE")

        def do_PROPFIND(self):
            self._handle("PROPFIND")

    return Handler


class DavServer:
    """后台线程里的 WebDAV 服务（测试用）。"""

    def __init__(self, auth: tuple[str, str] | None = None):
        self.state = DavState()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                        make_handler(self.state, auth))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        return False
