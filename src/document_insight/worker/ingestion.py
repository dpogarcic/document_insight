"""RQ entry point reserved for ingestion processing."""

import logging
from uuid import UUID

from document_insight.api.logging_config import configure_server_logging
from document_insight.api.middleware.correlation_id import correlation_id_scope

logger = logging.getLogger(__name__)


def process_ingestion_job(job_id: str, correlation_id: str) -> None:
    """Validate and trace a queued job until processing stages are implemented.

    The callable deliberately does not parse, OCR, index, or transition durable job state.
    Those processing stages will be introduced in a later worker slice.
    """
    parsed_job_id = UUID(job_id)
    parsed_correlation_id = str(UUID(correlation_id))
    configure_server_logging()
    with correlation_id_scope(parsed_correlation_id):
        logger.info(
            "Ingestion worker received a job awaiting processing implementation",
            extra={"job_id": str(parsed_job_id)},
        )
