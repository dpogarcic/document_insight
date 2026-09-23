"""Upgrade early evaluation tables without discarding existing run history.

Revision ID: 20260923_0015
Revises: 20260923_0014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0015"
down_revision: str | None = "20260923_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add reproducibility, manual quality, and queue fields to older local installs."""
    op.execute("ALTER TABLE evaluation_suite_revisions ADD COLUMN IF NOT EXISTS evaluation_tenant_id uuid")
    op.execute("ALTER TABLE evaluation_suite_revisions ADD COLUMN IF NOT EXISTS corpus_version_ids json")
    op.execute("ALTER TABLE evaluation_suite_revisions ADD COLUMN IF NOT EXISTS dataset_fingerprint varchar(64)")
    # Early scaffold rows cannot prove a test tenant or corpus. A zero sentinel keeps
    # their history readable while the application refuses to run or approve them.
    op.execute("UPDATE evaluation_suite_revisions SET evaluation_tenant_id = '00000000-0000-0000-0000-000000000000' WHERE evaluation_tenant_id IS NULL")
    op.execute("UPDATE evaluation_suite_revisions SET corpus_version_ids = '[]'::json WHERE corpus_version_ids IS NULL")
    op.execute("UPDATE evaluation_suite_revisions SET dataset_fingerprint = repeat('0', 64) WHERE dataset_fingerprint IS NULL")
    op.execute("ALTER TABLE evaluation_suite_revisions ALTER COLUMN evaluation_tenant_id SET NOT NULL")
    op.execute("ALTER TABLE evaluation_suite_revisions ALTER COLUMN corpus_version_ids SET NOT NULL")
    op.execute("ALTER TABLE evaluation_suite_revisions ALTER COLUMN dataset_fingerprint SET NOT NULL")

    op.execute("ALTER TABLE evaluation_test_cases ADD COLUMN IF NOT EXISTS relevance_complete boolean")
    op.execute("UPDATE evaluation_test_cases SET relevance_complete = false WHERE relevance_complete IS NULL")
    op.execute("ALTER TABLE evaluation_test_cases ALTER COLUMN relevance_complete SET NOT NULL")

    op.execute("ALTER TABLE evaluation_runs ADD COLUMN IF NOT EXISTS enqueued_at timestamptz")
    op.execute("ALTER TABLE evaluation_runs ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz")

    op.execute("ALTER TABLE evaluation_case_results ADD COLUMN IF NOT EXISTS variant varchar(20)")
    op.execute("ALTER TABLE evaluation_case_results ADD COLUMN IF NOT EXISTS lexical_cohort_ranked_ids json")
    op.execute("ALTER TABLE evaluation_case_results ADD COLUMN IF NOT EXISTS measurements json")
    op.execute("ALTER TABLE evaluation_case_results ADD COLUMN IF NOT EXISTS answer_quality_score double precision")
    op.execute("ALTER TABLE evaluation_case_results ADD COLUMN IF NOT EXISTS answer_quality_note varchar(2000)")
    op.execute("UPDATE evaluation_case_results SET variant = 'legacy' WHERE variant IS NULL")
    op.execute("UPDATE evaluation_case_results SET lexical_cohort_ranked_ids = '{}'::json WHERE lexical_cohort_ranked_ids IS NULL")
    op.execute("UPDATE evaluation_case_results SET measurements = '[]'::json WHERE measurements IS NULL")
    op.execute("ALTER TABLE evaluation_case_results ALTER COLUMN variant SET NOT NULL")
    op.execute("ALTER TABLE evaluation_case_results ALTER COLUMN lexical_cohort_ranked_ids SET NOT NULL")
    op.execute("ALTER TABLE evaluation_case_results ALTER COLUMN measurements SET NOT NULL")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_evaluation_case_variant') THEN
                ALTER TABLE evaluation_case_results
                ADD CONSTRAINT uq_evaluation_case_variant UNIQUE (run_id, case_id, variant);
            END IF;
        END $$
    """)

    op.execute("ALTER TABLE evaluation_aggregates ADD COLUMN IF NOT EXISTS variant varchar(20)")
    op.execute("ALTER TABLE evaluation_aggregates ADD COLUMN IF NOT EXISTS stage varchar(40)")
    op.execute("ALTER TABLE evaluation_aggregates ADD COLUMN IF NOT EXISTS k integer")
    op.execute("ALTER TABLE evaluation_aggregates ADD COLUMN IF NOT EXISTS cohort_id uuid")
    op.execute("UPDATE evaluation_aggregates SET variant = 'legacy' WHERE variant IS NULL")
    op.execute("UPDATE evaluation_aggregates SET stage = 'overall' WHERE stage IS NULL")
    op.execute("ALTER TABLE evaluation_aggregates ALTER COLUMN variant SET NOT NULL")
    op.execute("ALTER TABLE evaluation_aggregates ALTER COLUMN stage SET NOT NULL")

    op.execute("ALTER TABLE evaluation_gate_reviews ADD COLUMN IF NOT EXISTS threshold_revision varchar(64)")
    op.execute("UPDATE evaluation_gate_reviews SET threshold_revision = 'legacy' WHERE threshold_revision IS NULL")
    op.execute("ALTER TABLE evaluation_gate_reviews ALTER COLUMN threshold_revision SET NOT NULL")

    op.execute("GRANT SELECT, INSERT ON evaluation_suite_revisions, evaluation_test_cases, evaluation_runs, evaluation_case_results, evaluation_aggregates, evaluation_gate_reviews TO di_profile_operator")
    op.execute("GRANT UPDATE (is_active) ON evaluation_suite_revisions TO di_profile_operator")
    op.execute("GRANT UPDATE (status, started_at, completed_at, error_message, enqueued_at, heartbeat_at, comparison_valid) ON evaluation_runs TO di_profile_operator")
    op.execute("GRANT UPDATE (answer_quality_score, answer_quality_note) ON evaluation_case_results TO di_profile_operator")
    op.execute("GRANT INSERT ON active_profiles TO di_profile_operator")


def downgrade() -> None:
    """Retain additive evaluation data on rollback; the previous app ignores it."""
