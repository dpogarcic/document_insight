"""Typed results exchanged by document parsing adapters and workers."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Text extracted from one immutable document version."""

    text: str
    page_count: int
    parser_name: str
    parser_version: str


class DocumentLanguage(StrEnum):
    """Languages supported by the initial local NER provider."""

    ENGLISH = "en"
    CROATIAN = "hr"


class EntityLabel(StrEnum):
    """Canonical entity labels retained as useful RAG metadata."""

    PERSON = "PERSON"
    ORG = "ORG"
    GPE = "GPE"
    LOC = "LOC"
    PRODUCT = "PRODUCT"
    EVENT = "EVENT"
    DATE = "DATE"


@dataclass(frozen=True, slots=True)
class NamedEntity:
    """One allowlisted entity mention returned by the configured NER provider."""

    text: str
    normalized_value: str
    label: EntityLabel


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    """One deduplicated entity fact retained for a document version."""

    display_value: str
    normalized_value: str
    label: EntityLabel
    occurrence_count: int


def canonicalize_entities(entities: tuple[NamedEntity, ...]) -> tuple[CanonicalEntity, ...]:
    """Collapse repeated label/value pairs while retaining their first display form."""
    counts: dict[tuple[EntityLabel, str], int] = {}
    display_values: dict[tuple[EntityLabel, str], str] = {}
    for entity in entities:
        key = (entity.label, entity.normalized_value)
        counts[key] = counts.get(key, 0) + 1
        display_values.setdefault(key, entity.text)
    return tuple(
        CanonicalEntity(
            display_value=display_values[(label, normalized_value)],
            normalized_value=normalized_value,
            label=label,
            occurrence_count=occurrence_count,
        )
        for (label, normalized_value), occurrence_count in counts.items()
    )


@dataclass(frozen=True, slots=True)
class NerResult:
    """Language and entity mentions produced by one configured NER model."""

    language: DocumentLanguage
    provider_name: str
    model_name: str
    entities: tuple[NamedEntity, ...]
