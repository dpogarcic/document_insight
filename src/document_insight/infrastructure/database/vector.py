"""Minimal pgvector column type used before a provider adapter is introduced."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.types import UserDefinedType


class PgVector(UserDefinedType[Any]):
    """Compile as PostgreSQL's dimension-agnostic `vector` type.

    Dimensions belong to immutable embedding profiles, so the first embedding table must
    accept multiple profile cohorts without one global vector dimension.
    """

    cache_ok = True

    def get_col_spec(self, **_: object) -> str:
        """Return the pgvector type name for schema generation."""
        return "VECTOR"

    def bind_processor(self, _: object) -> Any:
        """Serialize vectors into pgvector's text input representation."""
        return lambda value: None if value is None else self._serialize(value)

    @staticmethod
    def _serialize(value: Sequence[float]) -> str:
        """Produce one pgvector literal without relying on a provider SDK."""
        return "[" + ",".join(str(component) for component in value) + "]"
