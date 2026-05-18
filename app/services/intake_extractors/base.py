"""Intake extractor protocol + shared types.

Each supported upload format has its own extractor module that implements
the IntakeExtractor protocol. The registry below resolves the right one
by MIME type first, file extension as fallback.

See LLD §C2 for the design.
"""

from enum import StrEnum
from typing import Any, BinaryIO, ClassVar, Protocol

from pydantic import BaseModel, Field


class SupportedUpload(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class ExtractedContent(BaseModel):
    """Common output shape across all extractors."""

    text: str | None = None
    rows: list[dict[str, Any]] | None = None  # for tabular (CSV/XLSX) - header-keyed
    tables: list[list[list[str]]] | None = None  # for PDFs with embedded tables
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class IntakeExtractor(Protocol):
    name: ClassVar[str]
    accepts_mime: ClassVar[list[str]]
    accepts_ext: ClassVar[list[str]]  # leading-dot extensions like ".pdf"

    def extract(self, blob: BinaryIO, filename: str) -> ExtractedContent: ...


class UnsupportedFormat(Exception):
    """Raised when no registered extractor accepts the input."""


class _ExtractorRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, IntakeExtractor] = {}

    def register(self, extractor: IntakeExtractor) -> None:
        if extractor.name in self._by_name:
            raise ValueError(f"extractor {extractor.name!r} already registered")
        self._by_name[extractor.name] = extractor

    def resolve(self, mime: str | None, filename: str) -> IntakeExtractor:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        # MIME match first
        if mime:
            for e in self._by_name.values():
                if mime.lower() in [m.lower() for m in e.accepts_mime]:
                    return e
        # Extension fallback
        for e in self._by_name.values():
            if ext in e.accepts_ext:
                return e
        raise UnsupportedFormat(f"no extractor for mime={mime!r} ext={ext!r}")

    def list_names(self) -> list[str]:
        return sorted(self._by_name)


registry = _ExtractorRegistry()
