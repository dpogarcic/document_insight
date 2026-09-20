"""Local English/Croatian NER adapter backed by spaCy pipelines."""

import spacy
from lingua import Language, LanguageDetector, LanguageDetectorBuilder
from spacy.language import Language as SpacyLanguage

from document_insight.application.processing.exceptions import NerError
from document_insight.application.processing.models import (
    DocumentLanguage,
    EntityLabel,
    NamedEntity,
    NerResult,
)
from document_insight.infrastructure.ner.protocol import NamedEntityRecognizer

RAG_ENTITY_LABEL_ALLOWLIST = frozenset(EntityLabel)
_SPACY_LABEL_ALIASES = {"PER": EntityLabel.PERSON}


def _canonical_label(label: str) -> EntityLabel | None:
    """Map provider labels to the canonical RAG allowlist."""
    if alias := _SPACY_LABEL_ALIASES.get(label):
        return alias
    try:
        canonical = EntityLabel(label)
    except ValueError:
        return None
    return canonical if canonical in RAG_ENTITY_LABEL_ALLOWLIST else None


class SpacyNamedEntityRecognizer(NamedEntityRecognizer):
    """Route English and Croatian text to explicitly configured local models."""

    def __init__(self, english_model: str, croatian_model: str) -> None:
        try:
            self._models: dict[DocumentLanguage, SpacyLanguage] = {
                DocumentLanguage.ENGLISH: spacy.load(english_model),
                DocumentLanguage.CROATIAN: spacy.load(croatian_model),
            }
        except (ImportError, OSError) as error:
            raise NerError from error
        self._model_names = {
            DocumentLanguage.ENGLISH: english_model,
            DocumentLanguage.CROATIAN: croatian_model,
        }
        self._detector: LanguageDetector = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH, Language.CROATIAN
        ).build()

    def recognize(self, text: str) -> NerResult:
        """Detect one supported language and return normalized entity spans."""
        detected = self._detector.detect_language_of(text)
        language = (
            DocumentLanguage.CROATIAN if detected is Language.CROATIAN else DocumentLanguage.ENGLISH
        )
        try:
            document = self._models[language](text)
        except (RuntimeError, ValueError) as error:
            raise NerError from error
        entities: list[NamedEntity] = []
        for entity in document.ents:
            label = _canonical_label(entity.label_)
            if label is None:
                continue
            entities.append(
                NamedEntity(
                    text=entity.text,
                    normalized_value=" ".join(entity.text.casefold().split()),
                    label=label,
                )
            )
        return NerResult(language, "spacy", self._model_names[language], tuple(entities))
