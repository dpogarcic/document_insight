"""RQ entry point reserved for ingestion processing."""

import asyncio
import logging
from functools import lru_cache
from uuid import UUID

from document_insight.api.logging_config import configure_server_logging
from document_insight.api.middleware.correlation_id import correlation_id_scope
from document_insight.application.processing.service import ProcessingService
from document_insight.config import get_settings
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.document_parser.ocr import TesseractImageDocumentParser
from document_insight.infrastructure.document_parser.pypdf import PyPdfDocumentParser
from document_insight.infrastructure.document_version.repository import (
    SqlAlchemyDocumentVersionRepository,
)
from document_insight.infrastructure.entity.repository import SqlAlchemyEntityRepository
from document_insight.infrastructure.extracted_document.repository import (
    SqlAlchemyExtractedDocumentRepository,
)
from document_insight.infrastructure.job.repository import SqlAlchemyJobRepository
from document_insight.infrastructure.ner.spacy import SpacyNamedEntityRecognizer
from document_insight.infrastructure.object_storage.s3 import S3OriginalObjectStorage

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_ner(english_model: str, croatian_model: str) -> SpacyNamedEntityRecognizer:
    """Load local language models once per long-running worker process."""
    return SpacyNamedEntityRecognizer(english_model, croatian_model)


def process_ingestion_job(job_id: str, correlation_id: str) -> None:
    """Run parsing and NER through durable version-scoped checkpoints."""
    parsed_job_id = UUID(job_id)
    parsed_correlation_id = str(UUID(correlation_id))
    configure_server_logging()
    with correlation_id_scope(parsed_correlation_id):
        asyncio.run(_process(parsed_job_id))
        logger.info("Ingestion NER stage completed", extra={"job_id": str(parsed_job_id)})


async def _process(job_id: UUID) -> None:
    """Compose one worker-scoped parsing service."""
    settings = get_settings()
    storage = S3OriginalObjectStorage(
        settings.s3_endpoint_url,
        settings.s3_access_key.get_secret_value(),
        settings.s3_secret_key.get_secret_value(),
        settings.s3_bucket_name,
        settings.s3_region,
    )
    async with get_session_factory()() as session:
        ner = get_ner(settings.ner_en_model, settings.ner_hr_model)
        await ProcessingService(
            SqlAlchemyJobRepository(session),
            SqlAlchemyDocumentVersionRepository(session),
            SqlAlchemyExtractedDocumentRepository(session),
            SqlAlchemyEntityRepository(session),
            storage,
            PyPdfDocumentParser(),
            TesseractImageDocumentParser(),
            ner,
            SqlAlchemyTransactionManager(session),
        ).process(job_id)
