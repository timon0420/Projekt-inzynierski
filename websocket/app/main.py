from __future__ import annotations

import asyncio
import contextlib
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config as cfg
from .routes import APIError, router as api_router
from .sessions import PairRateLimiter, SessionManager
from .ws import router as ws_router

async def cleanup_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(cfg.CLEANUP_INTERVAL)
        now = time.time()
        for client in app.state.manager.cleanup(now):
            await client.close(1000)
        app.state.pair_limiter.prune(now)

def create_app(settings: cfg.Settings | None = None) -> FastAPI:
    settings = settings or cfg.Settings.from_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(cleanup_loop(app))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Server", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.manager = SessionManager()
    app.state.pair_limiter = PairRateLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins) or ["*"],
        allow_methods=['GET', 'POST', 'OPTIONS'],
        allow_headers=['Content-Type']
    )

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, error: APIError) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"error": error.code})

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, error: StarletteHTTPException) -> JSONResponse:
        code = 'method_not_allowed' if error.status_code == 405 else str(error.detail)
        return JSONResponse(status_code=error.status_code, content={"error": code})

    app.include_router(api_router)
    app.include_router(ws_router)

    return app

app = create_app()
