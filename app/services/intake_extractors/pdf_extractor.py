"""PDF extractor (pdfplumber primary, pypdf fallback).

Scanned-image-only PDFs (no text layer) yield empty text + a warning
flagging the item for needs_review per §C2.
"""

import io
from typing import BinaryIO, ClassVar

import pdfplumber
import pypdf

from app.services.intake_extractors.base import ExtractedContent, IntakeExtractor


class PdfExtractor(IntakeExtractor):
    name: ClassVar[str] = "pdf"
    accepts_mime: ClassVar[list[str]] = ["application/pdf"]
    accepts_ext: ClassVar[list[str]] = [".pdf"]

    def extract(self, blob: BinaryIO, filename: str) -> ExtractedContent:
        data = blob.read()
        bio = io.BytesIO(data)
        text_parts: list[str] = []
        tables_data: list[list[list[str]]] = []
        page_count = 0
        warnings: list[str] = []

        try:
            with pdfplumber.open(bio) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(page_text)
                    # Tables: only collect if the page has well-formed ones
                    page_tables = page.extract_tables()
                    for t in page_tables:
                        cleaned = [[(c or "") for c in row] for row in t]
                        tables_data.append(cleaned)
        except Exception as e:
            warnings.append(f"pdfplumber_failed: {type(e).__name__}: {e}; falling back to pypdf")
            text_parts = []
            try:
                reader = pypdf.PdfReader(io.BytesIO(data))
                page_count = len(reader.pages)
                for pypdf_page in reader.pages:
                    text_parts.append(pypdf_page.extract_text() or "")
            except Exception as e2:
                warnings.append(f"pypdf_also_failed: {type(e2).__name__}: {e2}")

        text = "\n\n".join(p for p in text_parts if p.strip())
        if not text:
            warnings.append("no_text_extracted")

        return ExtractedContent(
            text=text or None,
            tables=tables_data or None,
            metadata={"page_count": page_count, "table_count": len(tables_data)},
            warnings=warnings,
        )
