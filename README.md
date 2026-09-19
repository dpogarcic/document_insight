# Document Insight Platform

An internal AI platform for securely ingesting PDFs and images, extracting structured
content, and answering questions over authorized document evidence.

## Project status

**Planning complete; implementation has not started.**

The current documents define the first implementation slice. Setup commands, API
examples, deployment instructions, and operational runbooks will be added alongside
working code so that this README remains accurate.

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
- [AI Tech Lead assignment](Tech_Assignment.pdf) - original project
  brief.

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
