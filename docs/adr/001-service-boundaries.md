# ADR 001: Define service boundaries around a document-insight workflow

- **Status:** In Review
- **Date:** 2026-09-19
- **Decision owners:** Engineering

## Context

The platform must ingest PDFs and images, make their content searchable, and answer questions over stored content. It must be straightforward to run locally and safe to extend without coupling HTTP request handling, document processing, data access, and AI-provider details.

The first release should demonstrate production-minded boundaries without prematurely splitting the system into independently deployed microservices.

## Decision

We will build a Python application with logical service boundaries. FastAPI will expose the public HTTP API; the API process and worker process may be deployed from the same codebase and container image with different commands.

### Public API

- `POST /ingest` accepts one PDF or image and an optional `document_id`. It validates the request and access context, stores the original, creates a processing job, and returns `202 Accepted` with a `document_id`, `document_version_id`, and `job_id`.
- `POST /query` accepts `question`, optional `filter`, and optional `top_k`. It applies authorization before retrieval and returns an answer, confidence, quoted sources, and detected entities.
- `POST /auth/register` and `POST /auth/login` support local users for the exercise. They are the only authentication endpoints in the first release.
- `GET /jobs/{job_id}` provides the status of an accepted upload.
- The API remains the only public entry point. Workers, PostgreSQL, Redis, and object storage are private Docker-network services.

### Logical components

| Component | Responsibility | Must not own |
| --- | --- | --- |
| API/gateway | Request validation, authentication, authorization, rate limiting, job creation, query orchestration | OCR, embedding, direct worker execution |
| Ingestion application service | Object creation, document and job records, idempotency orchestration, event publication | Text extraction or vector indexing |
| Processing worker | Parse/OCR, language detection, NER, chunking, embedding, indexing, job-state updates | User authentication and public HTTP handling |
| Query application service | Build the authorized retrieval request, call retrieval and generation providers, assemble cited response | Tenant-policy decisions or direct SQL in route handlers |
| Retrieval and AI provider layer | Stable interfaces for lexical retrieval, embedding, generation, reranking, and retrieval implementations | HTTP concerns or user identity interpretation |
| Persistence adapters | PostgreSQL/pgvector, Redis queue, and object-storage access behind explicit interfaces | Business policy |
| Observability stack | Scrape bounded metrics, collect structured container logs, and provide authenticated dashboards | Public API traffic, document text, authorization decisions |

### Technology baseline

- **FastAPI** provides the HTTP interface and OpenAPI contract.
- **PostgreSQL with pgvector** is the system of record for documents, versions, jobs, chunks, extracted entities, and vector embeddings.
- **S3-compatible object storage** holds immutable original files. MinIO is used for local development.
- **Redis and Redis Queue (RQ)** provide background-job delivery for the initial release. The queue implementation is isolated so it can later be replaced by a managed queue without changing the application services.
- **Docker Compose** starts the full local stack with one command.

### API and domain rules

- The initial upload maximum is 25 MiB per file. Content type, file signature, and size are validated before storage. The limit is configuration-backed, but production must not set it below 10 MiB.
- The document-library UI decides whether an upload is new or replaces an existing logical document. When it sends no `document_id`, the API creates a new document at version `v1`; when it sends an authorized `document_id`, the API creates that document's next version.
- A document is not queryable until its current version reaches `ready` status.
- Query source citations identify the document, version, page when available, and passage/chunk identifier so the caller can inspect the evidence.
- When the retrieved evidence is insufficient, the answer must explicitly say that the information is not available in the authorized documents. It must not invent an answer.
- Routes stay thin: request/response models and transport errors belong in FastAPI; business decisions belong in application services.

### Request tracing and correlation IDs

- Every HTTP request has one correlation ID. The API preserves an inbound
  `X-Correlation-ID` only when it is a valid UUID; otherwise it generates a new UUID so
  untrusted header values cannot enter logs.
- The selected value is stored on the request state and in a request-scoped context
  variable. Application and infrastructure code can therefore add logs without passing
  the correlation ID through every function signature.
- Every HTTP response includes the selected value in `X-Correlation-ID`, including safe
  error responses. A client can report this ID so operators can locate the corresponding
  request and exception logs.
- Every server log record includes a visible `correlation_id` field. Logs emitted during
  a request use its UUID; process startup and other work outside an HTTP request use `-`.
- The API emits a completion log containing correlation ID, method, path, response status,
  and duration. It does not log query strings, request bodies, credentials, or document
  content.
- Unexpected exceptions retain their traceback in server logs under the same correlation
  ID, while the HTTP response contains only a stable generic error and never the raw
  exception message.
- The API persists the originating correlation ID with the durable job. When queue
  processing is added, it must publish the same ID, and the worker must bind it to its
  logging context so ingestion can be traced across HTTP and asynchronous boundaries.

### Retrieval and AI providers

- Application code depends on provider protocols/interfaces rather than a specific SDK. Each adapter translates its provider's protocol and capabilities into the application's expected embedding, reranking, or generation contract.
- Configuration explicitly selects a supported implementation for each capability, for example `EMBEDDING_PROVIDER=mistral`, `RERANKER_PROVIDER=mistral`, or `GENERATION_PROVIDER=mistral`. A base URL and API key are runtime settings for the selected provider, not a mechanism for inferring its protocol.
- At startup, configuration is validated against the selected provider's required settings and supported capabilities. An embedding provider must have a known vector dimension; a reranker must support document-query ranking; and a generation provider must support the response format and citation prompt used by the application.
- Provider choices are independent. The first supported configuration uses Mistral Embed for embeddings and pinned Mistral Large 3 profiles for structured LLM reranking and generation. The generation and reranking adapters use the OpenAI Agents SDK's Chat Completions model shape against Mistral's API with tracing disabled; embeddings use a separate typed adapter because the Agents SDK is not an embeddings client.
- Retrieval is hybrid: the lexical and vector branches receive the same authorization filters, their oversampled candidates are fused with Reciprocal Rank Fusion (RRF), and a reranker orders the final candidates before applying `top_k`.
- The intended lexical implementation is a PostgreSQL extension/service that provides true BM25 alongside pgvector. `pg_search` is the leading candidate because it provides BM25 and integrates with pgvector; its deployment and AGPL licensing must be confirmed before adoption. PostgreSQL full-text search is an acceptable temporary lexical fallback, but it must not be described as BM25.
- NER is metadata enrichment, not lexical search. It extracts structured people,
  organizations, geopolitical entities, locations, products, events, and dates from
  extracted text.
- `confidence` is an evidence-confidence score in the range `0.0` to `1.0`, not an LLM self-assessment. It is derived from a calibrated reranker/retrieval score for the cited evidence, with an explicit insufficient-evidence threshold. The score must be calibrated and evaluated on a labelled test set before it is presented as probabilistic confidence.
- Provider adapters translate implementation-specific errors into application errors such as unavailable, rate-limited, invalid request, or retryable failure. Prompts, model names, reranker version, index generation, and retrieval configuration are versioned with evaluation runs.

### Entity metadata and document selection

- NER enriches document selection only. It may identify or softly boost relevant authorized
  document versions before chunk retrieval; it must not select passages, produce citations,
  or replace lexical retrieval, vector retrieval, RRF, or reranking.
- An entity is a canonical document-version fact, not an occurrence record. Persist one row
  for each unique `(document_version_id, label, normalized_value)` combination. Repeated
  mentions increase `occurrence_count` on that row rather than creating duplicate rows.
- Canonical entity records retain a display value, canonical label, normalized value,
  occurrence count, detected language, and NER provider/model provenance. Source character
  offsets are deliberately not persisted: chunks and their citations provide passage-level
  grounding.
- Query-time entity extraction may add eligible document versions to the candidate set or
  apply a modest document-level boost. It is a recall aid, never a mandatory filter, because
  NER can miss entities or classify them incorrectly. Tenant and department authorization
  filters apply before entity matching just as they do before lexical and vector retrieval.

## Acceptance criteria

- The complete stack starts through Docker Compose and exposes only the API publicly.
- Uploading a valid file creates a document and a job without blocking on processing.
- A ready, authorized document can be queried through `POST /query` with traceable source citations.
- Component interfaces can be replaced by fakes in unit tests.
- A client-reported response correlation ID identifies the matching request logs and any
  associated exception traceback without exposing internal error details.
