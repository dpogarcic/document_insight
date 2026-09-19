# ADR 003: Enforce tenant isolation and authorization before retrieval

- **Status:** In Review
- **Date:** 2026-09-19
- **Decision owners:** Engineering

## Context

The platform serves internal customers whose documents may contain sensitive data. Similarity search and generated answers make post-retrieval filtering unsafe: an unauthorized passage must never be eligible for retrieval or supplied to the language model.

The assignment requires a single public API, authentication, per-user query rate limiting, tenant isolation, and encryption in transit and at rest. The first release needs a simple local identity implementation while preserving a migration path to an external identity provider.

## Decision

We will use locally managed users and signed access tokens for the exercise. Every request carries an authenticated identity with `tenant_id`, user ID, role, and department claims. Authorization is enforced in the API/gateway and represented as mandatory filters for every persistence and retrieval operation.

### Identity and authentication

- Public registration provisions a new tenant, a `General` department, and its initial `tenant_admin`. It does not accept an existing tenant ID or caller-selected role. Adding users to an existing tenant is reserved for a future administrator-controlled invitation flow.
- Users register and log in through the local authentication endpoints. Passwords are stored as salted Argon2 hashes; plaintext passwords are never logged or stored.
- Login issues a short-lived signed bearer token. Token signing material is supplied by secret configuration, not committed to the repository.
- A department is a tenant-scoped organizational access boundary, for example `legal`, `finance`, `human_resources`, or `customer_support`. Department names are configured per tenant; they are not global labels shared across tenants.
- Every non-admin user has one department membership in the first release. A document can be assigned to multiple departments through a `document_departments` association; its versions, chunks, entities, and embeddings inherit that department set for authorization. A department can contain many documents, so this is a many-to-many relationship.
- The first release supports `tenant_admin`, `editor`, and `viewer` roles. A `tenant_admin` can manage users and access all departments in its tenant; an `editor` can ingest, replace, and query documents in their own department; a `viewer` can query documents in their own department only.
- Department scope is applied before `POST /query` retrieval. It also drives document-library UI grouping. Role permissions decide whether a user can create, view, or version a document; department scope decides which documents that permission can apply to.

### Department assignment and administration

- A new document's department set is determined during request authorization and persisted through `document_departments` when the document row is created, before the processing job is queued.
- When an `editor` creates a document, the API automatically assigns the editor's own department as its initial department. The editor cannot select, add, or remove departments.
- A `tenant_admin` can select one or more departments within their tenant when creating a document, and is the only role allowed to add or remove department assignments later. Every change is audited with actor, timestamp, prior set, and new set.
- A replacement upload with an existing `document_id` inherits its logical document's full department set. Versioning cannot change department assignments.
- Department associations use a unique `(document_id, department_id)` key. Retrieval metadata keeps a synchronized department-set projection where required by the lexical/vector backend, while the relational association remains the authorization source of truth.
- An admin department-assignment change must update the relational policy and retrieval projection before the change is reported as successful. If synchronization cannot complete, the document is temporarily excluded from retrieval rather than evaluated with stale, broader access metadata.
- Local identity is a deliberate exercise-time choice. OAuth/OIDC integration is a future adapter, not a prerequisite for the initial delivery.

### Authorization order and retrieval scope

Authorization is resolved in this order:

1. Authenticate the user and validate the token.
2. Resolve the tenant from the authenticated identity, never from an untrusted request field.
3. Resolve the user's department and role permissions. A `tenant_admin` receives all departments in the tenant; other users receive only their assigned department.
4. Build an authorization scope containing the permitted tenant, departments, and roles/classifications. A non-admin document is eligible only when its department set intersects the user's permitted departments.
5. Apply that scope as a mandatory predicate to document metadata, SQL queries, vector search, lexical search, source lookup, and answer generation.

User-supplied query filters can only narrow this scope. They can never broaden it or override the tenant, department, role, or document-permission predicate.

### Data isolation and metadata

- PostgreSQL is shared for the initial release, with `tenant_id` on every tenant-owned row and foreign keys preserving tenant consistency.
- PostgreSQL Row-Level Security (RLS) is enabled for tenant-owned tables as defense in depth. Application queries still include the tenant predicate explicitly.
- Object-storage keys are tenant and document-version scoped; object access is mediated by the application rather than exposed as broad public bucket access.
- Documents and indexed chunks carry authorization metadata: `tenant_id`, a synchronized department-set projection, allowed roles, document ID, version, validity/status, and any classification needed for policy enforcement. The `document_departments` association remains the source of truth for department policy.
- The vector/lexical retrieval query receives the same authorization metadata filter before scoring. It must not retrieve cross-tenant candidates and discard them later.

### Transport, encryption, and secrets

- Production traffic uses TLS from the public ingress/load balancer to the API. Internal service traffic is restricted to the private network; production deployments must use encrypted internal connections where the platform supports them.
- At-rest encryption is provided by the selected production database and object-storage platform, including backups. Object storage uses server-side encryption, and PostgreSQL data volumes use the managed service or host's encrypted-storage capability.
- Secrets, including token signing material and provider API keys, are supplied through environment-backed secret configuration locally and a managed secret store in production. They are never committed or logged.
- Docker Compose is a local-development environment. Any local relaxation of TLS or volume encryption is documented as development-only and must not be represented as production security.

### Abuse protection, privacy, and auditing

- A default per-user rate limit protects `POST /query`; limits are configurable and return a clear `429` response when exceeded.
- Each request receives a correlation ID propagated to the API, queued job, worker, database audit fields where useful, and structured logs.
- Logs record request lifecycle, authorization result, latency, status, and safe IDs. They must not contain raw document text, bearer tokens, passwords, or provider API keys.

## Acceptance criteria

- Requests without valid authorization cannot ingest, read job status, or query.
- A user cannot retrieve, cite, or infer content from another tenant or unauthorized department.
- Query filters cannot broaden the authenticated authorization scope.
- Query abuse is rate-limited per user and logs remain free of document content and credentials.
