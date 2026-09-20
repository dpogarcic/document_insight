"""PDF text parser built on pypdf."""

from io import BytesIO

import fitz  # type: ignore[import-untyped]  # Third-party adapter lacks stubs.
import pytesseract  # type: ignore[import-untyped]  # Third-party adapter lacks stubs.
from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from document_insight.application.processing.exceptions import ParsingError
from document_insight.application.processing.models import ParsedDocument
from document_insight.infrastructure.document_parser.protocol import DocumentParser


class PyPdfDocumentParser(DocumentParser):
    """Extract embedded text from PDFs; OCR is intentionally a later adapter."""

    def parse(self, content: bytes) -> ParsedDocument:
        """Parse all PDF pages without retaining source bytes or exception detail."""
        try:
            reader = PdfReader(BytesIO(content))
            pages = tuple(page.extract_text() or "" for page in reader.pages)
            if not any(page.strip() for page in pages):
                rendered = fitz.open(stream=content, filetype="pdf")
                pages = tuple(
                    pytesseract.image_to_string(
                        Image.open(BytesIO(page.get_pixmap(dpi=200).tobytes("png")))
                    )
                    for page in rendered
                )
                rendered.close()
        except (PdfReadError, ValueError, fitz.FileDataError, OSError) as error:
            raise ParsingError from error
        return ParsedDocument(
            text="\n\f\n".join(pages),
            page_count=len(pages),
            parser_name="pypdf",
            parser_version="6.19.0",
        )
