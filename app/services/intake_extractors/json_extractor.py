"""JSON extractor.

If top-level is an array of objects, treat as rows (CRM-like exports).
If top-level is an object, dump as text.
"""

import json
from typing import Any, BinaryIO, ClassVar

from app.services.intake_extractors.base import ExtractedContent, IntakeExtractor


class JsonExtractor(IntakeExtractor):
    name: ClassVar[str] = "json"
    accepts_mime: ClassVar[list[str]] = ["application/json"]
    accepts_ext: ClassVar[list[str]] = [".json"]

    def extract(self, blob: BinaryIO, filename: str) -> ExtractedContent:
        raw = blob.read()
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return ExtractedContent(warnings=[f"json_parse_failed: {e}"])

        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            return ExtractedContent(rows=parsed, metadata={"row_count": len(parsed)})
        return ExtractedContent(text=json.dumps(parsed, indent=2))
