"""Response schemas for the document ingestion endpoint."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from document_insight.api.schemas.common import ApiModel


class IngestStoredResponse(ApiModel):
    """Identifiers returned after the original and version metadata are stored."""

    document_id: UUID
    document_version_id: UUID
    version_number: Annotated[int, Field(ge=1)]
    status: Literal["stored"] = "stored"
