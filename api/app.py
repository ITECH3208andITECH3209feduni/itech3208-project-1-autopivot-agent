"""FastAPI application factory."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import ALLOWED_ORIGINS
from api.routes_auth import router as auth_router
from api.routes_backdrops import router as backdrops_router
from api.routes_dashboard import router as dashboard_router
from api.routes_listings import router as listings_router
from api.routes_platform_admin import router as platform_admin_router
from api.routes_platform_dealership_users import router as platform_dealership_users_router
from api.routes_dealership_users import router as dealership_users_router

logger = logging.getLogger("autopivot")


def create_app(
    lifespan: Optional[Callable[..., Any]] = None,
    *,
    description: str = (
        "Authentication and dealership data for AutoPivot. "
        "Vehicle processing routes are added by autopivot_backend.py."
    ),
) -> FastAPI:
    app = FastAPI(
        title="AutoPivot",
        description=description,
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method, request.url.path, exc, exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred."},
        )

    @app.get("/health/api", tags=["Observability"])
    async def api_health() -> dict:
        """Liveness for the non-ML half. /health additionally reports models."""
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(listings_router)
    app.include_router(backdrops_router)
    app.include_router(platform_admin_router)
    app.include_router(platform_dealership_users_router)
    app.include_router(dealership_users_router)

    return app


app = create_app()

