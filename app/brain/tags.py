"""Reserved BrainPage.tags constants.

Phase 1 §F5/F4: web-verifier verdicts are applied to BrainPage rows by
brain_updater as one of these three reserved string tags. They live in
their own module so non-brain callers (web_verifier, dashboard rollup)
can reference the constants without importing the model layer.
"""

from __future__ import annotations

WEB_CORROBORATED = "web_corroborated"
UNVERIFIED_WEB = "unverified_web"
CONTRADICTS_WEB_SOURCE = "contradicts_web_source"

ALL_WEB_TAGS = (WEB_CORROBORATED, UNVERIFIED_WEB, CONTRADICTS_WEB_SOURCE)

__all__ = [
    "ALL_WEB_TAGS",
    "CONTRADICTS_WEB_SOURCE",
    "UNVERIFIED_WEB",
    "WEB_CORROBORATED",
]
