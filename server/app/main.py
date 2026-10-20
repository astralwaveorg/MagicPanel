"""应用入口：路由、静态托管与安全响应头。"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import HTTPException as StarletteHTTPException

from . import config, db
from .routers import (auth, automation, base_config, builds, feed, local_nodes,
                      misc, policy, portal, rule_providers, snippets, sources,
                      targets_devices)
from .services import retention, scheduler


async def _retention_loop() -> None:
    """留存清理独立运行：不能因为关掉调度器就停止回收磁盘。"""
    import asyncio
    await asyncio.sleep(120)
    while True:
        try:
            await asyncio.to_thread(retention.run_once)
        except Exception:  # 清理失败不能影响主进程
            pass
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = scheduler.start_loop() if config.SCHEDULER_AUTOSTART else None
    retention_task = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        retention_task.cancel()
        if task:
            await scheduler.stop_loop(task)


def _setup_logging() -> None:
    """配置根日志。

    uvicorn 只配置了 uvicorn.* 这几个 logger，应用自己的 logger
    （scheduler / retention 等）默认不输出，INFO 级的运行摘要全部丢失。
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app() -> FastAPI:
    _setup_logging()
    try:
        db.init_db()
    except Exception as exc:  # 迁移失败不应该让容器陷入崩溃循环
        logging.getLogger("magicpanel").error(
            "数据库初始化/迁移失败，面板以只读降级模式启动：%s", exc)
        logging.getLogger("magicpanel").error(
            "请检查 data 目录权限与数据库文件，修复后重启容器")
    app = FastAPI(
        title="MagicPanel", docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )

    for r in (auth.router, sources.router, rule_providers.router, policy.router,
              targets_devices.router, builds.router, misc.router, automation.router,
              local_nodes.router, base_config.router, feed.router, portal.router,
              snippets.router):
        app.include_router(r)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'",
        )
        if request.url.scheme == "https" or request.headers.get(
                "x-forwarded-proto", "").split(",")[0].strip() == "https":
            # 不加 includeSubDomains：magichub.top 是家庭共享域名，
            # 其它子域可能是明文 HTTP，被强制 HTTPS 会直接打不开。
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000")
        return resp

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    static = config.STATIC_DIR
    index = static / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str, request: Request):
        """SPA 托管：存在的静态文件直接返回，其余回退到 index.html。

        /api 与 /feed 下的未知路径返回 JSON 404——否则接口写错时
        会拿到一份 index.html，前端与脚本都很难判断到底哪里错了。
        """
        if full_path.startswith(("api/", "feed/")):
            return JSONResponse({"detail": "接口不存在"}, status_code=404)
        if static.is_dir():
            candidate = (static / full_path).resolve()
            if full_path and candidate.is_file() and static.resolve() in candidate.parents:
                response = FileResponse(candidate)
                # 带哈希的静态资源可以长期缓存，index.html 必须每次回源
                if full_path.startswith("assets/"):
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                else:
                    response.headers["Cache-Control"] = "no-cache"
                return response
            if index.is_file():
                response = FileResponse(index)
                response.headers["Cache-Control"] = "no-cache"
                return response
        return JSONResponse(
            {"detail": "前端资源未构建，请先执行 npm run build"},
            status_code=503,
        )

    return app


app = create_app()
