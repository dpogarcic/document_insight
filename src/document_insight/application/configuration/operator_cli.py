"""Private platform-operator CLI for manual profile approval and activation."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from document_insight.application.configuration.approval import ProfileApprovalService
from document_insight.application.configuration.exceptions import (
    InvalidProfileProposalError,
    ProfileRevisionConflictError,
)
from document_insight.application.configuration.models import Capability
from document_insight.config import get_settings
from document_insight.infrastructure.active_profile.repository import (
    SqlAlchemyActiveProfileRepository,
)
from document_insight.infrastructure.capability_profile.repository import (
    SqlAlchemyCapabilityProfileRepository,
)
from document_insight.infrastructure.configuration_snapshot.repository import (
    SqlAlchemyConfigurationSnapshotRepository,
)
from document_insight.infrastructure.database.session import get_session_factory
from document_insight.infrastructure.database.transaction import SqlAlchemyTransactionManager
from document_insight.infrastructure.index_generation.repository import (
    SqlAlchemyIndexGenerationRepository,
)
from document_insight.infrastructure.ingestion_profile.repository import (
    SqlAlchemyIngestionProfileRepository,
)
from document_insight.infrastructure.profile_activation.repository import (
    SqlAlchemyProfileActivationRepository,
)
from document_insight.infrastructure.query_profile.repository import (
    SqlAlchemyQueryProfileRepository,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage immutable platform RAG profiles")
    commands = parser.add_subparsers(dest="command", required=True)
    capability = commands.add_parser("create-capability")
    capability.add_argument(
        "--capability", required=True, choices=[item.value for item in Capability]
    )
    capability.add_argument("--name", required=True)
    capability.add_argument("--config-file", required=True, type=Path)
    validate = commands.add_parser("validate-capability")
    validate.add_argument("profile_id", type=UUID)
    ingestion = commands.add_parser("create-ingestion")
    for name in ("ner", "chunking", "lexical", "embedding"):
        ingestion.add_argument(f"--{name}", required=True, type=UUID)
    query = commands.add_parser("create-query")
    query.add_argument("--lexical", required=True, nargs="+", type=UUID)
    query.add_argument("--embedding", required=True, nargs="+", type=UUID)
    query.add_argument("--reranker", required=True, type=UUID)
    query.add_argument("--generation", required=True, type=UUID)
    query.add_argument("--retrieval-file", required=True, type=Path)
    activate = commands.add_parser("activate")
    activate.add_argument("--kind", required=True, choices=("ingestion", "query"))
    activate.add_argument("--profile-id", required=True, type=UUID)
    activate.add_argument("--expected-revision", required=True, type=int)
    activate.add_argument("--actor-id", required=True, type=UUID)
    activate.add_argument("--reason", required=True)
    commands.add_parser("show-active")
    for name in ("show-capability", "show-ingestion", "show-query"):
        commands.add_parser(name).add_argument("profile_id", type=UUID)
    return parser


def _json_file(path: Path) -> dict[str, Any]:
    """Load a configuration object without printing its raw contents on errors."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InvalidProfileProposalError(
            "Configuration file is unreadable or invalid JSON"
        ) from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise InvalidProfileProposalError("Configuration must be a JSON object")
    return value


async def _run(args: argparse.Namespace) -> None:
    """Execute one operator action with a restricted control-plane credential."""
    settings = get_settings()
    async with get_session_factory("profile_operator")() as session:
        snapshots = SqlAlchemyConfigurationSnapshotRepository(session)
        capabilities = SqlAlchemyCapabilityProfileRepository(session)
        ingestions = SqlAlchemyIngestionProfileRepository(session)
        queries = SqlAlchemyQueryProfileRepository(session)
        active = SqlAlchemyActiveProfileRepository(session)
        service = ProfileApprovalService(
            snapshots,
            capabilities,
            ingestions,
            queries,
            active,
            SqlAlchemyIndexGenerationRepository(session),
            SqlAlchemyProfileActivationRepository(session),
            SqlAlchemyTransactionManager(session),
            bool(settings.mistral_api_key and settings.mistral_api_key.get_secret_value()),
        )
        if args.command == "create-capability":
            result: UUID | int = await service.create_capability(
                Capability(args.capability), args.name, _json_file(args.config_file)
            )
        elif args.command == "validate-capability":
            await service.validate_capability(args.profile_id)
            result = args.profile_id
        elif args.command == "create-ingestion":
            result = await service.create_ingestion(
                args.ner, args.chunking, args.lexical, args.embedding
            )
        elif args.command == "create-query":
            result = await service.create_query(
                tuple(args.lexical),
                tuple(args.embedding),
                args.reranker,
                args.generation,
                _json_file(args.retrieval_file),
            )
        elif args.command == "activate":
            result = await service.activate(
                args.kind, args.profile_id, args.expected_revision, args.actor_id, args.reason
            )
        elif args.command == "show-capability":
            capability_profile = await capabilities.get(args.profile_id)
            if capability_profile is None:
                raise InvalidProfileProposalError("Capability profile not found")
            snapshot = await snapshots.get(capability_profile.configuration_snapshot_id)
            if snapshot is None:
                raise InvalidProfileProposalError("Capability snapshot not found")
            print(
                json.dumps(
                    {
                        "profile_id": str(capability_profile.profile_id),
                        "capability": capability_profile.capability,
                        "status": capability_profile.status,
                        "configuration": snapshot.configuration,
                    },
                    sort_keys=True,
                )
            )
            return
        elif args.command == "show-ingestion":
            ingestion_profile = await ingestions.get(args.profile_id)
            if ingestion_profile is None:
                raise InvalidProfileProposalError("Ingestion profile not found")
            print(
                json.dumps(
                    {
                        "profile_id": str(ingestion_profile.ingestion_profile_id),
                        "ner": str(ingestion_profile.ner_profile_id),
                        "chunking": str(ingestion_profile.chunking_profile_id),
                        "lexical": str(ingestion_profile.lexical_profile_id),
                        "embedding": str(ingestion_profile.embedding_profile_id),
                    },
                    sort_keys=True,
                )
            )
            return
        elif args.command == "show-query":
            query_profile = await queries.get(args.profile_id)
            if query_profile is None:
                raise InvalidProfileProposalError("Query profile not found")
            retrieval = await snapshots.get(query_profile.retrieval_snapshot_id)
            if retrieval is None:
                raise InvalidProfileProposalError("Retrieval snapshot not found")
            print(
                json.dumps(
                    {
                        "profile_id": str(query_profile.query_profile_id),
                        "lexical_cohorts": [
                            str(value) for value in query_profile.lexical_profile_ids
                        ],
                        "embedding_cohorts": [
                            str(value) for value in query_profile.embedding_profile_ids
                        ],
                        "reranker": str(query_profile.reranker_profile_id),
                        "generation": str(query_profile.generation_profile_id),
                        "retrieval": retrieval.configuration,
                    },
                    sort_keys=True,
                )
            )
            return
        else:
            ingestion = await active.lock("platform", "ingestion")
            query = await active.lock("platform", "query")
            print(
                json.dumps(
                    {
                        "ingestion": None
                        if ingestion is None
                        else {
                            "profile_id": str(ingestion.profile_id),
                            "revision": ingestion.revision,
                        },
                        "query": None
                        if query is None
                        else {
                            "profile_id": str(query.profile_id),
                            "revision": query.revision,
                        },
                    }
                )
            )
            return
        print(result)


def main() -> None:
    """Map expected proposal failures to concise operator-facing errors."""
    args = _parser().parse_args()
    try:
        asyncio.run(_run(args))
    except (InvalidProfileProposalError, ProfileRevisionConflictError) as error:
        raise SystemExit(str(error) or "Active profile revision changed; review again") from error


if __name__ == "__main__":
    main()
