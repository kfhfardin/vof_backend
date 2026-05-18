"""Intake handler registry surface.

handler.ingest() round-trips against the brain provider live in
test_intake_handlers_brain.py (they exercise the §C8 brain-write path
that is the real behavior).
"""

import pytest

from app.services.intake_handlers import (
    CallerBrainHandler,
    CrossRefHandler,
    OrgBrainHandler,
    RawSourceHandler,
    resolve_handler,
)


def test_resolve_handler_for_each_scope() -> None:
    assert isinstance(resolve_handler("ORG_WIDE"), OrgBrainHandler)
    assert isinstance(resolve_handler("CALLER_SPECIFIC"), CallerBrainHandler)
    assert isinstance(resolve_handler("BOTH"), CrossRefHandler)
    assert isinstance(resolve_handler("RAW_SOURCE"), RawSourceHandler)


def test_resolve_handler_unknown_scope() -> None:
    with pytest.raises(ValueError, match="unknown scope"):
        resolve_handler("WHATEVER")
