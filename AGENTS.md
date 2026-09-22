# Document Insight Platform: Agent Guide

## Read first

Before planning or changing implementation code, read these documents in order:

1. `docs/ARCHITECTURE.md`
2. `docs/adr/001-service-boundaries.md`
3. `docs/adr/002-async-processing.md`
4. `docs/adr/003-tenant-isolation.md`
5. `docs/adr/004-capability-configuration-profiles.md`
6. `docs/CODE_QUALITY.md`

Treat these documents as the current implementation contract, even while their status is
`In Review`. If a request conflicts with them, explain the conflict and obtain a clear
decision before changing the design. Update the relevant ADR or architecture document
when an accepted implementation decision changes.

Instruction priority is: direct user request, this file, the architecture/ADRs, code
quality standards, then existing implementation conventions.

## Product boundary

Build a Python-based AI Document Insight Platform for internal users.

- Ingest PDFs and images through `POST /ingest`.
- Store original uploads synchronously in S3-compatible object storage.
- Queue only asynchronous processing: parsing/OCR, language detection, NER, chunking,
  embedding, lexical indexing, and ready-state transitions. Activation is a separate
  tenant-admin operation.
- Provide `POST /query` with `question`, optional `filter`, and optional `top_k`.
- Return an evidence-grounded answer, an evidence-confidence score, detected entities,
  and exact source citations.
- Keep the API/gateway as the only public service. PostgreSQL/search, Redis/RQ, object
  storage, and workers are private services.

Do not add optional stretch features unless the user explicitly requests them.

## Required architecture decisions

- Core services use Python and FastAPI.
- PostgreSQL with pgvector is the system of record for documents, versions, jobs,
  chunks, entities, and vectors. Object storage holds immutable originals. Redis/RQ
  delivers jobs.
- Keep routes thin. Put business logic in application services and infrastructure/vendor
  calls behind adapters.
- Keep application models with their owning feature under `application/<feature>/`. Do
  not create a separate `domain/` layer for this modular monolith.
- Use one repository per persisted entity or association. Application services coordinate
  cross-entity work through an explicit shared transaction boundary; a repository must
  not read or mutate another repository's entity as a convenience side effect.
- Co-locate each repository protocol, SQLAlchemy implementation, and ORM model under
  `infrastructure/<entity>/`. The concrete repository explicitly implements its local
  protocol. Reserve `infrastructure/database/` for shared metadata, model registration,
  connections, sessions, and transaction management.
- Name SQLAlchemy classes `<Entity>Model`, HTTP request schemas `<Operation>Request`, and
  HTTP response or nested response schemas `<Concept>DTO`. Do not add `Response` before
  the `DTO` suffix.
- Keep security capabilities separated under `infrastructure/security/`; each capability
  module owns its protocol and explicitly implementing adapter.
- Keep application use-case inputs in focused `commands.py` modules. Keep persistence
  creation data beside its owning infrastructure protocol; do not mix commands,
  persistence payloads, and infrastructure protocols in a generic `contracts.py`.
- Provider selection is explicit by capability, such as `EMBEDDING_PROVIDER` or
  `GENERATION_PROVIDER`. A URL or model name alone must not be used to infer a provider
  protocol.
- Capability behavior is selected through immutable, database-backed profiles and explicit
  active-profile pointers. Deployments may add adapter support but must not activate a new
  chunking, lexical, embedding, reranking, or generation configuration implicitly. Jobs
  and index generations use their persisted ingestion profile; queries use one query
  profile resolved at request start. See ADR 004.
- Initial model plan: Mistral Embed for embeddings plus Mistral-hosted LLMs for reranking and
  generation, selected through explicit `mistral` provider profiles. Provider protocols must make
  alternate supported implementations possible.
- Retrieval is hybrid. Lexical and vector retrieval must receive identical authorization
  filters, candidates are fused with RRF, then reranked before `top_k` is applied.
- True BM25 requires a chosen lexical implementation. `pg_search` is a candidate under
  review; do not add it until its deployment and AGPL licensing implications are
  explicitly approved. PostgreSQL full-text search may be used temporarily, but do not
  call it BM25.
- NER enriches metadata; it is not a retrieval algorithm.
- NER stores deduplicated document-version metadata, unique by label and normalized value,
  with an occurrence count. It may softly select or boost authorized documents before chunk
  retrieval; it must not select chunks or provide citations. Chunks own passage grounding.
- `confidence` is evidence confidence, not an LLM self-reported confidence. Do not
  expose uncalibrated model certainty as a factual score.

## Documents, versions, and processing

- A logical document has a stable `document_id`; each upload is a separate immutable
  `document_version`.
- An upload without `document_id` creates a new document at `v1`. An authorized upload
  with `document_id` creates that document's next version.
- The upload limit is 25 MiB. Validate file size, MIME type, and file signature.
- Generate job IDs and idempotency keys on the server. Queue delivery and worker retry
  must never create duplicate derived records.
- Scope chunks, entities, embeddings, and citations to `document_version_id`, not only
  `document_id`.
- Keep `current_ready_version_id` on the logical document. Processing may mark a version
  `ready` but must never change this pointer. A future tenant-admin activation action
  explicitly and atomically selects a ready version as current; until then, the existing
  current version remains searchable.
- The API returns `202 Accepted` only after the original file is stored and the job is
  accepted by RQ. Object writes are not worker work.
- Preserve failure recovery: clean up orphaned objects, retain durable job state, and
  reconcile stalled/unqueued jobs.

## Tenancy, departments, and security

- Derive tenant identity from authenticated credentials, never from an untrusted request
  field.
- Enforce tenant and department authorization before SQL, lexical retrieval, vector
  retrieval, source lookup, and generation. User filters may narrow access only.
- Use `document_departments` as the source of truth for the many-to-many relationship
  between documents and departments. A document may be assigned to multiple departments.
- Editors create documents initially assigned to their own department and cannot modify
  department assignments. Only `tenant_admin` can assign, add, or remove departments.
  Document versions inherit the existing document's complete department set.
- A non-admin can access a document only when its department set intersects the user's
  permitted departments. Tenant admins may access all departments in their tenant.
- Update retrieval metadata when a tenant admin changes department assignments. If it
  cannot be synchronized, exclude the document from retrieval rather than risk stale,
  broader access.
- Never log document text, passwords, bearer tokens, API keys, or unredacted prompts.
  Propagate correlation IDs through API, jobs, workers, and structured logs.
- Production requires TLS, encrypted database/object storage and backups, and external
  secret configuration. Docker Compose relaxations are development-only.

## Implementation and verification rules

- Follow `docs/CODE_QUALITY.md` for typing, layering, documentation, errors, tests,
  coverage, and merge criteria.
- Use typed request/response/event models and explicit application errors. Do not pass
  untyped dictionaries across component boundaries.
- Add tests with every behavior change. Maintain at least 70% branch coverage in `src/`.
- Keep unit tests isolated; integration tests use the real Docker services; maintain an
  authenticated ingest-to-query end-to-end scenario, including a denied department case.
- Update configuration examples, API documentation, and operational instructions when
  a change affects them.
- Do not introduce secrets into tracked files. Keep dependency versions locked and
  preserve security scanning in CI.
