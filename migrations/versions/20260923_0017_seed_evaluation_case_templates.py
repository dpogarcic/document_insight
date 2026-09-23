"""Seed reusable evaluation scenarios without binding them to a corpus or user.

Revision ID: 20260923_0017
Revises: 20260923_0016
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0017"
down_revision: str | None = "20260923_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATES = (
    (
        "document-purpose",
        "Document purpose",
        "What is the main purpose of this document?",
        "answerable",
        "Check that the answer captures the stated purpose and cites a supporting passage.",
        "summary",
    ),
    (
        "specific-fact",
        "Specific fact",
        "What does the document say about [specific topic]?",
        "answerable",
        "Replace the topic with one explicitly covered by the document. Check the exact fact and citation.",
        "fact",
    ),
    (
        "entity-lookup",
        "Named entity",
        "Which [person, organization, or place] is associated with [event or role]?",
        "answerable",
        "Choose an entity and relationship stated in the document. Check the name and cited passage.",
        "entity",
    ),
    (
        "date-number",
        "Date or number",
        "What [date, amount, or quantity] does the document give for [event or item]?",
        "answerable",
        "Choose a stated value. Check its units, context, and source citation.",
        "precision",
    ),
    (
        "cross-passage",
        "Combine passages",
        "How do [fact in passage A] and [fact in passage B] relate?",
        "answerable",
        "Choose two facts from distinct passages. Require citations for both and reject unsupported synthesis.",
        "multi_passage",
    ),
    (
        "qualified-statement",
        "Qualification or exception",
        "What exceptions or conditions apply to [statement]?",
        "answerable",
        "Choose a qualified statement. Check that the answer preserves its limits and cites the qualification.",
        "nuance",
    ),
    (
        "unsupported-fact",
        "Absent information",
        "What is [fact verified absent from the approved corpus]?",
        "unanswerable",
        "Verify the requested fact is absent from every authorized corpus version. The answer should state insufficient evidence without invented facts or citations.",
        "abstention",
    ),
    (
        "false-premise",
        "False premise",
        "Why does the document say [claim verified false or absent]?",
        "unanswerable",
        "Verify the premise is unsupported. The answer should reject the premise and avoid fabricating a reason.",
        "hallucination",
    ),
    (
        "department-denial",
        "Department isolation",
        "What does [document outside this identity's permitted departments] say about [topic]?",
        "unanswerable",
        "Use a non-admin identity without access to that document. Check that restricted content and citations are absent.",
        "authorization",
    ),
    (
        "filter-narrowing",
        "Filter narrowing",
        "What does the document say about [topic]?",
        "answerable",
        "Choose a topic and a narrowing filter. Check that the cited passage meets the filter and authorization scope.",
        "filter",
    ),
)


def upgrade() -> None:
    """Create a reusable catalog; runnable cases are still bound at suite creation."""
    op.create_table(
        "evaluation_case_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("answerability", sa.String(20), nullable=False),
        sa.Column("review_rubric", sa.String(), nullable=False),
        sa.Column("scenario_tag", sa.String(80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    table = sa.table(
        "evaluation_case_templates",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("title", sa.String()),
        sa.column("question", sa.String()),
        sa.column("answerability", sa.String()),
        sa.column("review_rubric", sa.String()),
        sa.column("scenario_tag", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": uuid5(NAMESPACE_URL, f"document-insight:evaluation-template:{key}"),
                "key": key,
                "title": title,
                "question": question,
                "answerability": answerability,
                "review_rubric": rubric,
                "scenario_tag": tag,
                "sort_order": order,
            }
            for order, (key, title, question, answerability, rubric, tag) in enumerate(TEMPLATES)
        ],
    )
    op.execute("GRANT SELECT ON evaluation_case_templates TO di_profile_operator")


def downgrade() -> None:
    """Remove the catalog; immutable suites made from it remain intact."""
    op.drop_table("evaluation_case_templates")
