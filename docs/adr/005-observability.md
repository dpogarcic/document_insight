# ADR 005: Establish privacy-safe observability for platform and RAG operations

- **Status:** In Review
- **Date:** 2026-09-22
- **Decision owners:** Engineering

## Context

The platform needs operational visibility across the public API, asynchronous processing,
retrieval, reranking, and generation. A support investigation must be able to connect an
API request to its worker activity without exposing document content, prompts, credentials,
or authorization-sensitive data. The platform also needs a local Docker-based monitoring
stack that uses the same collection contracts as production.

Prometheus is appropriate for bounded numeric time series, while Loki is appropriate for
safe, searchable structured events. Mixing identifiers, user content, or unbounded values
into Prometheus labels would create unbounded cardinality and could disclose sensitive data.

## Decision

We will use Prometheus for metrics, Grafana for dashboards, cAdvisor for Docker resource
metrics, and Grafana Alloy to collect Docker logs into Loki. Grafana is the only
observability UI that may be exposed, and only through authenticated access. Prometheus,
Loki, Alloy, cAdvisor, and application metrics endpoints remain private.

### Collection and access

- The API exposes `/metrics` only when a monitoring bearer token is configured. Missing or
  invalid credentials receive `404` so the endpoint is not discoverable through ordinary
  requests.
- Prometheus scrapes the API over the private service network using that token. Worker and
  reconciler metrics use a private Prometheus multiprocess volume shared with the API,
  so these processes do not expose separate HTTP ports. This is local-Compose-only:
  independent container restarts can reuse process IDs and corrupt the shared files.
  Production collection must use restart-safe per-instance isolation before rollout.
- Grafana Alloy reads Docker logs and forwards them to Loki. Grafana provisions Prometheus
  and Loki data sources, dashboards, and Grafana-managed alert rules that query Prometheus.
  No external Alertmanager is part of this stack. Grafana is loopback-only in local Compose and
  must sit behind authenticated TLS ingress in production.
- Local Docker Compose uses persistent named volumes. Production uses encrypted persistent
  storage, backups, retention controls, secret-manager supplied credentials, alert routing,
  and a managed or highly available logging deployment where scale requires it.

### Metric and log data policy

- Prometheus metric labels are bounded and low-cardinality. Allowed labels include fixed
  dimensions such as `stage`, `outcome`, `error_code`, `provider`, and `capability`.
  `profile_id` is allowed only while the set of active/readable profiles remains bounded.
- Prometheus labels must never contain tenant, department, user, document, version, chunk,
  job, correlation ID, question, filter, prompt, source text, embedding, token, or secret.
- Structured Loki logs contain correlation ID and safe resource identifiers only when needed
  for operations. They must never contain document text, unredacted prompts or queries,
  bearer tokens, passwords, provider keys, embeddings, or citation passage text.
- Metrics and logs are operational signals, not an authorization or audit subsystem. The
  immutable profile/audit records specified in ADR 004 remain authoritative for RAG behavior.

### Production observability signals

| Area | Prometheus metrics | Loki event fields |
| --- | --- | --- |
| HTTP API | request count and duration by method/status | correlation ID, operation, outcome, duration, safe error code |
| Ingestion jobs | durable jobs by status; oldest queued/in-flight age; scheduled-retry count; terminal failed-job count | correlation ID, job/version ID, stage, outcome, safe error code |
| Providers | request count, duration, rate-limit and retryable failure totals by provider/capability | correlation ID, provider, capability, outcome, safe error code |
| RAG query | retrieval/reranking/generation duration; candidate counts; cited-passage count; insufficient-evidence total | correlation ID, query-profile ID, stage, outcome, safe error code |
| Evidence quality | calibrated evidence-confidence histogram and profile-level outcome rates | query-profile ID, outcome; never question or retrieved text |
| Runtime | container CPU, memory, network, and filesystem metrics | service/container lifecycle events |

The query service records exactly one resolved query-profile identifier at request start as
required by ADR 004. RAG metrics may associate an event with that bounded profile cohort,
but must not include the question, documents, passages, or authorization scope.

### Production RAG metrics

Production telemetry measures operational behavior, not ground-truth relevance. These
metrics are emitted to Prometheus and visualized in Grafana. Prometheus duration values use
seconds by convention; dashboards display milliseconds and percentile views.

| Measurement | Type | Definition |
| --- | --- | --- |
| `rag_stage_duration_seconds` | Histogram | Wall-clock duration for bounded `stage` values: query embedding, lexical retrieval, vector retrieval, RRF fusion, reranking, evidence selection, and generation. Record a bounded `outcome`; add a query-profile cohort only after an explicit bounded-cohort mapping is defined. |
| `rag_query_duration_seconds` | Histogram | End-to-end duration from authorized query preparation through a grounded response or insufficient-evidence outcome. |
| `rag_candidate_count` | Histogram | Candidate count after lexical retrieval, vector retrieval, RRF fusion, reranking, and evidence selection. It measures retrieval shape without exposing candidate identities. |
| `rag_insufficient_evidence_total` | Counter | Queries that correctly stop before generation because the configured evidence or citation threshold was not met. |
| `rag_citation_count` | Histogram | Number of citations returned per grounded response. |
| `rag_evidence_confidence` | Histogram | Distribution of the already-calibrated evidence-confidence score. It is never an LLM self-confidence score or evidence of continued calibration. |

Production metrics must not claim Recall@K, Precision@K, answer correctness, or relevance.
Live traffic lacks the ground-truth judgments required to calculate them.

### Offline RAG evaluation metrics

Recall@K and Precision@K are calculated only in controlled, labelled evaluation runs. Each
run records the immutable query profile, enabled lexical/embedding read cohorts, retrieval
settings, evaluation-set revision, evaluator version, and timestamp. It runs the same
authorization-first retrieval path as production, using approved evaluation identities and
data; an evaluation must never bypass ADR 003 authorization predicates.

| Measurement | Definition |
| --- | --- |
| Recall@K | Of all labelled relevant passages for an evaluation query, the fraction present in the top `K` retrieved passages. Report separately for lexical, vector, fused/RRF, and reranked results where applicable. |
| Precision@K | Of the top `K` retrieved passages, the fraction labelled relevant. Report separately for lexical, vector, fused/RRF, and reranked results where applicable. |

`K` is an explicit evaluation parameter, normally reported for the retrieval candidate
limits and the final citation limit (for example `K=1`, `K=5`, and `K=10`). Evaluation
reports may retain these fixed values; arbitrary request `top_k` values must not become a
Prometheus label.

Relevance labels use immutable source-version page spans. Precision@K divides by K;
Recall@K is reported only when all relevant spans for a case have been labelled.
Overlapping candidate chunks count as relevant when they cover at least half the labelled
span. Evaluation history also retains citation precision/recall, answerability accuracy,
per-case operator answer-quality scores, and the numerator/denominator behind each
aggregate. Baseline and candidate measurements remain separate.

Evaluation reports may retain per-query relevance judgments in the controlled evaluation
artifact. Recall@K and Precision@K are not emitted to production Prometheus; production
telemetry must not contain evaluation query text, document text, passage identifiers, or
relevance labels tied to a customer document.

### Alerts and dashboards

- The system dashboard shows API request rate, p95 duration, 5xx ratio, and container CPU,
  memory, and task-state signals. It also provides Prometheus and Loki exploration for
  support staff.
- A separate RAG dashboard shows stage and end-to-end p95 duration, insufficient-evidence
  rate, and candidate-count distribution.
- A separate ingestion dashboard shows the authoritative durable-job backlog, in-flight
  work, retry backlog, terminal failure count, worker/reconciler health, and stage
  duration/outcome. It must not infer job state from Redis.
- RQ worker heartbeats advance during idle polling and active-job monitoring, separately
  from the last completed-job timestamp. The reconciler records its last successful pass.
  Missing or stale worker/reconciler signals and overly old in-flight jobs alert in Grafana.
- Grafana owns and evaluates the alert rules; Prometheus is a metrics source, not a rule
  evaluator. Contact points and notification policies are a separate deployment step and
  must be configured and delivery-tested before production use.
- Production alert rules must cover API unavailability, sustained 5xx responses, provider
  failures/rate limits, job failure or recovery spikes, stale-job recovery failures, queue
  backlog, and resource exhaustion.
- Production dashboards compare stage-latency percentiles and bounded query-profile cohorts.
  Controlled evaluation reports compare Recall@K and Precision@K before an activation
  changes query behavior. An evaluation regression requires investigation.
- Alert payloads contain only aggregate values, labels allowed by this ADR, and links to
  authenticated dashboards. They do not contain document-derived content.

## Consequences

- Operations can distinguish API, worker, provider, retrieval, and infrastructure failures
  without inspecting source documents.
- Correlation IDs allow a support workflow from Grafana/Loki back to the relevant API and
  worker logs while avoiding high-cardinality metric labels.
- RAG quality regressions can be compared in controlled evaluation reports across immutable
  query-profile and index-read cohorts, while production dashboards show only operational
  behavior. Evaluation datasets and calibrated-confidence governance remain separate work.
- The local stack is useful for development and acceptance testing. A single-binary Loki
  instance and one Prometheus server are not a high-availability production topology.

## Acceptance criteria

- Local Compose starts the application and the observability stack together with a
  single `docker compose up`; nothing is gated behind a Compose profile.
- Grafana exposes provisioned Prometheus and Loki data sources, while internal collection
  services do not publish host ports.
- Metrics endpoints require the monitoring secret and do not appear in public API schemas.
- Automated tests cover metrics authentication and the metrics/log data policy is documented.
- Production RAG instrumentation emits only the bounded operational metrics and safe log
  fields specified here; it does not emit Recall@K or Precision@K.
- Labelled evaluation runs report Recall@K and Precision@K for each configured retrieval
  stage in a controlled evaluation artifact, while production telemetry records per-stage
  and end-to-end latency for Grafana to display in milliseconds.
