"""Router auto-discovery.

Walks app/api/* (excluding subpackages with `_skip_autodiscovery=True`),
imports each module, and mounts any `router` attribute under /api/v1.

Reserved namespaces (organizations, rep) get explicit empty mounts so the
§C10 hierarchy guard test can assert they're present-but-empty.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from fastapi import FastAPI

API_PREFIX = "/api/v1"


def _walk_module_names(package: str) -> list[str]:
    pkg = importlib.import_module(package)
    out: list[str] = []
    for info in pkgutil.walk_packages(pkg.__path__, prefix=f"{package}."):
        # Skip the reserved-namespace subpackages here; we mount them explicitly below.
        if info.name.startswith(("app.api.organizations", "app.api.rep")):
            continue
        if info.ispkg:
            continue
        out.append(info.name)
    return out


def register_routers(app: FastAPI) -> None:
    # Auto-discovered routers
    for module_name in _walk_module_names("app.api"):
        module = importlib.import_module(module_name)
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            app.include_router(router, prefix=API_PREFIX)

    # Reserved namespaces — present but empty in Phase 0
    from app.api.organizations import router as organizations_router
    from app.api.rep import router as rep_router

    app.include_router(organizations_router, prefix=f"{API_PREFIX}/organizations", tags=["reserved"])
    app.include_router(rep_router, prefix=f"{API_PREFIX}/rep", tags=["reserved"])
