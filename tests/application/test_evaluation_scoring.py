"""Offline quality measurements use labelled spans and explicit denominators."""

from uuid import uuid4

import pytest

from document_insight.application.evaluation.scoring import (
    SourceSpan,
    aggregate_metrics,
    citation_metrics,
    retrieval_metrics,
)


def test_retrieval_metrics_use_k_and_complete_gold_denominators() -> None:
    version = uuid4()
    gold = (SourceSpan(version, 2, 10, 20), SourceSpan(version, 2, 80, 90))
    ranked = (
        SourceSpan(version, 2, 8, 22),
        SourceSpan(version, 3, 10, 20),
    )
    metrics = retrieval_metrics(ranked, gold, (1, 5), stage="reranked", complete_relevance_set=True)
    values = {(metric.name, metric.k): metric for metric in metrics}
    assert values["precision", 1].value == 1.0
    assert values["precision", 5].numerator == 1
    assert values["precision", 5].denominator == 5
    assert values["recall", 5].value == 0.5


def test_incomplete_or_unanswerable_cases_do_not_report_recall() -> None:
    version = uuid4()
    gold = (SourceSpan(version, 1, 0, 10),)
    incomplete = retrieval_metrics(
        (gold[0],), gold, (1,), stage="fused", complete_relevance_set=False
    )
    assert [metric.name for metric in incomplete] == ["precision"]
    assert retrieval_metrics((), (), (1,), stage="fused", complete_relevance_set=True) == ()


def test_citation_recall_deduplicates_and_aggregate_counts_are_exact() -> None:
    version = uuid4()
    gold = (SourceSpan(version, 1, 0, 10), SourceSpan(version, 1, 50, 60))
    citations = (gold[0], gold[0], SourceSpan(version, 1, 90, 100))
    metrics = citation_metrics(citations, gold, complete_relevance_set=True)
    values = {metric.name: metric for metric in metrics}
    assert values["citation_precision"].numerator == 1
    assert values["citation_precision"].denominator == 2
    assert values["citation_recall"].numerator == 1
    aggregate = aggregate_metrics((metrics, metrics))
    assert {metric.name: metric for metric in aggregate}["citation_recall"].denominator == 4


def test_source_span_rejects_invalid_offsets() -> None:
    with pytest.raises(ValueError):
        SourceSpan(uuid4(), 1, 10, 10)
