# Document Insight Platform

An internal AI platform for securely ingesting PDFs and images, extracting structured
content, and answering questions over authorized document evidence.

## Project status

**Planning complete; authentication and ingestion implementation in progress.**

The FastAPI application, typed request/response models, endpoint validation, and OpenAPI
contract are implemented. Local registration and login are connected to PostgreSQL with
Argon2 password hashing and short-lived signed JWT access tokens. Authenticated ingestion
currently validates PDF, PNG, and JPEG uploads, stores immutable originals in local MinIO,
and atomically persists document/version metadata with a durable processing job. The job
is published to Redis/RQ. The worker extracts PDF/image text, detects English or Croatian,
enriches document metadata with NER, and stores citation-ready chunks with a PostgreSQL
full-text lexical index. It also creates profile-bound embeddings through Mistral and marks
completed versions ready for later administrator activation. Query remains
contract-only.

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

- [Architecture](docs/ARCHITECTURE.md) - system diagram, component responsibilities,
  data flow, deployment position, and trade-offs.
- [ADR 001: Service boundaries](docs/adr/001-service-boundaries.md) - API, service
  boundaries, storage, provider configuration, and retrieval design.
- [ADR 002: Async processing and versioning](docs/adr/002-async-processing.md) - jobs,
  processing lifecycle, failures, readiness, and explicit version activation.
- [ADR 003: Tenant isolation and security](docs/adr/003-tenant-isolation.md) - tenants,
  departments, roles, authorization, encryption, and auditing.
- [ADR 004: Capability configuration profiles](docs/adr/004-capability-configuration-profiles.md) - immutable AI configuration, explicit activation, and compatible retrieval across profile generations.
- [Code quality standards](docs/CODE_QUALITY.md) - typing, testing, coverage,
  documentation, security, and merge expectations.
- [AI Tech Lead assignment](Tech_Assignment.pdf) - original project brief.

## Local setup

Install dependencies and create local configuration:

```bash
uv sync --group dev
cp .env.example .env
```

Set `MISTRAL_API_KEY` in `.env`, then start the complete local stack with one command:

```bash
docker compose up --build
```

Compose starts PostgreSQL/pgvector, Redis, MinIO and its bucket initialization, database
migrations, the RQ worker, and the public API. Only the API is exposed on port `8000`;
the supporting services remain private to the Compose network.

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
| `POST` | `/query` | Authenticate and prepare an authorization-bounded retrieval request | Implemented through retrieval preparation |

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
