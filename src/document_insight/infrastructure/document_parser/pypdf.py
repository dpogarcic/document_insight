"""PDF text parser built on pypdf."""

from io import BytesIO

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
        except (PdfReadError, ValueError) as error:
            raise ParsingError from error
        return ParsedDocument(
            text="\n\f\n".join(pages),
            page_count=len(pages),
            parser_name="pypdf",
            parser_version="6.19.0",
        )
