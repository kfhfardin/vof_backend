"""Object storage Protocol + workspace_key helper.

The workspace_key helper is the only sanctioned way to build storage keys
outside the storage module (per LLD §A6). A lint check rejects ad-hoc
key construction in other modules.
"""

from typing import BinaryIO, Literal, Protocol
from uuid import UUID


class ObjectStore(Protocol):
    async def put(self, key: str, data: BinaryIO | bytes, content_type: str) -> str:
        """Upload data; returns the canonical key."""

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def signed_url(
        self,
        key: str,
        ttl_seconds: int = 900,
        method: Literal["GET", "PUT"] = "GET",
    ) -> str: ...


def workspace_key(workspace_id: UUID, *parts: str) -> str:
    """Build a workspace-scoped S3 key.

    Layout (LLD §A6 + HLD §11.5):
        workspaces/{workspace_id}/<parts joined by />
    Example:
        workspace_key(wid, "intake", str(item_id), "raw.pdf")
        -> "workspaces/{wid}/intake/{item_id}/raw.pdf"
    """
    if not parts:
        raise ValueError("workspace_key needs at least one path part")
    clean = [p.strip("/") for p in parts if p]
    return f"workspaces/{workspace_id}/" + "/".join(clean)
