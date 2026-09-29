"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from aegisops.api.routes.v1 import router as v1_router
from aegisops.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="AegisOps API",
        version=settings.version,
        description="Enterprise AI incident response control plane (local, production-style).",
    )
    app.state.settings = settings

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(v1_router)
    return app
