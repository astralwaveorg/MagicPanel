"""应用入口：路由、静态托管与安全响应头。"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import HTTPException as StarletteHTTPException

from . import config, db
from .routers import (auth, builds, feed, misc, policy, portal, rule_providers,
                      snippets, sources, targets_devices)


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(title="MagicPanel", docs_url=None, redoc_url=None, openapi_url=None)

    for r in (auth.router, sources.router, rule_providers.router, policy.router,
              targets_devices.router, builds.router, misc.router, feed.router,
              portal.router, snippets.router):
        app.include_router(r)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    static = config.STATIC_DIR
    index = static / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """SPA 托管：存在的静态文件直接返回，其余回退到 index.html。"""
        if static.is_dir():
            candidate = (static / full_path).resolve()
            if full_path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            if index.is_file():
                return FileResponse(index)
        return JSONResponse(
            {"detail": "前端资源未构建，请先执行 npm run build"},
            status_code=503,
        )

    return app


app = create_app()
