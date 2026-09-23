# ADR 006: Evaluation suite admin dashboard and run lifecycle

- **Status:** In Review
- **Date:** 2026-09-23
- **Decision owners:** Engineering

## Context

ADR 004 requires a completed, approved evaluation run before a platform query activation.
ADR 005 defines the Recall@K, Precision@K, citation, and answerability methodology those
runs must report. Neither ADR specifies how an operator actually assembles a labelled test
set, launches a baseline-versus-candidate comparison, inspects its results, or how a query
profile that can no longer be resolved (for example, one seeded before a now-required
configuration field existed) is kept from being offered as a candidate again. This ADR
covers the suite/run data model, the Admin Panel surface that drives it, run execution and
recovery, and capability-profile retirement.

Building and operating this subsystem is materially larger than the take-home assignment's
required `benchmark/` folder with a load script and short results summary (see
`Tech_Assignment.pdf`). We retain it because it is the only way to actually exercise the
Recall@K/Precision@K methodology ADR 005 commits to, rather than leaving it as an unproven
paper design. New work here must not come at the expense of the assignment's required
CI/CD pipeline and load-test deliverable, which this ADR does not replace.

## Decision

### Suite and case model

- An evaluation suite has a stable `(suite_name, evaluation_tenant_id)` identity; each save
  is an immutable, numbered revision in `evaluation_suite_revisions`. Editing an existing
  suite creates its next revision rather than mutating history, so a run always stays
  reproducible against the exact revision it recorded at launch, even after the suite is
  later edited.
- Each revision owns a fixed set of immutable rows in `evaluation_test_cases`: question,
  authorized test-identity UUID, expected answerability, optional relevant-passage labels
  (`version_uuid@page:start:end`), an explicit `relevance_complete` flag, optional filter
  text, expected facts, and a review rubric. `relevance_complete` gates Recall@K and
  citation recall per ADR 005; a partially labelled case still supports Precision@K.
- `evaluation_case_templates` are migration-seeded, corpus-independent scenario starting
  points (document purpose, specific fact, named entity, date/number, multi-passage,
  nuance, abstention, hallucination, authorization, filter). They pre-fill a case's
  question, answerability, and rubric but are never runnable on their own; an operator
  still selects a corpus and a test identity.
- A suite pins an explicit corpus: a fixed set of the tenant's current activated document
  versions selected through the panel's title/version picker. The picker never exposes
  original content or raw passages.

### Run model and execution

- Launching a run persists an immutable `evaluation_runs` row before any queue
  publication: suite revision, baseline and candidate query-profile IDs, a corpus
  manifest, K values, requester, and evaluator version. `EvaluationService.launch_run`
  validates the manifest's fingerprint and corpus against the suite it claims to score
  before accepting it, so a run can never silently drift from that suite.
- A corpus manifest pairs a baseline `CorpusVariant` and a candidate `CorpusVariant`
  (indexed version IDs plus a mapping back to their source version). Query-mode
  comparisons reuse the suite's exact corpus for both variants. Ingestion-mode comparisons
  stay restricted to the isolated evaluation tenant (ADR 004) and require exactly one
  distinct candidate-indexed copy per source version.
- Runs move through `pending -> running -> completed | failed`. `EvaluationRunner.run()`
  claims a run exactly once (mirroring the idempotent job-claim pattern in ADR 002),
  executes every test case through both variants over the production-authorized query
  path, scores each case with the ADR 005 methodology, and only writes aggregate
  measurements after every case/variant has finished. A run that fails partway (for
  example, a provider or configuration error on the candidate side) never presents partial
  aggregates as complete; the Admin Panel instead shows whichever per-case results were
  saved before the failure, plus a safe, non-leaking error message.
- A dedicated `evaluation` RQ queue and `evaluation-worker` process keep this traffic
  isolated from ingestion (`worker` / `ingestion` queue). An `evaluation-reconciler`
  mirrors the ADR 002 ingestion reconciler: it republishes runs that were persisted but
  never confirmed enqueued, and fails runs whose heartbeat has been stale for over two
  hours, without ever retrying a run that already reached a terminal state.
- The worker advances a heartbeat after each case/variant so the reconciler can
  distinguish "still working" from "abandoned." Case-level measurements, stage rankings
  (lexical, vector, fused, reranked ranked IDs), citations, latencies, and provider errors
  are persisted per case per variant, not only as an aggregate, so a failed or surprising
  run stays debuggable.

### Gate review

- A completed run supports exactly one manual decision in `evaluation_gate_reviews`
  (`approve` or `reject`) with a required reason, recorded once by an operator. Before
  that decision, each candidate case answer can optionally receive a manual 0-1 quality
  score and note — the "answer quality" judgment ADR 005 explicitly leaves to a human
  rather than automating.
- An approved run against the tenant's currently active baseline is the artifact ADR 004
  requires before a platform query activation; a rejected or absent review blocks
  activation. Rejections remain in history rather than being deletable, preserving an
  audit trail of declined candidates.

### Admin Panel surface

- The Admin Panel (ADR 003, ADR 004) hosts the suite/run screens under `/evaluations/*`
  on the same operator-authenticated, CSRF-protected, loopback-bound FastAPI app used for
  capability/profile administration. It reuses that app's dedicated `profile-operator`
  database role, which has no original-document, raw-passage, or credential access; it can
  read tenant-scoped document titles/version IDs for the corpus picker and the generated
  answers/citations a completed run produced for manual review.
- Suite and case authoring are server-rendered HTML with one small vanilla-JS helper for
  client-side JSON assembly; there is no separate frontend build for this surface.

### Capability profile retirement

- A `capability_profile` can be marked `retired` in addition to `draft`/`validated`.
  Retirement means its configuration no longer satisfies the current provider schema (for
  example, a required field such as `system_prompt` was added after the profile was
  seeded) and it must never be resolved again.
- `ProfileCatalog.selectable_queries` excludes any query profile whose reranker or
  generation capability profile is retired from every operator-facing picker (new query
  policy, evaluation candidate). This closes the gap ADR 004 left open ("Backfilling and
  retiring legacy cohorts are separate operational work"): retirement is now a concrete,
  auditable state instead of a deferred item, though the initial mechanism is an explicit
  migration rather than a live Admin Panel action.
- A retired profile is never deleted: existing `query_profiles`, `evaluation_runs`, and
  `chunk_embeddings` rows that reference it keep resolving for historical audit; only
  future selection is blocked.

## Consequences

- Operators can run a real baseline-versus-candidate comparison end to end and see the
  exact Recall@K, Precision@K, citation, and answerability numbers ADR 005 defines, not
  just a paper methodology.
- A run's immutability (pinned suite revision, validated manifest, per-case-and-variant
  persistence) makes results reproducible and auditable, at the cost of a noticeably
  larger schema than a minimal benchmark script would need: `evaluation_suite_revisions`,
  `evaluation_test_cases`, `evaluation_case_templates`, `evaluation_runs`,
  `evaluation_case_results`, `evaluation_aggregates`, and `evaluation_gate_reviews`.
- Retirement prevents a known-broken profile from being offered again, at the cost of one
  more `capability_profiles.status` value every consumer of that column must handle.
- This subsystem does not replace the assignment's required load-test benchmark (see the
  scope note above); it answers a different question — retrieval and answer quality — than
  a throughput benchmark answers — latency and capacity under load.

## Acceptance criteria

- Editing a suite never changes a prior revision's test cases; a run always reports
  against the exact revision it recorded at launch.
- A run's aggregate measurements are absent, not partially wrong, whenever any
  case/variant failed to complete.
- A capability profile marked `retired` cannot be selected as a query-policy candidate
  through the Admin Panel — neither the New query policy form nor the evaluation run form
  — even though profiles that already reference it keep resolving for historical reads.
- An evaluation run can only be cited to authorize a platform activation when it is
  `completed` and has a recorded `approve` gate review against the currently active
  baseline.
