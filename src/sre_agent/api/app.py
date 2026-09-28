"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import settings
from ..logging_setup import get_logger, setup_logging
from .routes import router
from .service import AgentService

log = get_logger("api")


def create_app(service: AgentService | None = None) -> FastAPI:
    setup_logging()
    svc = service or AgentService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = svc
        # The agent runs in a worker thread; give the broker the serving loop so events
        # can be published across the thread boundary.
        svc.broker.bind_loop(asyncio.get_running_loop())
        await asyncio.to_thread(svc.startup)
        log.info("SRE Memory Agent API ready")
        try:
            yield
        finally:
            await asyncio.to_thread(svc.shutdown)
            log.info("SRE Memory Agent API stopped")

    app = FastAPI(
        title="SRE Memory Agent",
        description=(
            "An SRE agent that investigates failures, recalls how it fixed similar "
            "incidents via Hindsight memory, and verifies repairs in a sandbox."
        ),
        version=_version(),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root():
        index = _frontend_dir() / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            {
                "service": "sre-memory-agent",
                "version": _version(),
                "docs": "/docs",
                "api": "/api/status",
                "note": (
                    "Frontend build not found. Run `npm install && npm run build` in web/, "
                    "or use the Vite dev server on port 5173."
                ),
            }
        )

    assets = _frontend_dir() / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
        _mount_spa_fallback(app)

    return app


def _frontend_dir() -> Path:
    return settings.base_dir / "web" / "dist"


def _mount_spa_fallback(app: FastAPI) -> None:
    """Serve index.html for client-side routes that are not API calls."""

    dist = _frontend_dir()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "Not Found"}, status_code=404)


def _version() -> str:
    from .. import __version__

    return __version__


app = None  # populated by scripts/serve.py to keep import cost out of tooling
