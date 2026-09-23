"""Add evaluation suite, run, and gate review tables.

Revision ID: 20260923_0014
Revises: 20260923_0013_profile_operator
Create Date: 2026-09-23 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0014"
down_revision: str | None = "20260923_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Evaluation suite revisions
    op.create_table(
        "evaluation_suite_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("suite_name", sa.String(200), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("evaluation_tenant_id", sa.Uuid(), nullable=False),
        sa.Column("corpus_version_ids", sa.JSON(), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint("suite_name", "revision_number", name="uq_evaluation_suite_revision"),
    )

    # Evaluation test cases
    op.create_table(
        "evaluation_test_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "suite_revision_id",
            sa.Uuid(),
            sa.ForeignKey("evaluation_suite_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("filter_text", sa.String(), nullable=True),
        sa.Column("authorized_identity_id", sa.Uuid(), nullable=False),
        sa.Column("answerability", sa.String(20), nullable=False),
        sa.Column("expected_facts", sa.JSON(), nullable=True),
        sa.Column("review_rubric", sa.String(), nullable=True),
        sa.Column("tags", sa.JSON(), default={}, nullable=False),
        sa.Column("relevant_passage_ids", sa.JSON(), default=[], nullable=False),
        sa.Column("relevance_complete", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), default=0, nullable=False),
    )
    op.create_index(
        "ix_evaluation_test_cases_suite_revision_id",
        "evaluation_test_cases",
        ["suite_revision_id"],
    )

    # Evaluation runs
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "suite_revision_id",
            sa.Uuid(),
            sa.ForeignKey("evaluation_suite_revisions.id"),
            nullable=False,
        ),
        sa.Column("corpus_manifest", sa.JSON(), default={}, nullable=False),
        sa.Column("baseline_profile_ids", sa.JSON(), default=[], nullable=False),
        sa.Column("candidate_profile_ids", sa.JSON(), default=[], nullable=False),
        sa.Column("config_fingerprints", sa.JSON(), default={}, nullable=False),
        sa.Column("read_cohorts", sa.JSON(), default={}, nullable=False),
        sa.Column("candidate_component_profiles", sa.JSON(), nullable=True),
        sa.Column("evaluator_version", sa.String(50), nullable=False),
        sa.Column("k_values", sa.JSON(), default=[], nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_mode", sa.String(20), default="query", nullable=False),
        sa.Column("status", sa.String(20), default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("comparison_valid", sa.Boolean(), default=True, nullable=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_evaluation_runs_suite_revision_id",
        "evaluation_runs",
        ["suite_revision_id"],
    )

    # Evaluation case results
    op.create_table(
        "evaluation_case_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("variant", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), default="pending", nullable=False),
        sa.Column("lexical_ranked_ids", sa.JSON(), default=[], nullable=False),
        sa.Column("lexical_cohort_ranked_ids", sa.JSON(), default={}, nullable=False),
        sa.Column("vector_cohort_ranked_ids", sa.JSON(), default={}, nullable=False),
        sa.Column("vector_combined_ranked_ids", sa.JSON(), default=[], nullable=False),
        sa.Column("fused_ranked_ids", sa.JSON(), default=[], nullable=False),
        sa.Column("reranked_ranked_ids", sa.JSON(), default=[], nullable=False),
        sa.Column("final_citations", sa.JSON(), default=[], nullable=False),
        sa.Column("answer_text", sa.String(), nullable=True),
        sa.Column("answerability_outcome", sa.String(), nullable=True),
        sa.Column("provider_errors", sa.JSON(), default=[], nullable=False),
        sa.Column("stage_latencies_ms", sa.JSON(), default={}, nullable=False),
        sa.Column("measurements", sa.JSON(), default=[], nullable=False),
        sa.Column("answer_quality_score", sa.Float(), nullable=True),
        sa.Column("answer_quality_note", sa.String(2000), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_evaluation_case_results_run_id",
        "evaluation_case_results",
        ["run_id"],
    )
    op.create_unique_constraint(
        "uq_evaluation_case_variant", "evaluation_case_results", ["run_id", "case_id", "variant"]
    )

    # Aggregate measurements
    op.create_table(
        "evaluation_aggregates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("variant", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("k", sa.Integer(), nullable=True),
        sa.Column("cohort_id", sa.Uuid(), nullable=True),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("case_count", sa.Integer(), default=0, nullable=False),
        sa.Column("numerator", sa.Integer(), nullable=True),
        sa.Column("denominator", sa.Integer(), nullable=True),
        sa.Column("definition", sa.String(500), nullable=False),
    )
    op.create_index(
        "ix_evaluation_aggregates_run_id",
        "evaluation_aggregates",
        ["run_id"],
    )

    # Gate reviews
    op.create_table(
        "evaluation_gate_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("reviewed_run_id", sa.Uuid(), nullable=False),
        sa.Column("threshold_revision", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        "GRANT SELECT, INSERT ON evaluation_suite_revisions, evaluation_test_cases, "
        "evaluation_runs, evaluation_case_results, evaluation_aggregates, "
        "evaluation_gate_reviews TO di_profile_operator"
    )
    op.execute(
        "GRANT UPDATE (is_active) ON evaluation_suite_revisions TO di_profile_operator"
    )
    op.execute(
        "GRANT UPDATE (status, started_at, completed_at, error_message, enqueued_at, "
        "heartbeat_at, comparison_valid) ON evaluation_runs TO di_profile_operator"
    )
    op.execute(
        "GRANT UPDATE (answer_quality_score, answer_quality_note) "
        "ON evaluation_case_results TO di_profile_operator"
    )
    op.execute("GRANT INSERT ON active_profiles TO di_profile_operator")


def downgrade() -> None:
    op.drop_table("evaluation_gate_reviews")
    op.drop_table("evaluation_aggregates")
    op.drop_table("evaluation_case_results")
    op.drop_table("evaluation_runs")
    op.drop_table("evaluation_test_cases")
    op.drop_table("evaluation_suite_revisions")
