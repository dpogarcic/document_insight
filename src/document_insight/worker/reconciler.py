"""Long-running periodic recovery process for durable ingestion jobs."""

import asyncio
import logging

from document_insight.api.logging_config import configure_server_logging
from document_insight.application.processing.reconciliation import ProcessingJobReconciler
from document_insight.config import get_settings
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.document_version.repository import (
    SqlAlchemyDocumentVersionRepository,
)
from document_insight.infrastructure.job.repository import SqlAlchemyJobRepository
from document_insight.infrastructure.queue.rq import RqProcessingQueue

logger = logging.getLogger(__name__)


async def run_reconciler() -> None:
    """Continuously reconcile durable jobs at the configured bounded interval."""
    settings = get_settings()
    while True:
        try:
            async with get_session_factory()() as session:
                await ProcessingJobReconciler(
                    SqlAlchemyJobRepository(session),
                    SqlAlchemyDocumentVersionRepository(session),
                    RqProcessingQueue(settings.redis_url, settings.rq_ingestion_queue_name),
                    SqlAlchemyTransactionManager(session),
                ).reconcile()
        except Exception:
            logger.exception("processing job reconciliation failed")
        await asyncio.sleep(settings.job_reconciliation_interval_seconds)


def main() -> None:
    """Configure worker logging and start durable job reconciliation."""
    configure_server_logging()
    asyncio.run(run_reconciler())


if __name__ == "__main__":
    main()
