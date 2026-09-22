# ADR 004: Version and explicitly activate AI capability configurations

- **Status:** In Review
- **Date:** 2026-09-21
- **Decision owners:** Engineering

## Context

Chunking, lexical indexing, embeddings, reranking, and generation each depend on model
and behavior configuration. A deployment must be able to add support for a new provider
or model without silently changing processing or query behavior. In particular, vectors
created by different embedding configurations are not comparable, while reranker and
generation changes affect only new query executions.

Retrying a job must use the same configuration as its first attempt, even if an operator
activates a newer configuration in the meantime. The platform also needs an auditable,
atomic way to move from a capability version such as a reranker `v1` to `v2`.

## Decision

We will separate runtime deployment settings from explicitly enabled capability profiles.
Environment-backed configuration provides supported adapters, endpoints, secrets, and
resource limits; profiles contain no endpoint URL, API key, secret reference, or connection
record. Runtime settings do not select the configuration used by a job or query. Only an
active profile pointer stored in PostgreSQL may do that.

### Immutable configuration model

- A `configuration_snapshot` stores one canonical, non-secret JSON configuration, its
  schema version, and a SHA-256 fingerprint. It is immutable and unique by capability and
  fingerprint.
- A `capability_profile` is an immutable named version of one capability and points to one
  snapshot. Its capability is one of `ner`, `chunking`, `lexical`, `embedding`,
  `reranking`, or `generation`.
- Snapshots include every application-level setting that changes observable behavior.
  Examples include chunk size and overlap; lexical analyzer and ranking configuration;
  explicit provider key, model identifier, configuration revision, vector dimension,
  normalization, and prefixes for embeddings; and model, input limit, and
  score-normalization policy for reranking.
- URLs, secrets, bearer tokens, API keys, passwords, secret identifiers, and connection
  references never appear in snapshots or their fingerprints. An adapter resolves its
  provider-specific endpoint and credentials from runtime settings using the profile's
  explicit provider key.
- A capability profile's configuration revision is immutable. A mutable model reference
  such as `latest` is not an acceptable value within that immutable configuration.

### Runtime bundles and active selection

- An immutable `ingestion_profile` bundles the NER, chunking, lexical, and embedding
  profiles used to create an index generation for new uploads.
- An immutable `query_profile` bundles lexical and embedding read cohorts, one reranker,
  one generation profile, and retrieval settings such as candidate limits, RRF constant,
  insufficient-evidence threshold, and minimum citation score. These thresholds determine
  whether generation is permitted and which reranked passages can be provided as evidence.
- `active_profiles` stores the active ingestion and query profile pointers for a scope
  (initially platform-wide). It includes a monotonic revision for optimistic concurrency.
  `profile_activations` is append-only audit history containing the actor, time, prior
  profile, new profile, and activation reason.
- A job is assigned its ingestion profile and target index generation when it is created.
  Worker retries resolve those persisted identifiers, never current environment variables
  or a newly active profile.
- A query resolves exactly one active query profile at request start and carries that
  identifier through retrieval, reranking, generation, logging, and later evaluation/audit
  records. An activation during a request affects only later requests.

### Persistence model

| Record | Required identity and relationship fields |
| --- | --- |
| `configuration_snapshots` | `id`, `capability`, `schema_version`, `fingerprint`, immutable `configuration_json`, `created_at`; unique `(capability, fingerprint)` |
| `capability_profiles` | `id`, `capability`, `configuration_snapshot_id`, `status`, `created_at`; immutable after creation |
| `ingestion_profiles` | `id`, `ner_profile_id`, `chunking_profile_id`, `lexical_profile_id`, `embedding_profile_id` |
| `query_profiles` | `id`, enabled lexical/embedding read cohorts, `reranker_profile_id`, `generation_profile_id`, retrieval-settings snapshot |
| `active_profiles` | `scope`, `profile_kind` (`ingestion` or `query`), `profile_id`, monotonic `revision`, `updated_at`; unique `(scope, profile_kind)` |
| `profile_activations` | `id`, scope, prior and new profile IDs, actor, reason, time, and active-profile revision |
| `index_generations` | `id`, `document_version_id`, `ingestion_profile_id`, state, lifecycle timestamps |
| `processing_jobs` | target `ingestion_profile_id` and `index_generation_id`, fixed at job creation |
| `chunks` | `id`, `index_generation_id`, version-local ordinal, source/provenance fields; unique `(index_generation_id, ordinal)` |
| `chunk_embeddings` | `chunk_id`, `embedding_profile_id`, vector; unique `(chunk_id, embedding_profile_id)` |

The initial migration creates these profile, generation, and embedding provenance records.
The processing worker assigns an ingestion profile and index generation at upload time, then
resolves persisted NER, chunking, and embedding snapshots when it processes the job. Mistral
supplies cloud embeddings; the snapshot records its model identifier, configuration revision,
dimensions, normalization, and batch size. Mistral chat models are selected independently for
structured LLM reranking and grounded generation, whose snapshots also record prompt,
response-schema, temperature, and output-token revisions. The OpenAI Agents SDK is used only
for those chat tasks with tracing disabled, so document passages are not exported to tracing.

### Index generations and compatibility

- An `index_generation` belongs to one document version and one ingestion profile. It is
  `building`, `ready`, `failed`, or `superseded`.
- Chunks belong to an index generation and have a unique
  `(index_generation_id, ordinal)` key. Their immutable chunking and lexical configuration
  provenance is obtained through the generation's ingestion profile; chunks carry no
  duplicated chunker name or version fields.
- Chunk embeddings record their embedding profile and are unique by
  `(chunk_id, embedding_profile_id)`. A vector query may search only vectors created by
  the same embedding profile used to create that query vector. The embedding-profile
  foreign key is authoritative even when the embedding belongs to a chunk whose index
  generation used a different ingestion profile during a later re-embedding operation.
- A query profile explicitly lists its lexical and embedding read cohorts. For each
  embedding cohort, the query service creates a compatible query vector and searches only
  that cohort. It fuses ranked results with RRF rather than comparing raw scores across
  embedding spaces. The selected reranker may score candidates from all compatible
  cohorts because it consumes chunk text, not vectors.
- Tenant and department authorization predicates remain mandatory before every lexical or
  vector candidate is scored, as specified in ADR 003.

### Explicit activation

1. An operator creates a new immutable snapshot and capability profile in `draft` state.
2. The platform validates that the deployed application supports the profile's adapter,
   that required runtime secrets/settings are available, and that the profile's declared
   capabilities are compatible with its use.
3. The operator creates and validates a new ingestion or query profile that references the
   new capability profile.
4. In one transaction, the platform locks the appropriate active-profile pointer, checks
   its expected revision, changes it to the new bundle, increments the revision, and writes
   an activation audit record.

Deploying a container that supports a new profile does not activate it. A reranker or
generation profile may switch live without a new deployment when the already deployed
application supports its adapter and has its required runtime configuration. If an adapter
or dependency is new, deploy support first while retaining the old active profile, then
activate it explicitly.

### Effect of capability changes

| Changed capability | Activation effect |
| --- | --- |
| Chunking | New uploads use a new ingestion profile and index generation; existing generations remain readable until separately migrated. |
| Lexical indexing | New uploads build the selected lexical generation; queries search only explicitly enabled read cohorts. |
| Embedding | New uploads embed with the new profile. Queries create a query vector per enabled embedding cohort and never compare incompatible vector spaces directly. |
| Reranking | A new query profile selects the new reranker for subsequent queries; no document-derived data changes. |
| Generation | A new query profile selects the new model/prompt behavior for subsequent queries; no document-derived data changes. |

Backfilling and retiring legacy cohorts are separate operational work. This ADR only
requires that legacy profiles remain readable while referenced by ready index generations,
and that they are removed from query read cohorts only through another explicit,
audited activation.

### Current implementation transition

Chunks now reference `index_generation_id`. Processing jobs resolve NER, chunking, and
embedding configuration solely through their persisted ingestion profile. The worker stores vectors in
`chunk_embeddings` under the exact `embedding_profile_id`, then marks the generation's
embedding checkpoint complete. No runtime endpoint configuration can substitute for that
foreign key.

## Consequences

- New deployments cannot silently change RAG behavior or invalidate retry reproducibility.
- The platform can run multiple embedding and lexical cohorts during a transition, at the
  cost of extra query embedding/search work until legacy cohorts are retired.
- Every answer and derived artifact can be traced to exact immutable configuration.
- Activation requires an administrative/operational control plane, which is planned but
  not implemented in the current processing slice.

## Acceptance criteria

- Changing an environment variable alone cannot change the profile used by a new job or
  query.
- A retried job uses its originally persisted ingestion profile and index generation.
- An embedding query never searches vectors from a different embedding profile with its
  query vector.
- A successful reranker or generation activation changes only subsequently started
  queries, atomically and with an audit record.
- New configuration support may be deployed independently from its explicit activation.
