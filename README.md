# Document Insight Platform

An internal AI platform for securely ingesting PDFs and images, extracting structured
content, and answering questions over authorized document evidence.

## Project status

**Core vertical slice implemented and tested; CI/CD pipeline and load-test benchmark are not yet added.**

Authentication, ingestion, processing, and query are implemented end to end. Local
registration and login are connected to PostgreSQL with Argon2 password hashing and
short-lived signed JWT access tokens. Authenticated ingestion validates PDF, PNG, and JPEG
uploads, stores immutable originals in local MinIO, and atomically persists document/version
metadata with a durable processing job published to Redis/RQ. The worker extracts PDF/image
text, detects English or Croatian, enriches document metadata with NER, stores citation-ready
chunks with a PostgreSQL full-text lexical index, and creates profile-bound embeddings
through Mistral, marking completed versions ready for later tenant-admin activation.
`POST /query` performs authorized hybrid retrieval (lexical + vector, fused with RRF),
reranking, and evidence-grounded generation, returning an answer, evidence-confidence score,
citations, and detected entities; per-user rate limiting and PostgreSQL row-level security
enforce tenant/department isolation before every read. A separately authenticated Admin
Panel manages capability/ingestion/query profile activation and a full evaluation-suite
workflow (labelled test cases, baseline-vs-candidate runs, Recall@K/Precision@K/citation
scoring, manual gate review) gating platform activations. A local Prometheus/Grafana/Loki
stack provides metrics, per-stage duration timing, and dashboards, with a correlation ID
propagated through logs across the API, queue, and worker boundaries — not yet a formal
distributed-tracing backend (see ADR 005).

Not yet done: the CI/CD pipeline (lint/test/security-scan on push, image build/push on
main) and the `benchmark/` load-test script and results summary are both required
deliverables per `Tech_Assignment.pdf` and are still outstanding.

## Planned capabilities

- Upload PDFs and images, including replacement uploads that create immutable document
  versions.
- Store original files and process them asynchronously through text extraction/OCR,
  language detection, Named Entity Recognition (NER), chunking, and embedding.
- Search with authorized hybrid retrieval: lexical search plus vector similarity,
  followed by ranking and evidence-grounded answer generation.
- Return answers with an evidence-confidence score, detected entities, and citations to
  the exact document version and passage.
- Protect tenant and department data before retrieval, with role-based actions and
  per-user query rate limits.

## Design documentation

- [Applications and services](docs/application/README.md) - running Compose services,
  optional tools, local endpoints, startup jobs, and the [tenant evaluation workflow](docs/application/README.md#evaluation-suites-and-manual-quality-gate).
- [Architecture](docs/ARCHITECTURE.md) - system diagram, component responsibilities,
  data flow, deployment position, and trade-offs.
- [ADR 001: Service boundaries](docs/adr/001-service-boundaries.md) - API, service
  boundaries, storage, provider configuration, and retrieval design.
- [ADR 002: Async processing and versioning](docs/adr/002-async-processing.md) - jobs,
  processing lifecycle, failures, readiness, and explicit version activation.
- [ADR 003: Tenant isolation and security](docs/adr/003-tenant-isolation.md) - tenants,
  departments, roles, authorization, encryption, and auditing.
- [ADR 004: Capability configuration profiles](docs/adr/004-capability-configuration-profiles.md) - immutable AI configuration, explicit activation, and compatible retrieval across profile generations.
- [ADR 005: Observability](docs/adr/005-observability.md) - privacy-safe metrics, logs,
  dashboards, local Compose monitoring, and production operational controls.
- [ADR 006: Evaluation suite admin dashboard and run lifecycle](docs/adr/006-evaluation-admin-dashboard.md) -
  suite/run data model, evaluation execution and recovery, gate review, and capability
  profile retirement.
- [Code quality standards](docs/CODE_QUALITY.md) - typing, testing, coverage,
  documentation, security, and merge expectations.
- [AI Tech Lead assignment](Tech_Assignment.pdf) - original project brief.

Reranking and generation instructions are stored in fingerprinted capability snapshots.
Migration `20260922_0011` creates prompt-bearing replacements and activates a new query
profile only when the platform still uses the original seeded query profile. Migration
`20260923_0020` retires that original pre-`system_prompt` reranker/generator pair outright
(see ADR 006), so it can no longer be selected as an evaluation candidate. Installations
with a custom active query profile must create and activate prompt-bearing capability and
query profiles before running queries with this application version; an old snapshot with
only `prompt_revision` is rejected at profile resolution.

## Local setup

Install dependencies and create local configuration:

```bash
uv sync --group dev
cp .env.example .env
```

Set `MISTRAL_API_KEY` and six distinct runtime `DATABASE_*_PASSWORD` values in `.env`.
Set a seventh, `DATABASE_PROFILE_OPERATOR_PASSWORD`, for the Admin Panel and manual
profile approval, which start by default. Replace each matching `DATABASE_*_URL`
password with the same value (URL-encode special characters). `DATABASE_URL` is the
database owner credential used only by migration and role provisioning; application
services receive restricted login URLs. Then start the complete local stack, including
the Admin Panel, evaluation services, and local observability, with one command:

```bash
docker compose up --build
```

Compose starts PostgreSQL/pgvector, Redis, MinIO and its bucket initialization, database
migrations, restricted database role provisioning, the RQ worker, the public API, the
Admin Panel, evaluation workers, and the local observability stack (Prometheus, cAdvisor,
Loki, Grafana Alloy, and Grafana). Nothing is gated behind a Compose `--profile` flag.
Only the API, Admin Panel, and Grafana are exposed on host ports (`8000`, `127.0.0.1:8001`,
and `127.0.0.1:3001`); the supporting services remain private to the Compose network.

### Manual configuration-profile approval

For the browser UI, set `DATABASE_PROFILE_OPERATOR_PASSWORD` and its matching
`DATABASE_PROFILE_OPERATOR_URL`, plus distinct `ADMIN_PANEL_USERNAME` and
`ADMIN_PANEL_PASSWORD` values in `.env`. It starts with the rest of the stack:

```bash
docker compose up --build
```

Open [Document Insight Admin](http://127.0.0.1:8001/) and sign in with those admin
panel credentials. The Compose port binds to localhost only. The panel supports reviewing
profiles, creating draft capabilities, validating them, assembling ingestion and query
policies, and activating bundles with an audit reason. It keeps older read cohorts
selected when creating a new query policy. For production, put the panel behind an
internal TLS ingress and set `ADMIN_PANEL_SECURE_COOKIES=true`.

The operator command remains available for scripted or emergency use:

The private `profile-operator` service uses `DATABASE_PROFILE_OPERATOR_URL`, separate
from the public API and worker credentials. Put local JSON configuration files in a
`profiles/` directory. `docker compose up` also starts this service, but only runs its
default `--help` command and exits; run a specific command with
`docker compose run --rm profile-operator ...`.

1. `create-capability --capability embedding --name mistral-embed-v2 --config-file /app/profiles/embedding-v2.json` stages a draft and prints its ID.
2. `validate-capability PROFILE_ID` approves the draft after schema, adapter, and runtime checks.
3. `create-ingestion --ner ID --chunking ID --lexical ID --embedding ID` stages a bundle, reusing approved IDs for unchanged capabilities.
4. `create-query --lexical OLD_ID NEW_ID --embedding OLD_ID NEW_ID --reranker ID --generation ID --retrieval-file /app/profiles/retrieval.json` stages a query bundle that reads both old and new indexes.
5. Review the proposed policy with `show-capability PROFILE_ID`, `show-query PROFILE_ID`, and `show-ingestion PROFILE_ID`. `show-active` prints the active IDs and revisions. Activate the query bundle with `activate --kind query --profile-id ID --expected-revision N --actor-id OPERATOR_UUID --reason "enable both cohorts"`. Then activate the ingestion bundle with its own expected revision.

Keep runtime credentials for every provider used by an active query cohort. This
deployment supports Mistral embedding, reranking, and generation; another provider
requires its adapter and credential before validation. Existing jobs retain their
persisted ingestion profile. Query activation refuses to omit cohorts referenced by
ready index generations, so older indexed documents remain searchable.

### Local observability

The local monitoring stack starts with the rest of the services:

```bash
docker compose up --build
```

This starts Prometheus, cAdvisor, Loki, Grafana Alloy, and Grafana. Grafana is available
only on `http://127.0.0.1:3001`; use the configured `admin` account and
`GRAFANA_ADMIN_PASSWORD`. Grafana provisions dashboards for **Document Insight System**
for API traffic and container CPU, memory, and task-state signals; **Document Insight RAG**
for query latency and evidence outcomes; and **Document Insight Ingestion** for asynchronous
job health. The RAG dashboard does not display Recall@K or Precision@K: those require
labelled offline evaluation data. **Document Insight Logs** starts at a 24-hour window and
filters Docker logs by service. **Document Insight Alerts** shows current Grafana-managed
alert states and configured coverage. Inspect every rule, including healthy rules, under
**Alerting → Alert rules**.

The separate **Document Insight Ingestion** dashboard shows durable jobs by status, the
age of the oldest queued or in-flight job, jobs awaiting retry, terminal failures,
worker/reconciler liveness, and per-stage processing outcomes and latency. Job counts and
ages come from PostgreSQL's authoritative ledger rather than transient Redis queue state.

On Docker Desktop, cAdvisor may expose only an aggregate host cgroup rather than individual
container cgroups. In that case the memory panel displays the available aggregate instead of
per-service memory.

Set strong `METRICS_BEARER_TOKEN` and `GRAFANA_ADMIN_PASSWORD` values before starting the
stack. Grafana provisions and evaluates the alert rules against Prometheus. No external
Alertmanager, contact point, or custom notification policy is configured by this project;
notification delivery must be configured and tested in Grafana before production use.
Prometheus uses the first only inside the Compose network to scrape the private
`/metrics` endpoint; the API returns `404` for that endpoint when no token is configured.
Prometheus, Loki, cAdvisor, and Alloy do not publish host ports.

Worker, reconciler, and API metrics use Prometheus multiprocess files on a private shared
volume, reset once before the services start. This makes worker-stage durations, provider
outcomes, recovered/exhausted-job totals, worker heartbeat, and worker/reconciler
last-success timestamps
available through the authenticated API scrape without exposing a worker port.
The worker heartbeat advances during idle polling and while RQ monitors an active job;
last completed-job time is intentionally separate. Grafana alerts when the worker heartbeat
or reconciler success becomes stale, or a processing job remains in flight too long.
The shared multiprocess volume is a local Compose arrangement: independently recreating
containers can reuse process IDs and corrupt the metric files, making `/metrics` fail.
After such a restart, stop the API, worker, and reconciler together, run
`docker compose run --rm prometheus-multiproc-init`, then start them together.
Before production deployment, replace this shared-file collection with a restart-safe
per-instance metric collection design and test rolling restarts.

For production, deploy the same scrape configuration on private infrastructure with
encrypted persistent storage, secret-manager supplied monitoring and Grafana credentials,
an authenticated Grafana ingress, backups, Grafana contact points and notification policies,
and production-appropriate
retention. Do not expose Prometheus, Loki, cAdvisor, Alloy, or `/metrics` directly to the
internet. The local single-binary Loki instance is intended for development; use the
organization's managed log platform or a production Loki deployment for scale and HA.

OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

Every HTTP request receives a UUID correlation ID. A valid inbound `X-Correlation-ID` is
preserved; otherwise the API generates one. The selected ID is returned in the
`X-Correlation-ID` response header so clients can include it in support reports. Every
server log line includes a `correlation_id` field; request-scoped logs and exception
tracebacks use the response ID, while work outside an HTTP request uses `-`.

| Method | Path | Contract | Status |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | Provision a new tenant, General department, and tenant administrator | Implemented |
| `POST` | `/auth/login` | Verify credentials and obtain a bearer token | Implemented |
| `POST` | `/ingest` | Store a PDF/image, create its version, and enqueue a processing job | Implemented through queue publication |
| `GET` | `/documents` | List documents and visible departments within the caller's authorization scope | Implemented |
| `POST` | `/documents/{document_id}/activate` | Tenant-admin-only explicit selection of a ready searchable version | Implemented |
| `GET` | `/jobs/{job_id}` | Read an authorized processing-job status | Implemented |
| `POST` | `/query` | Authenticate, enforce a per-user quota, retrieve authorized evidence, and return a cited answer | Implemented |

`POST /query` allows 30 requests per authenticated user per 60-second window by default.
Set `QUERY_RATE_LIMIT_REQUESTS` and `QUERY_RATE_LIMIT_WINDOW_SECONDS` to change the quota.
Redis shares the count across API instances. Once exhausted, the API returns `429` with
`detail.code: "query_rate_limit_exceeded"` and a `Retry-After` header. If Redis cannot be
checked, `/query` returns `503` and does not call retrieval or a model provider.

Registration intentionally creates a new tenant. Joining an existing tenant will use a
future administrator-controlled invitation flow; public registration cannot select an
existing tenant or self-assign a role.

`POST /ingest` returns `202` with `status: "stored"`, `job_status: "queued"`, and the
generated `job_id` only after the original and durable records are stored and RQ accepts
the job. PostgreSQL remains authoritative for lifecycle state; `enqueued_at` records
successful queue publication. The worker parses PDFs and images into a durable,
version-scoped extraction checkpoint, detects English or Croatian, and persists spaCy
entity metadata. It then creates deterministic page-aware chunks, including page and
character offsets for exact citations, and PostgreSQL generates a `simple` full-text index
for each chunk. This is a temporary lexical index, not BM25. The worker batches those
chunks through Mistral's embeddings API, validates the profile-declared vector dimension,
and stores vectors under the exact embedding profile.
After all checkpoints succeed it marks the index generation, job, and version `ready`.
It does not make the version searchable; a future tenant-admin activation action will
atomically select a ready version as the document's current version.

The worker image includes and uses local spaCy NER models for English (`en_core_web_sm`)
and Croatian (`hr_core_news_sm`). The entity model holds deduplicated,
document-version-scoped metadata: a display value, normalized value, label, occurrence
count, and model provenance. Only RAG-relevant labels are retained: `PERSON`, `ORG`,
`GPE`, `LOC`, `PRODUCT`, `EVENT`, and `DATE`. The Croatian model's `PER` label is
normalized to the canonical `PERSON` label; broad or numeric labels such as `MISC` and
`CARDINAL` are discarded. Chunks, rather than entities, retain the grounding used for
passage retrieval and citations.

The Compose `worker` service consumes the `ingestion` RQ queue and starts RQ's delayed-job
scheduler. The `reconciler` service runs every `JOB_RECONCILIATION_INTERVAL_SECONDS`
(60 seconds by default). PostgreSQL remains authoritative: it republishes unqueued or stale
queued work, resumes stale processing jobs within their retry budget, and retries only
transient failed jobs. Permanent parser failures and exhausted jobs remain terminal.
Follow either worker's output with:

```bash
docker compose logs -f worker reconciler
```

Run the current checks with:

```bash
uv run ruff format --check src tests migrations
uv run ruff check src tests migrations
uv run mypy
uv run pytest
```

### Disposable PostgreSQL security tests

Set `TEST_DATABASE_OWNER_PASSWORD` and `TEST_DATABASE_RUNTIME_PASSWORD` in `.env`,
and set `TEST_DATABASE_RUNTIME_URL` to
`postgresql+asyncpg://document_insight_test_runtime:<runtime-password>@127.0.0.1:5433/document_insight_test`.
Use URL-safe local test passwords, and keep the URL password identical to
`TEST_DATABASE_RUNTIME_PASSWORD`. The test database runs on port 5433 with its data
on a temporary filesystem; stopping its container removes the data. It never uses
the development database on port 5432.

`database-test`, `test-migrate`, `test-bootstrap-roles`, and `redis-test` start
automatically with `docker compose up --build` alongside the rest of the stack, so once
it's running you only need:

```bash
uv run pytest -q -o addopts='' tests/integration
docker compose rm -sf database-test redis-test
```

The last command discards the temporary test data; it is optional since the tmpfs is
also cleared on container removal.

The test database initializes a restricted runtime role automatically. Alembic uses
the separate test owner role. The role bootstrap step enables six runtime logins and,
when configured, the private profile-operator login using passwords from `.env`.
The RLS tests check role capabilities, direct
SQL reads and writes, department revocation, editor assignment timing, ranked retrieval,
and an authenticated `/query` response. The disposable Redis test checks that concurrent
requests share one per-user quota. These checks skip when their respective test URLs are
unset.

## First implementation scope

The initial release will provide a Python/FastAPI API, PostgreSQL with pgvector,
S3-compatible object storage, Redis/RQ background processing, and Docker Compose for
local development. The API will expose document ingestion, job status, authentication,
and document query operations.

The implementation is container-first. Kubernetes deployment and autoscaling are
deliberately deferred until throughput, operational requirements, and hosting standards
have been validated.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the human and AI-agent workflows. It links
to the required architecture, ADRs, and [code-quality standards](docs/CODE_QUALITY.md).

Install the repository hooks before contributing implementation changes:

```bash
uv sync --group dev
uv run pre-commit install
```

Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
Design decisions remain **In Review** until they are validated during the first working
vertical slice.
