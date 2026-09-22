# ADR 002: Process document versions asynchronously with durable, idempotent jobs

- **Status:** In Review
- **Date:** 2026-09-19
- **Decision owners:** Engineering

## Context

PDF parsing, OCR, entity extraction, embedding, and indexing can take substantially longer than an HTTP request. They may fail due to malformed input, a transient model-provider failure, or worker interruption. Retrying must not create duplicate chunks, embeddings, or document versions.

The platform also needs users to observe the status of an accepted upload without exposing worker internals.

## Decision

We will accept uploads quickly and process each immutable document version through a durable background job. Redis Queue (RQ) delivers jobs, while PostgreSQL holds the authoritative job and processing state.

### Current implementation checkpoint

- The API stores the original, then creates the document version and its single processing
  job atomically in PostgreSQL. The job receives server-generated job and idempotency IDs,
  the originating correlation ID, `attempt_count=0`, and `status=queued`.
- The API publishes only the durable job ID and correlation ID to RQ, then records
  `enqueued_at`. `POST /ingest` returns `202` only after that publication succeeds.
- The RQ worker parses/OCRs originals, detects English or Croatian, and persists local
  spaCy NER results under `document_version_id`. Parsing and NER completion are durable
  checkpoints, including successful NER runs that find zero entities.
- NER persistence is restricted to the canonical RAG metadata allowlist: `PERSON`,
  `ORG`, `GPE`, `LOC`, `PRODUCT`, `EVENT`, and `DATE`. Provider-specific equivalent
  labels are normalized before persistence; all other labels are discarded.
- NER stores canonical document-version entities, not one row per textual mention. A unique
  `(document_version_id, label, normalized_value)` row tracks repeated mentions through an
  `occurrence_count`; source offsets are not retained because chunks own passage citations.
- The worker produces deterministic, page-aware chunks under `document_version_id`.
  Each chunk has a version-local ordinal, text, page number, and exact character offsets;
  PostgreSQL generates a `simple` full-text index for the chunk text. The chunks and
  checkpoint are committed together, making RQ retries idempotent. This is a temporary
  lexical index, not BM25.
- The worker batches chunks through the configured Mistral embedding adapter,
  validates the profile-declared vector dimension, and stores vectors with their exact
  profile-bound index generation. It then marks the version, index generation, and job
  `ready`; activation remains a deliberately separate tenant-admin operation.
- Authenticated callers can read `GET /jobs/{job_id}` only through their tenant and current
  document-department scope. Missing and unauthorized jobs both return `404`.

### Upload and processing flow

1. Validate the caller, file size, MIME type, and file signature.
2. If the upload includes an existing `document_id`, authorize access to that logical document and atomically allocate its next version number. Otherwise, create a new logical document at version `v1`.
3. Write the original synchronously to a tenant-scoped, versioned object key. File storage is part of the upload request, not worker work.
4. In one database transaction, create the document version and a `queued` processing job that references the stored object. Generate a unique, server-managed job ID and idempotency key for that job.
5. Enqueue the job in RQ. The API returns `202 Accepted` only after the job has been accepted by the queue; the response contains the document, version, and job identifiers.
6. A worker moves the job to `processing`, extracts text (PDF parser first, OCR where required), detects language, extracts entities, chunks the content, and indexes the chunks.
7. The worker writes all derived data under the document-version identifier and marks the version/job `ready` only after the complete index is available.
8. On an unrecoverable error, the worker records a safe error code and marks the job `failed`; it never exposes document content or secrets in the status message.

### Job and document states

- Job states: `queued`, `processing`, `ready`, `failed`, and `cancelled`.
- A document version is eligible for activation only in `ready` state. Default retrieval
  uses only the document's explicitly activated current version.
- Failed jobs are retryable only when their failure is classified as transient or when an operator explicitly requests a retry.
- The API exposes job status through `GET /jobs/{job_id}`.

### Idempotency, retries, and recovery

- Idempotency is server-managed. Every processing job has a generated unique ID and internal idempotency key.
- The system stores a SHA-256 content digest as provenance. A repeated upload is still a new version when the document-library UI supplies the document ID; the digest may later support safe processing optimization, but it does not alter versioning semantics.
- Each worker step is retry-safe. Derived rows use unique keys containing `document_version_id`, chunk ordinal, and the embedding/index configuration version.
- Workers use bounded retries with exponential backoff for retryable dependencies. Attempts, timestamps, error category, and correlation ID are persisted.
- A periodic reconciliation process uses PostgreSQL as the source of truth to republish
  unqueued or stale queued work, recover stale `processing` jobs within their retry budget,
  and requeue only transient failed jobs. It marks stale jobs that exhausted their retry
  budget as terminal failures. Queue delivery is idempotent: the worker claims only
  `queued` jobs, so duplicate Redis messages cannot run the same job concurrently.
- If synchronous object storage succeeds but the database transaction fails, the API attempts immediate object deletion and records the key for reconciliation if deletion fails. If RQ is unavailable after the job is committed, the job remains durable as `queued`, a reconciliation process republishes it, and the API returns a retryable error rather than a successful acceptance response.

### Versioning and provenance

- Original files are immutable. The document-library UI creates a replacement by supplying the existing document ID; the API creates its next document version rather than overwriting the previous source or index. Uploads without a document ID create a separate document at `v1`.
- Every derived chunk records its source page or image region when available, extractor version, language, and processing timestamp.
- Every embedding records the profile-bound embedding configuration, vector dimension, and index generation.
- Existing vectors are incompatible with an embedding model or dimension change. A configuration change therefore creates a new index generation and triggers a controlled reindex; vectors from different generations are never compared together.

### Current-version activation

- A logical document has a `current_ready_version_id` pointer. Uploading `v2` does not change the pointer while `v2` is queued, processing, or merely `ready`; the existing current version remains searchable.
- When a version becomes `ready`, the worker updates only its own state and the index-generation/job checkpoints. It never updates `current_ready_version_id`.
- `POST /documents/{document_id}/activate` is a tenant-admin-only action. It locks the
  logical document, verifies that the selected version is ready and belongs to that document,
  then atomically updates `current_ready_version_id`. That action is deliberately separate
  from ingestion and processing.
- A failed or cancelled version is never eligible for activation. Previous versions remain immutable for audit and can be exposed through an explicit historical-version feature later, but default retrieval uses only `current_ready_version_id`.
- Chunks, entities, embeddings, and citations are scoped to `document_version_id`. Chunk ordinals are unique only within a version and chunking configuration, so identical ordinal values across versions cannot clash.

## Acceptance criteria

- The ingest endpoint returns before OCR or embedding starts and supplies a job ID.
- Retrying the same job does not create duplicate indexed chunks.
- A worker failure leaves a durable, inspectable status and can safely resume or retry.
- A document becomes eligible for explicit activation only after all required derived
  records are committed; it becomes searchable only once that activation succeeds.
