"""CSV extractor (stdlib `csv`).

Rows are returned as header-keyed dicts. First-row-is-header is assumed.
"""

import csv
import io
from typing import BinaryIO, ClassVar

from app.services.intake_extractors.base import ExtractedContent, IntakeExtractor


class CsvExtractor(IntakeExtractor):
    name: ClassVar[str] = "csv"
    accepts_mime: ClassVar[list[str]] = ["text/csv", "application/csv"]
    accepts_ext: ClassVar[list[str]] = [".csv"]

    def extract(self, blob: BinaryIO, filename: str) -> ExtractedContent:
        raw = blob.read()
        try:
            text = raw.decode("utf-8-sig")  # eat BOM if present
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        return ExtractedContent(
            rows=rows,
            metadata={"row_count": len(rows), "fieldnames": reader.fieldnames or []},
        )
