# Document Insight Platform

An internal AI platform for securely ingesting PDFs and images, extracting structured
content, and answering questions over authorized document evidence.

## Project status

**Planning complete; authentication and ingestion implementation in progress.**

The FastAPI application, typed request/response models, endpoint validation, and OpenAPI
contract are implemented. Local registration and login are connected to PostgreSQL with
Argon2 password hashing and short-lived signed JWT access tokens. Authenticated ingestion
currently validates PDF, PNG, and JPEG uploads, stores immutable originals in local MinIO,
and atomically persists document/version metadata with a durable processing job. The
authenticated job-status endpoint is implemented. RQ publication, workers, query, and
model providers are not connected yet.

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
  processing lifecycle, failures, and current-version promotion.
- [ADR 003: Tenant isolation and security](docs/adr/003-tenant-isolation.md) - tenants,
  departments, roles, authorization, encryption, and auditing.
- [Code quality standards](docs/CODE_QUALITY.md) - typing, testing, coverage,
  documentation, security, and merge expectations.
- [AI Tech Lead assignment](Tech_Assignment.pdf) - original project brief.

## Local setup

Install dependencies and create local configuration:

```bash
uv sync --group dev
cp .env.example .env
```

Start PostgreSQL, pgvector, and the local S3-compatible object store, then apply migrations:

```bash
docker compose up -d database object-storage object-storage-init
uv run alembic upgrade head
```

Start the API:

```bash
uv run uvicorn document_insight.api.app:app --reload
```

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
| `POST` | `/ingest` | Store a PDF/image, create its version, and persist a processing job | Pre-queue stage implemented |
| `GET` | `/jobs/{job_id}` | Read an authorized processing-job status | Implemented |
| `POST` | `/query` | Query authorized documents with optional filters and `top_k` | Contract only |

Registration intentionally creates a new tenant. Joining an existing tenant will use a
future administrator-controlled invitation flow; public registration cannot select an
existing tenant or self-assign a role.

The current ingestion checkpoint returns `203` with `status: "stored"`,
`job_status: "queued"`, and the generated `job_id` after the original, version, and job
are durable. At this stage `queued` means that PostgreSQL is authoritatively holding the
job for future delivery; `enqueued_at` remains null because RQ publication is not yet
implemented. The next queue slice will publish this same job, set `enqueued_at`, and
replace the interim response with the planned `202 Accepted` response.

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
