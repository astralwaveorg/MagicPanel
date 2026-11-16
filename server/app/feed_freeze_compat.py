"""ASGI 兼容冻结层；reader 不依赖 V2 新迁移。"""
from pathlib import Path
from starlette.middleware import Middleware

from . import db, security
from .services import feed_freeze


class FeedFreezeMiddleware:
    def __init__(self, app, root: Path):
        self.app = app
        self.root = root

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'http' and scope.get('method') in ('GET', 'HEAD'):
            path = scope.get('path', '')
            if path.startswith('/feed/') or path.startswith('/res/'):
                identity = self._identity_ok(scope, path)
                if identity is None:
                    await self._plain(send, 503, b'identity unavailable')
                    return
                if not identity:
                    await self.app(scope, receive, send)
                    return
                found = feed_freeze.lookup_frozen(
                    self.root, path=path, query=scope.get('query_string', b'').decode('latin-1'),
                    method=scope.get('method', ''), identity_ok=True)
                if found is not None:
                    await self._respond(scope, send, found)
                    return
        await self.app(scope, receive, send)

    def _identity_ok(self, scope, path: str) -> bool | None:
        if path.startswith('/res/'):
            return True
        parts = path.split('/', 3)
        token = parts[2] if len(parts) > 2 else ''
        if not token or len(token) < 20:
            return False
        try:
            with db.connect() as conn:
                device = db.one(conn, 'SELECT id FROM devices WHERE token_hash=?',
                                (security.sha256_text(token),))
            return bool(device)
        except Exception:
            return None

    async def _respond(self, scope, send, found):
        headers = [(b'content-type', found['content_type'].encode('latin-1')),
                   (b'etag', ('"' + found['etag'] + '"').encode('latin-1')),
                   (b'cache-control', b'private, no-cache'),
                   (b'x-content-type-options', b'nosniff')]
        if_match = dict((key.lower(), value.decode('latin-1')) for key, value in scope.get('headers', []))
        if scope['method'] == 'HEAD':
            body = b''
            headers.append((b'content-length', str(len(found['body'])).encode('ascii')))
        elif if_match.get('if-none-match') in ('"' + found['etag'] + '"', found['etag'], '*'):
            await send({'type': 'http.response.start', 'status': 304, 'headers': headers})
            await send({'type': 'http.response.body', 'body': b''})
            return
        else:
            body = found['body']
            headers.append((b'content-length', str(len(body)).encode('ascii')))
        await send({'type': 'http.response.start', 'status': 200, 'headers': headers})
        await send({'type': 'http.response.body', 'body': body})

    async def _plain(self, send, status: int, body: bytes):
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-length', str(len(body)).encode('ascii'))]})
        await send({'type': 'http.response.body', 'body': body})


def install_freeze_reader(app, root: Path | None = None):
    from .config import DATA_DIR
    selected = (root or DATA_DIR / 'feed-freeze').resolve()
    if not selected.exists() or not (selected / 'ACTIVE').exists():
        return False
    app.user_middleware.insert(0, Middleware(FeedFreezeMiddleware, selected))
    app.middleware_stack = None
    return True
