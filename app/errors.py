"""Exception types and HTTP error envelope.

Webhook routes bypass this envelope and return per provider contracts
(see app/api/webhooks/*).
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class VotFError(Exception):
    http_status: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(VotFError):
    http_status = 404
    code = "not_found"


class Forbidden(VotFError):
    http_status = 403
    code = "forbidden"


class Validation(VotFError):
    http_status = 400
    code = "validation"


class Conflict(VotFError):
    http_status = 409
    code = "conflict"


class UpstreamError(VotFError):
    http_status = 502
    code = "upstream_error"


def _envelope(code: str, message: str, request_id: str | None, details: dict[str, Any]) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "request_id": request_id, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(VotFError)
    async def _votf_handler(request: Request, exc: VotFError) -> JSONResponse:
        request_id = request.headers.get("x-request-id")
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(exc.code, exc.message, request_id, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Preserve the original detail; map common statuses to our code vocabulary.
        code_map = {404: "not_found", 403: "forbidden", 401: "unauthenticated", 409: "conflict"}
        code = code_map.get(exc.status_code, "http_error")
        request_id = request.headers.get("x-request-id")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail), request_id, {}),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = request.headers.get("x-request-id")
        return JSONResponse(
            status_code=400,
            content=_envelope(
                "validation", "Request validation failed", request_id, {"errors": exc.errors()}
            ),
        )
