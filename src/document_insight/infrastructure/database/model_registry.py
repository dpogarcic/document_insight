"""Import every ORM model so shared SQLAlchemy metadata is complete."""

from document_insight.infrastructure.department.model import DepartmentModel
from document_insight.infrastructure.document.model import DocumentModel
from document_insight.infrastructure.document_department.model import DocumentDepartmentModel
from document_insight.infrastructure.document_version.model import DocumentVersionModel
from document_insight.infrastructure.entity.model import EntityModel
from document_insight.infrastructure.extracted_document.model import ExtractedDocumentModel
from document_insight.infrastructure.job.model import JobModel
from document_insight.infrastructure.tenant.model import TenantModel
from document_insight.infrastructure.user.model import UserModel
from document_insight.infrastructure.user_department.model import UserDepartmentModel

__all__ = [
    "DepartmentModel",
    "DocumentDepartmentModel",
    "DocumentModel",
    "DocumentVersionModel",
    "EntityModel",
    "ExtractedDocumentModel",
    "JobModel",
    "TenantModel",
    "UserDepartmentModel",
    "UserModel",
]
