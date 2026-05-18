"""workspace_key helper - the only sanctioned way to build storage keys."""

import uuid

import pytest

from app.storage.base import workspace_key


def test_basic_layout() -> None:
    wid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    key = workspace_key(wid, "intake", "abc", "raw.pdf")
    assert key == f"workspaces/{wid}/intake/abc/raw.pdf"


def test_strips_extra_slashes() -> None:
    wid = uuid.uuid4()
    key = workspace_key(wid, "/intake/", "/file.txt/")
    assert "//" not in key
    assert key.startswith(f"workspaces/{wid}/")


def test_requires_at_least_one_part() -> None:
    with pytest.raises(ValueError):
        workspace_key(uuid.uuid4())
