"""Focused query use-case input."""

from dataclasses import dataclass

from document_insight.application.auth.models import AuthorizationContext


@dataclass(frozen=True, slots=True)
class PrepareQueryCommand:
    """Validated user question and optional text to match during retrieval."""

    question: str
    filter_text: str | None
    top_k: int
    actor: AuthorizationContext
