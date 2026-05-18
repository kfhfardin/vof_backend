"""Plain-text + Markdown extractor."""

from typing import BinaryIO, ClassVar

from app.services.intake_extractors.base import ExtractedContent, IntakeExtractor


class TextExtractor(IntakeExtractor):
    name: ClassVar[str] = "text"
    accepts_mime: ClassVar[list[str]] = ["text/plain", "text/markdown"]
    accepts_ext: ClassVar[list[str]] = [".txt", ".md", ".markdown"]

    def extract(self, blob: BinaryIO, filename: str) -> ExtractedContent:
        raw = blob.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        return ExtractedContent(text=text)
