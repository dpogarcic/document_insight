"""RQ entry point reserved for ingestion processing."""

import asyncio
import logging
from uuid import UUID

from document_insight.api.logging_config import configure_server_logging
from document_insight.api.middleware.correlation_id import correlation_id_scope
from document_insight.application.configuration.service import IngestionProfileResolver
from document_insight.application.processing.service import ProcessingService
from document_insight.config import get_settings
from document_insight.infrastructure.capability_profile.repository import (
    SqlAlchemyCapabilityProfileRepository,
)
from document_insight.infrastructure.chunk.repository import SqlAlchemyChunkRepository
from document_insight.infrastructure.chunk_embedding.repository import (
    SqlAlchemyChunkEmbeddingRepository,
)
from document_insight.infrastructure.configuration_snapshot.repository import (
    SqlAlchemyConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.document_chunker.page_window import (
    PageWindowDocumentChunkerFactory,
)
from document_insight.infrastructure.document_parser.ocr import TesseractImageDocumentParser
from document_insight.infrastructure.document_parser.pypdf import PyPdfDocumentParser
from document_insight.infrastructure.document_version.repository import (
    SqlAlchemyDocumentVersionRepository,
)
from document_insight.infrastructure.embedding.openai_compatible import (
    OpenAICompatibleTextEmbedderFactory,
)
from document_insight.infrastructure.entity.repository import SqlAlchemyEntityRepository
from document_insight.infrastructure.extracted_document.repository import (
    SqlAlchemyExtractedDocumentRepository,
)
from document_insight.infrastructure.index_generation.repository import (
    SqlAlchemyIndexGenerationRepository,
)
from document_insight.infrastructure.ingestion_profile.repository import (
    SqlAlchemyIngestionProfileRepository,
)
from document_insight.infrastructure.job.repository import SqlAlchemyJobRepository
from document_insight.infrastructure.ner.spacy import SpacyNamedEntityRecognizerFactory
from document_insight.infrastructure.object_storage.s3 import S3OriginalObjectStorage

logger = logging.getLogger(__name__)


def process_ingestion_job(job_id: str, correlation_id: str) -> None:
    """Run parsing and NER through durable version-scoped checkpoints."""
    parsed_job_id = UUID(job_id)
    parsed_correlation_id = str(UUID(correlation_id))
    configure_server_logging()
    with correlation_id_scope(parsed_correlation_id):
        asyncio.run(_process(parsed_job_id))
        logger.info(
            "Ingestion processing checkpoint completed", extra={"job_id": str(parsed_job_id)}
        )


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
        await ProcessingService(
            SqlAlchemyJobRepository(session),
            SqlAlchemyDocumentVersionRepository(session),
            SqlAlchemyExtractedDocumentRepository(session),
            SqlAlchemyEntityRepository(session),
            SqlAlchemyChunkRepository(session),
            SqlAlchemyChunkEmbeddingRepository(session),
            SqlAlchemyIndexGenerationRepository(session),
            IngestionProfileResolver(
                SqlAlchemyIngestionProfileRepository(session),
                SqlAlchemyCapabilityProfileRepository(session),
                SqlAlchemyConfigurationSnapshotRepository(session),
            ),
            storage,
            PyPdfDocumentParser(),
            TesseractImageDocumentParser(),
            SpacyNamedEntityRecognizerFactory(),
            PageWindowDocumentChunkerFactory(),
            OpenAICompatibleTextEmbedderFactory(
                settings.embedding_base_url,
                None
                if settings.embedding_api_key is None
                else settings.embedding_api_key.get_secret_value(),
            ),
            SqlAlchemyTransactionManager(session),
        ).process(job_id)
