"""Local Tesseract parser for standalone image documents."""

from io import BytesIO

import pytesseract  # type: ignore[import-untyped]  # Third-party adapter lacks stubs.
from PIL import Image, UnidentifiedImageError
from pytesseract import TesseractError

from document_insight.application.processing.exceptions import ParsingError
from document_insight.application.processing.models import ParsedDocument
from document_insight.infrastructure.document_parser.protocol import DocumentParser


class TesseractImageDocumentParser(DocumentParser):
    """Extract text from PNG and JPEG originals with local Tesseract OCR."""

    def parse(self, content: bytes) -> ParsedDocument:
        """Recognize one image without retaining its pixels after the call."""
        try:
            with Image.open(BytesIO(content)) as image:
                text = pytesseract.image_to_string(image)
        except (OSError, TesseractError, UnidentifiedImageError) as error:
            raise ParsingError from error
        return ParsedDocument(text=text, page_count=1, parser_name="tesseract", parser_version="5")
