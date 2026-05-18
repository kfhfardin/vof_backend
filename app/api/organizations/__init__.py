"""Reserved namespace — empty in Phase 0.

The §C10 hierarchy guard test asserts this namespace exists but returns 404
for any path inside it. Phase 1+ will populate it for org_admin endpoints.
"""

from fastapi import APIRouter

router = APIRouter()
