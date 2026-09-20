"""Focused tests for English/Croatian spaCy language routing and entity mapping."""

import pytest
import spacy
from lingua import Language
from spacy.language import Language as SpacyLanguage

from document_insight.application.processing.models import DocumentLanguage, EntityLabel
from document_insight.infrastructure.ner import spacy as spacy_adapter


class FakeLanguageDetector:
    """Return a configured language without loading statistical detector data."""

    def __init__(self, language: Language) -> None:
        self.language = language

    def detect_language_of(self, _: str) -> Language:
        return self.language


def pipeline(label: str, text: str) -> SpacyLanguage:
    """Build a tiny local spaCy pipeline with one deterministic entity pattern."""
    nlp = spacy.blank("xx")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns([{"label": label, "pattern": text}])
    return nlp


@pytest.mark.parametrize(
    ("detected", "text", "expected_language", "expected_model", "provider_label", "label"),
    [
        (
            Language.ENGLISH,
            "OpenAI",
            DocumentLanguage.ENGLISH,
            "english-model",
            "ORG",
            EntityLabel.ORG,
        ),
        (
            Language.CROATIAN,
            "Zagreb",
            DocumentLanguage.CROATIAN,
            "croatian-model",
            "LOC",
            EntityLabel.LOC,
        ),
        (
            Language.CROATIAN,
            "Ivan Horvat",
            DocumentLanguage.CROATIAN,
            "croatian-model",
            "PER",
            EntityLabel.PERSON,
        ),
    ],
)
def test_spacy_ner_routes_language_and_maps_entity_metadata(
    monkeypatch: pytest.MonkeyPatch,
    detected: Language,
    text: str,
    expected_language: DocumentLanguage,
    expected_model: str,
    provider_label: str,
    label: EntityLabel,
) -> None:
    """Provider output preserves language, model provenance, and canonical labels."""
    models = {
        "english-model": pipeline(provider_label, text),
        "croatian-model": pipeline(provider_label, text),
    }
    monkeypatch.setattr(spacy_adapter.spacy, "load", lambda name: models[name])
    recognizer = spacy_adapter.SpacyNamedEntityRecognizer("english-model", "croatian-model")
    recognizer._detector = FakeLanguageDetector(detected)

    result = recognizer.recognize(text)

    assert result.language is expected_language
    assert result.provider_name == "spacy"
    assert result.model_name == expected_model
    assert result.entities[0].text == text
    assert result.entities[0].normalized_value == text.casefold()
    assert result.entities[0].label == label


def test_spacy_ner_discards_label_outside_rag_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generic numeric entities do not become persisted RAG metadata."""
    models = {
        "english-model": pipeline("CARDINAL", "1234567890"),
        "croatian-model": pipeline("CARDINAL", "1234567890"),
    }
    monkeypatch.setattr(spacy_adapter.spacy, "load", lambda name: models[name])
    recognizer = spacy_adapter.SpacyNamedEntityRecognizer("english-model", "croatian-model")
    recognizer._detector = FakeLanguageDetector(Language.ENGLISH)

    result = recognizer.recognize("1234567890")

    assert result.entities == ()
