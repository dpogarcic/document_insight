"""SQLAlchemy activation audit adapter."""

from sqlalchemy.ext.asyncio import AsyncSession

from document_insight.infrastructure.profile_activation.model import ProfileActivationModel
from document_insight.infrastructure.profile_activation.protocol import (
    CreateProfileActivation,
    ProfileActivationRepository,
)


class SqlAlchemyProfileActivationRepository(ProfileActivationRepository):
    """Append one audit row per successful platform profile switch."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, activation: CreateProfileActivation) -> None:
        """Add an audit row within the caller's transaction."""
        self._session.add(
            ProfileActivationModel(
                scope=activation.scope,
                profile_kind=activation.kind,
                previous_profile_id=activation.previous_profile_id,
                new_profile_id=activation.new_profile_id,
                actor_id=activation.actor_id,
                reason=activation.reason,
                active_profile_revision=activation.revision,
            )
        )
