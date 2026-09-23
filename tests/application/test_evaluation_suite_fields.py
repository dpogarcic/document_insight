"""Suite creation accepts only the fixed, structured case schema."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from document_insight.application.evaluation.exceptions import EvaluationError
from document_insight.application.evaluation.service import EvaluationService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_suite_rejects_unknown_case_keys_before_persistence() -> None:
    repository = AsyncMock()
    service = EvaluationService(
        repository,
        repository,
        repository,
        repository,
        repository,
        repository,
        repository,
    )
    version_id = uuid4()
    case = {
        "question": "What changed?",
        "authorized_identity_id": str(uuid4()),
        "answerability": "answerable",
        "relevance_complete": True,
        "relevant_passage_ids": [f"{version_id}@1:0:20"],
        "tags": {},
        "editable_key": "must not be persisted",
    }
    with pytest.raises(EvaluationError, match="fixed suite fields"):
        await service.create_suite_revision(
            "quality",
            uuid4(),
            (case,),
            uuid4(),
            (version_id,),
        )
    repository.create_revision.assert_not_awaited()
