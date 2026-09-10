"""Run with: uvicorn backend.app.main:app --host 0.0.0.0 --port 8000."""

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import api, auth, realtime, storage
from .game import GameError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    storage.initialize()
    timer = asyncio.create_task(realtime.clock())
    try:
        yield
    finally:
        timer.cancel()
        await asyncio.gather(timer, return_exceptions=True)
        for peer in list(realtime.connections):
            realtime.detach(peer, 1001)


app = FastAPI(title="魔法裁判 · 七双", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(api.router)


@app.middleware("http")
async def request_boundary(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if not auth.same_origin(request):
            return JSONResponse({"detail": "仅允许从本站提交操作"}, status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 3_000_000:
                return JSONResponse({"detail": "请求过大，图片限制为2MB"}, status_code=413)
            body.extend(chunk)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


@app.exception_handler(GameError)
async def game_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def input_error(request, exc):
    return JSONResponse({"detail": "输入格式不合法，请检查必填项、类型及长度"}, status_code=422)


@app.exception_handler(sqlite3.Error)
async def storage_error(request, exc):
    logger.error("数据库操作失败，事务已回滚", exc_info=exc)
    return JSONResponse(
        {"detail": "保存失败，请稍后刷新状态；请勿直接重复提交操作"}, status_code=503
    )


@app.websocket("/api/live")
async def live(socket: WebSocket):
    await realtime.live(socket)


app.mount(
    "/assets/characters", StaticFiles(directory=storage.PROJECT_ROOT / "img"), name="characters"
)


@app.get("/{path:path}")
async def frontend(path: str):
    if path == "api" or path.startswith("api/"):
        return JSONResponse({"detail": "接口不存在"}, status_code=404)
    dist = storage.PROJECT_ROOT / "frontend" / "dist"
    candidate = (dist / path).resolve()
    if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    index = dist / "index.html"
    if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
        return JSONResponse({"detail": "文件不存在"}, status_code=404)
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        {"detail": "前端尚未构建，请先在frontend目录运行npm run build，开发时使用Vite页面"},
        status_code=503,
    )
