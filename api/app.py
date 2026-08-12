"""FastAPI application factory.

Deliberately free of any machine-learning import. The vision stack is several
gigabytes and needs a GPU to be useful, but authentication and the dashboard
need neither — so this module can be served on a laptop, in CI, or anywhere a
GPU is absent:

    uvicorn api.app:app --reload

autopivot_backend.py calls create_app() and bolts the processing routes on top,
so the full deployment still exposes one application with one set of routes.
"""

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

    # Fixed by Vadim Rudoi — wildcard "*" with allow_credentials=True is an
    # invalid CORS combination that every modern browser rejects. Origins are
    # explicit and credentials are off; the bearer token travels in the
    # Authorization header, which is why that header is allowed here.
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

    return app


# Module-level instance so `uvicorn api.app:app` works without the ML stack.
app = create_app()
