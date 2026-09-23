"""Deterministic offline scoring against approved, version-stable source spans."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A page-local span in one immutable source document version."""

    document_version_id: UUID
    page_number: int
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        if self.page_number < 1 or self.start_offset < 0 or self.end_offset <= self.start_offset:
            raise ValueError("Source span page and offsets are invalid")

    @classmethod
    def parse(cls, value: str) -> "SourceSpan":
        """Read an anchor in `version@page:start:end` form."""
        version, rest = value.split("@", 1)
        page, start, end = rest.split(":", 2)
        return cls(UUID(version), int(page), int(start), int(end))

    def encode(self) -> str:
        """Return a stable label independent of chunk and embedding identifiers."""
        return (
            f"{self.document_version_id}@{self.page_number}:{self.start_offset}:{self.end_offset}"
        )


@dataclass(frozen=True, slots=True)
class ScoredMetric:
    """One auditable numerator and denominator for a stage and K."""

    name: str
    stage: str
    k: int | None
    numerator: int
    denominator: int
    value: float
    definition: str
    cohort_id: UUID | None = None


def _covers(candidate: SourceSpan, gold: SourceSpan) -> bool:
    """Treat a chunk as relevant when it covers at least half a labelled span."""
    if (
        candidate.document_version_id != gold.document_version_id
        or candidate.page_number != gold.page_number
    ):
        return False
    overlap = max(
        0,
        min(candidate.end_offset, gold.end_offset) - max(candidate.start_offset, gold.start_offset),
    )
    return overlap * 2 >= gold.end_offset - gold.start_offset


def retrieval_metrics(
    ranked: tuple[SourceSpan, ...],
    gold: tuple[SourceSpan, ...],
    k_values: tuple[int, ...],
    *,
    stage: str,
    complete_relevance_set: bool,
    cohort_id: UUID | None = None,
) -> tuple[ScoredMetric, ...]:
    """Compute P@K and eligible R@K with fixed-K denominators.

    Cases lacking a complete relevance set cannot support Recall@K. An empty
    relevance set belongs to answerability evaluation, not retrieval scoring.
    """
    if not gold:
        return ()
    if any(k < 1 for k in k_values) or len(set(k_values)) != len(k_values):
        raise ValueError("K values must be distinct positive integers")
    result: list[ScoredMetric] = []
    for k in k_values:
        top = ranked[:k]
        relevant_candidates = sum(
            1 for candidate in top if any(_covers(candidate, label) for label in gold)
        )
        result.append(
            ScoredMetric(
                "precision",
                stage,
                k,
                relevant_candidates,
                k,
                relevant_candidates / k,
                "Relevant ranked passages among the first K divided by K.",
                cohort_id,
            )
        )
        if complete_relevance_set:
            covered_labels = sum(
                1 for label in gold if any(_covers(candidate, label) for candidate in top)
            )
            result.append(
                ScoredMetric(
                    "recall",
                    stage,
                    k,
                    covered_labels,
                    len(gold),
                    covered_labels / len(gold),
                    "Labelled relevant source spans covered in the first K divided by all labelled relevant spans.",
                    cohort_id,
                )
            )
    return tuple(result)


def citation_metrics(
    citations: tuple[SourceSpan, ...],
    gold: tuple[SourceSpan, ...],
    *,
    complete_relevance_set: bool,
) -> tuple[ScoredMetric, ...]:
    """Score cited evidence, counting a duplicate citation only once for recall."""
    if not gold:
        return ()
    distinct_citations = tuple(dict.fromkeys(citations))
    result: list[ScoredMetric] = []
    if distinct_citations:
        relevant = sum(
            1 for citation in distinct_citations if any(_covers(citation, label) for label in gold)
        )
        result.append(
            ScoredMetric(
                "citation_precision",
                "citation",
                None,
                relevant,
                len(distinct_citations),
                relevant / len(distinct_citations),
                "Distinct relevant citations divided by all distinct citations.",
            )
        )
    if complete_relevance_set:
        covered = sum(
            1 for label in gold if any(_covers(citation, label) for citation in distinct_citations)
        )
        result.append(
            ScoredMetric(
                "citation_recall",
                "citation",
                None,
                covered,
                len(gold),
                covered / len(gold),
                "Labelled relevant source spans covered by citations divided by all labelled relevant spans.",
            )
        )
    return tuple(result)


def aggregate_metrics(
    cases: tuple[tuple[ScoredMetric, ...], ...],
) -> tuple[ScoredMetric, ...]:
    """Micro-average auditable counts for matching stage, cohort, metric, and K."""
    grouped: dict[tuple[str, str, int | None, UUID | None], list[ScoredMetric]] = {}
    for metrics in cases:
        for metric in metrics:
            key = (metric.name, metric.stage, metric.k, metric.cohort_id)
            grouped.setdefault(key, []).append(metric)
    result: list[ScoredMetric] = []
    for values in grouped.values():
        first = values[0]
        numerator = sum(item.numerator for item in values)
        denominator = sum(item.denominator for item in values)
        result.append(
            ScoredMetric(
                first.name,
                first.stage,
                first.k,
                numerator,
                denominator,
                numerator / denominator,
                first.definition,
                first.cohort_id,
            )
        )
    return tuple(result)
