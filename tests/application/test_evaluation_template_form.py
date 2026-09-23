"""The suite form exposes the seeded scenarios without trusting their HTML text."""

from uuid import uuid4

from document_insight.admin_panel.views import list_suites, suite_form
from document_insight.infrastructure.evaluation_case_template.protocol import EvaluationCaseTemplate


def test_suite_form_escapes_template_values() -> None:
    template = EvaluationCaseTemplate(
        uuid4(),
        "sample",
        "Purpose <script>",
        "What is <this>?",
        "answerable",
        "Check <source>",
        "summary",
    )
    page = suite_form("csrf", (template,))
    assert "Purpose &lt;script&gt;" in page
    assert 'data-question="What is &lt;this&gt;?"' in page
    assert "Purpose <script>" not in page
    assert 'data-tag="summary"' in page
    assert "Saving does not start a run." in page
    assert "This enables recall scores" in page
    assert "answer quality is scored manually" in page
    assert "Show saved case data" in page
    assert "Upload test documents" in page
    assert "data-corpus-choice" in page
    assert "data-refresh-corpus" in page
    assert '<textarea name="corpus_version_ids_json"' not in page
    assert 'target="_blank" rel="noopener"' in page


def test_evaluation_index_lists_seeded_scenarios_with_creation_links() -> None:
    template = EvaluationCaseTemplate(
        uuid4(),
        "document-purpose",
        "Document purpose",
        "What is its purpose?",
        "answerable",
        "Check cited purpose.",
        "summary",
    )
    page = list_suites((), "csrf", (template,))
    assert "Baseline scenarios" in page
    assert "Document purpose" in page
    assert "/evaluations/suites/new?template=document-purpose" in page
