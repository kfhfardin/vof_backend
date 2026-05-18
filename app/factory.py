"""Build the FastAPI application.

Used by app.main (the ASGI entry point), by tests (fixture), and by scripts
that need a configured app instance.
"""

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app import __version__
from app.api import register_routers
from app.errors import register_exception_handlers
from app.lifespan import lifespan
from app.logging import configure_logging
from app.settings import Settings, get_settings


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Voice of the Field",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "prod" else None,
        openapi_url="/openapi.json" if settings.environment != "prod" else None,
    )

    # Middleware (outermost first)
    app.add_middleware(RequestIdMiddleware)
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    register_routers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
