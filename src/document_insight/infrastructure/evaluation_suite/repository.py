"""SQLAlchemy repository for immutable evaluation suite revisions."""

from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.evaluation_suite.model import EvaluationSuiteRevisionModel
from document_insight.infrastructure.evaluation_suite.protocol import (
    EvaluationSuiteRepository,
    EvaluationSuiteRevision,
)


class SqlAlchemyEvaluationSuiteRepository(EvaluationSuiteRepository):
    """Own suite metadata without writing the associated case rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_revision(self, revision_id: UUID) -> EvaluationSuiteRevision | None:
        model = await self._session.scalar(
            select(EvaluationSuiteRevisionModel).where(
                EvaluationSuiteRevisionModel.id == revision_id
            )
        )
        return None if model is None else self._to_revision(model)

    async def list_revisions(
        self, suite_name: str, tenant_id: UUID | None = None
    ) -> tuple[EvaluationSuiteRevision, ...]:
        stmt = select(EvaluationSuiteRevisionModel)
        if suite_name:
            stmt = stmt.where(EvaluationSuiteRevisionModel.suite_name == suite_name)
        if tenant_id is not None:
            stmt = stmt.where(EvaluationSuiteRevisionModel.evaluation_tenant_id == tenant_id)
        models = await self._session.scalars(
            stmt.order_by(EvaluationSuiteRevisionModel.created_at.desc())
        )
        return tuple(self._to_revision(model) for model in models)

    async def create_revision(
        self,
        suite_name: str,
        created_by: UUID,
        evaluation_tenant_id: UUID,
        corpus_version_ids: tuple[UUID, ...],
        dataset_fingerprint: str,
    ) -> UUID:
        latest = await self._session.scalar(
            select(EvaluationSuiteRevisionModel.revision_number)
            .where(
                EvaluationSuiteRevisionModel.suite_name == suite_name,
                EvaluationSuiteRevisionModel.evaluation_tenant_id == evaluation_tenant_id,
            )
            .order_by(EvaluationSuiteRevisionModel.revision_number.desc())
        )
        revision_id = uuid4()
        self._session.add(
            EvaluationSuiteRevisionModel(
                id=revision_id,
                suite_name=suite_name,
                revision_number=(latest or 0) + 1,
                created_by=created_by,
                evaluation_tenant_id=evaluation_tenant_id,
                corpus_version_ids=[str(value) for value in corpus_version_ids],
                dataset_fingerprint=dataset_fingerprint,
            )
        )
        await self._session.flush()
        return revision_id

    async def get_active_revision(
        self, suite_name: str, tenant_id: UUID
    ) -> EvaluationSuiteRevision | None:
        model = await self._session.scalar(
            select(EvaluationSuiteRevisionModel).where(
                EvaluationSuiteRevisionModel.suite_name == suite_name,
                EvaluationSuiteRevisionModel.is_active.is_(True),
                EvaluationSuiteRevisionModel.evaluation_tenant_id == tenant_id,
            )
        )
        return None if model is None else self._to_revision(model)

    async def set_active_revision(
        self, revision_id: UUID, suite_name: str, tenant_id: UUID
    ) -> None:
        selected = await self._session.scalar(
            select(EvaluationSuiteRevisionModel.id).where(
                EvaluationSuiteRevisionModel.id == revision_id,
                EvaluationSuiteRevisionModel.suite_name == suite_name,
                EvaluationSuiteRevisionModel.evaluation_tenant_id == tenant_id,
            )
        )
        if selected is None:
            raise ValueError("Suite revision does not belong to the selected tenant")
        await self._session.execute(
            update(EvaluationSuiteRevisionModel)
            .where(
                EvaluationSuiteRevisionModel.id == revision_id,
                EvaluationSuiteRevisionModel.suite_name == suite_name,
                EvaluationSuiteRevisionModel.evaluation_tenant_id == tenant_id,
            )
            .values(is_active=True)
        )
        await self._session.execute(
            update(EvaluationSuiteRevisionModel)
            .where(
                EvaluationSuiteRevisionModel.suite_name == suite_name,
                EvaluationSuiteRevisionModel.evaluation_tenant_id == tenant_id,
                EvaluationSuiteRevisionModel.id != revision_id,
            )
            .values(is_active=False)
        )

    @staticmethod
    def _to_revision(model: EvaluationSuiteRevisionModel) -> EvaluationSuiteRevision:
        return EvaluationSuiteRevision(
            revision_id=model.id,
            suite_name=model.suite_name,
            revision_number=model.revision_number,
            created_by=model.created_by,
            created_at=model.created_at.isoformat(),
            test_cases=(),
            evaluation_tenant_id=model.evaluation_tenant_id,
            corpus_version_ids=tuple(UUID(value) for value in model.corpus_version_ids),
            dataset_fingerprint=model.dataset_fingerprint,
        )
