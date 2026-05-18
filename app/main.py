"""ASGI entry point: `uvicorn app.main:app`."""

from app.factory import build_app

app = build_app()
