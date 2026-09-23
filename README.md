# Document Insight Platform

[![CI](https://github.com/dpogarcic/document_insight/actions/workflows/ci.yml/badge.svg)](https://github.com/dpogarcic/document_insight/actions/workflows/ci.yml)

An internal AI platform for securely ingesting PDFs and images, extracting structured
content, and answering questions over authorized document evidence.

## Project status

**Core vertical slice implemented and tested, with a CI/CD pipeline through image
publication.**

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

A [`benchmark/`](benchmark/README.md) load test drives `POST /query` at a configured
aggregate rate across throwaway tenants. The default is 100 users at 100 requests/s
for 20 seconds, within the default per-user quota. [`benchmark/results.md`](benchmark/results.md)
summarizes the latest run, remaining bottlenecks, and capacity expectations. Reports separate
HTTP outcomes, client failures, latency, and scheduler lag; HTTP success alone is not an
answer-quality evaluation.

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs quality, test, dependency-audit,
and Docker build/image-scan checks on pull requests, repeats the required checks on
`main`, and publishes the application image to GitHub Container Registry (GHCR) only
from `main`, tagged with the commit SHA. Publication is the final stage; cloud deployment
is intentionally deferred. [`.github/dependabot.yml`](.github/dependabot.yml) opens weekly
dependency, base-image, and GitHub Actions update pull requests through the same checks.
See the [CI/CD scope](docs/ARCHITECTURE.md#cicd-scope-and-delivery-boundary) for the
assignment interpretation and rationale.

## Frontend application

A companion Next.js frontend lives in a separate repository:
[document_insight_application](https://github.com/dpogarcic/document_insight_application).
It provides the document library, upload, version-activation, and query/chat UI against
this API.

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
- [Autoscaling guide](docs/AUTOSCALING.md) - provisional users-per-API-worker estimates,
  scaling thresholds, shared capacity limits, and benchmark validation requirements.
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
- [Load test](benchmark/README.md) and [results](benchmark/results.md) - open-loop
  `POST /query` benchmark, methodology, and the connection-pool finding it surfaced.
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
make local-run
```

Equivalent to, and a thin wrapper around, `docker compose up --build`.

Compose starts PostgreSQL/pgvector, Redis, MinIO and its bucket initialization, database
migrations, restricted database role provisioning, the RQ worker, the public API, the
Admin Panel, evaluation workers, and the local observability stack (Prometheus, cAdvisor,
Loki, Grafana Alloy, and Grafana). Nothing is gated behind a Compose `--profile` flag.
Only the API, Admin Panel, and Grafana are exposed on host ports (`8000`, `127.0.0.1:8001`,
and `127.0.0.1:3001`); the supporting services remain private to the Compose network.
OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

See [Applications and services](docs/application/README.md) for what each container does,
including the Admin Panel and `profile-operator` CLI walkthrough for approving capability
profiles, and the Grafana dashboards, metrics internals, and production observability
requirements for the local monitoring stack.

| Method | Path | Contract | Status |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | Provision a new tenant, General department, and tenant administrator | Implemented |
| `POST` | `/auth/login` | Verify credentials and obtain a bearer token | Implemented |
| `POST` | `/ingest` | Store a PDF/image, create its version, and enqueue a processing job | Implemented through queue publication |
| `GET` | `/documents` | List documents and visible departments within the caller's authorization scope | Implemented |
| `POST` | `/documents/{document_id}/activate` | Tenant-admin-only explicit selection of a ready searchable version | Implemented |
| `GET` | `/jobs/{job_id}` | Read an authorized processing-job status | Implemented |
| `POST` | `/query` | Authenticate, enforce a per-user quota, retrieve authorized evidence, and return a cited answer | Implemented |

### Sample API calls

Register creates a new tenant, a `General` department, and a tenant administrator:

```bash
curl -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{
        "email": "admin@example.com",
        "password": "a-strong-password",
        "display_name": "Ada Admin",
        "tenant_name": "Example Tenant"
      }'
```

Log in to obtain a short-lived bearer token:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "admin@example.com", "password": "a-strong-password"}' \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
```

Ingest a PDF or image (multipart upload, ≤ 25 MiB); omit `document_id` to create a new
document at `v1`, or pass an existing one to create its next version:

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample.pdf;type=application/pdf"
```

Check processing status with the `job_id` the `/ingest` response returned:

```bash
curl http://127.0.0.1:8000/jobs/<job_id> -H "Authorization: Bearer $TOKEN"
```

Once a version is `ready`, a tenant admin activates it as the document's current,
searchable version:

```bash
curl -X POST http://127.0.0.1:8000/documents/<document_id>/activate \
  -H "Authorization: Bearer $TOKEN"
```

Ask a question with an optional lexical/vector `filter` hint and result count:

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question": "How many paid vacation days do employees get?", "top_k": 5}'
```

Returns `answer`, an evidence-`confidence` score, quoted `sources` (document version,
page, and exact passage), and `entities` detected in the authorized documents that
contributed to retrieval.

`POST /query` allows 30 requests per authenticated user per 60-second window by default.
Set `QUERY_RATE_LIMIT_REQUESTS` and `QUERY_RATE_LIMIT_WINDOW_SECONDS` to change the quota.
Redis shares the count across API instances. Once exhausted, the API returns `429` with
`detail.code: "query_rate_limit_exceeded"` and a `Retry-After` header. If Redis cannot be
checked, `/query` returns `503` and does not call retrieval or a model provider.

Registration intentionally creates a new tenant; joining an existing tenant will use a
future administrator-controlled invitation flow. See
[ARCHITECTURE.md's ingest/version-replacement](docs/ARCHITECTURE.md#ingest-and-version-replacement)
and [processing-job recovery](docs/ARCHITECTURE.md#processing-job-recovery) sections for
what happens between `202 Accepted` and a version becoming `ready` — parsing, language
detection, NER, chunking, embedding, and reconciler recovery — and
[Applications and services](docs/application/README.md#background-and-storage-services)
for following worker/reconciler logs locally.

Run the local checks and disposable-test-service setup described in
[CONTRIBUTING.md](CONTRIBUTING.md#local-workflow) before opening a pull request.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the human and AI-agent workflows, including
installing the repository's pre-commit hooks. It links to the required architecture,
ADRs, and [code-quality standards](docs/CODE_QUALITY.md).

Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
Design decisions remain **In Review** until they are validated during the first working
vertical slice.
