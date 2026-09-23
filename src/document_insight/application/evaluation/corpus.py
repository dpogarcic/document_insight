"""Validate an immutable, authorized test corpus before scoring any candidate."""

from uuid import UUID

from document_insight.application.auth.models import UserRole
from document_insight.application.evaluation.executor import EvaluationActorLoader
from document_insight.application.evaluation.models import EvaluationCorpusManifest
from document_insight.application.ingestion.models import DocumentVersionStatus
from document_insight.infrastructure.document.protocol import DocumentRepository
from document_insight.infrastructure.document_version.protocol import DocumentVersionRepository
from document_insight.infrastructure.evaluation_suite.protocol import EvaluationSuiteRevision
from document_insight.infrastructure.index_generation.protocol import IndexGenerationRepository


class EvaluationCorpusValidator:
    """Validate selected documents under a current admin's tenant RLS scope."""

    def __init__(
        self,
        actors: EvaluationActorLoader,
        documents: DocumentRepository,
        versions: DocumentVersionRepository,
        generations: IndexGenerationRepository,
        tenant_id: UUID,
    ) -> None:
        self._actors = actors
        self._documents = documents
        self._versions = versions
        self._generations = generations
        self._tenant_id = tenant_id

    async def validate(
        self, suite: EvaluationSuiteRevision, manifest: EvaluationCorpusManifest
    ) -> None:
        """Reject stale, foreign, unactivated, or incorrectly indexed test documents."""
        if not suite.test_cases:
            raise ValueError("Evaluation suite has no cases")
        actor = await self._actors.load(suite.test_cases[0].authorized_identity_id)
        if actor.tenant_id != self._tenant_id or actor.role is not UserRole.TENANT_ADMIN:
            raise ValueError(
                "The first suite case must use an administrator of the selected tenant"
            )
        if suite.evaluation_tenant_id != self._tenant_id:
            raise ValueError("Evaluation suite tenant does not match the selected tenant")
        for corpus, ingestion_id in (
            (manifest.baseline, manifest.baseline_ingestion_profile_id),
            (manifest.candidate, manifest.candidate_ingestion_profile_id),
        ):
            for version_id in corpus.version_ids:
                document_id = await self._versions.get_document_id(version_id, self._tenant_id)
                if document_id is None:
                    raise ValueError("Evaluation corpus version is outside the test tenant")
                version = await self._versions.get_for_activation(version_id, self._tenant_id)
                if version is None or version.status is not DocumentVersionStatus.READY:
                    raise ValueError("Evaluation corpus version must be ready")
                current = await self._documents.get_current_ready_version_id(
                    document_id, self._tenant_id
                )
                if current != version_id:
                    raise ValueError("Evaluation corpus version must be activated")
                if ingestion_id is not None and not await self._generations.has_ready_generation(
                    version_id, self._tenant_id, ingestion_id
                ):
                    raise ValueError("Evaluation corpus was not indexed by its declared profile")
        for indexed_id, source_id in manifest.candidate.source_versions.items():
            indexed_hash = await self._versions.get_content_sha256(indexed_id, self._tenant_id)
            source_hash = await self._versions.get_content_sha256(source_id, self._tenant_id)
            if indexed_hash is None or indexed_hash != source_hash:
                raise ValueError("Candidate copy differs from its approved source document")
