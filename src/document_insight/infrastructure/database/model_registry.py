"""Import every ORM model so shared SQLAlchemy metadata is complete."""

from document_insight.infrastructure.active_profile.model import ActiveProfileModel
from document_insight.infrastructure.capability_profile.model import CapabilityProfileModel
from document_insight.infrastructure.chunk.model import ChunkModel
from document_insight.infrastructure.chunk_embedding.model import ChunkEmbeddingModel
from document_insight.infrastructure.configuration_snapshot.model import ConfigurationSnapshotModel
from document_insight.infrastructure.department.model import DepartmentModel
from document_insight.infrastructure.document.model import DocumentModel
from document_insight.infrastructure.document_department.model import DocumentDepartmentModel
from document_insight.infrastructure.document_version.model import DocumentVersionModel
from document_insight.infrastructure.entity.model import EntityModel
from document_insight.infrastructure.extracted_document.model import ExtractedDocumentModel
from document_insight.infrastructure.index_generation.model import IndexGenerationModel
from document_insight.infrastructure.ingestion_profile.model import IngestionProfileModel
from document_insight.infrastructure.job.model import JobModel
from document_insight.infrastructure.profile_activation.model import ProfileActivationModel
from document_insight.infrastructure.query_profile.model import (
    QueryProfileEmbeddingCohortModel,
    QueryProfileLexicalCohortModel,
    QueryProfileModel,
)
from document_insight.infrastructure.tenant.model import TenantModel
from document_insight.infrastructure.user.model import UserModel
from document_insight.infrastructure.user_department.model import UserDepartmentModel

__all__ = [
    "DepartmentModel",
    "ActiveProfileModel",
    "CapabilityProfileModel",
    "ChunkModel",
    "ChunkEmbeddingModel",
    "ConfigurationSnapshotModel",
    "DocumentDepartmentModel",
    "DocumentModel",
    "DocumentVersionModel",
    "EntityModel",
    "ExtractedDocumentModel",
    "IndexGenerationModel",
    "IngestionProfileModel",
    "JobModel",
    "ProfileActivationModel",
    "QueryProfileEmbeddingCohortModel",
    "QueryProfileLexicalCohortModel",
    "QueryProfileModel",
    "TenantModel",
    "UserDepartmentModel",
    "UserModel",
]
