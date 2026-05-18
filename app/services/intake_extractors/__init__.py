"""Intake extractor registry.

Importing this package registers all seven Phase 0 extractors on the
shared `registry` singleton. Resolve via `registry.resolve(mime, filename)`.
"""

from app.services.intake_extractors.base import (
    ExtractedContent,
    IntakeExtractor,
    SupportedUpload,
    UnsupportedFormat,
    registry,
)
from app.services.intake_extractors.csv_extractor import CsvExtractor
from app.services.intake_extractors.docx_extractor import DocxExtractor
from app.services.intake_extractors.json_extractor import JsonExtractor
from app.services.intake_extractors.pdf_extractor import PdfExtractor
from app.services.intake_extractors.text_extractor import TextExtractor
from app.services.intake_extractors.xlsx_extractor import XlsxExtractor

# Register all extractors (idempotent across imports thanks to the registry guard)
for _ext_cls in (PdfExtractor, DocxExtractor, TextExtractor, CsvExtractor, XlsxExtractor, JsonExtractor):
    try:
        registry.register(_ext_cls())
    except ValueError:
        pass  # already registered (re-import)


__all__ = [
    "ExtractedContent",
    "IntakeExtractor",
    "SupportedUpload",
    "UnsupportedFormat",
    "registry",
]
