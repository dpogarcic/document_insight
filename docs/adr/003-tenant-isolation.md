# ADR 003: Enforce tenant isolation and authorization before retrieval

- **Status:** In Review
- **Date:** 2026-09-19
- **Decision owners:** Engineering

## Context

The platform serves internal customers whose documents may contain sensitive data. Similarity search and generated answers make post-retrieval filtering unsafe: an unauthorized passage must never be eligible for retrieval or supplied to the language model.

The assignment requires a single public API, authentication, per-user query rate limiting, tenant isolation, and encryption in transit and at rest. The first release needs a simple local identity implementation while preserving a migration path to an external identity provider.

## Decision

We will use locally managed users and signed access tokens for the exercise. Every request carries an authenticated user ID and tenant claim. The API validates the token, then refreshes the user's role and department memberships from PostgreSQL. Authorization is enforced in the API/gateway, represented as mandatory filters for every persistence and retrieval operation, and backed by PostgreSQL row-level security (RLS).

### Identity and authentication

- Public registration provisions a new tenant, a `General` department, and its initial `tenant_admin`. It does not accept an existing tenant ID or caller-selected role. Adding users to an existing tenant is reserved for a future administrator-controlled invitation flow.
- Users register and log in through the local authentication endpoints. Passwords are stored as salted Argon2 hashes; plaintext passwords are never logged or stored.
- Login issues a short-lived signed bearer token. Token signing material is supplied by secret configuration, not committed to the repository.
- A department is a tenant-scoped organizational access boundary, for example `legal`, `finance`, `human_resources`, or `customer_support`. Department names are configured per tenant; they are not global labels shared across tenants.
- Users can belong to multiple departments through the tenant-scoped `user_departments`
  association. A document can also be assigned to multiple departments through
  `document_departments`; its versions, chunks, entities, and embeddings inherit that
  department set for authorization. Both relationships are many-to-many and constrained
  to one tenant.
- The first release supports `tenant_admin`, `editor`, and `viewer` roles. A `tenant_admin` can manage users and access all departments in its tenant; an `editor` can ingest, replace, and query documents in their own department; a `viewer` can query documents in their own department only.
- Department scope is applied before `POST /query` retrieval. It also drives document-library UI grouping. Role permissions decide whether a user can create, view, or version a document; department scope decides which documents that permission can apply to.

### Department assignment and administration

- A new document's department set is determined during request authorization and persisted through `document_departments` when the document row is created, before the processing job is queued.
- When an `editor` creates a document, the API permits only a non-empty subset of the
  editor's own departments. If the editor omits a selection, all of their current
  departments are assigned. The editor cannot add or remove assignments later.
- A `tenant_admin` can select one or more departments within their tenant when creating a document, and is the only role allowed to add or remove department assignments later. Every change is audited with actor, timestamp, prior set, and new set.
- A replacement upload with an existing `document_id` inherits its logical document's full department set. Versioning cannot change department assignments.
- Department associations use a unique `(document_id, department_id)` key. Retrieval metadata keeps a synchronized department-set projection where required by the lexical/vector backend, while the relational association remains the authorization source of truth.
- An admin department-assignment change must update the relational policy and retrieval projection before the change is reported as successful. If synchronization cannot complete, the document is temporarily excluded from retrieval rather than evaluated with stale, broader access metadata.
- Local identity is a deliberate exercise-time choice. OAuth/OIDC integration is a future adapter, not a prerequisite for the initial delivery.

### Authorization order and retrieval scope

Authorization is resolved in this order:

1. Authenticate the user and validate the token.
2. Resolve the tenant from the authenticated identity, never from an untrusted request field.
3. Resolve the user's department memberships and role permissions. A `tenant_admin` may
   act on any department in the tenant; other users receive only their assigned department
   set.
4. Build an authorization scope containing the permitted tenant, departments, and roles/classifications. A non-admin document is eligible only when its department set intersects the user's permitted departments.
5. Apply that scope as a mandatory predicate to document metadata, SQL queries, vector search, lexical search, source lookup, and answer generation.

The optional user-supplied query `filter` is text for entity matching and lexical retrieval. It
never changes or overrides the tenant, department, role, or document-permission predicate.

### Data isolation and metadata

- PostgreSQL is shared for the initial release, with `tenant_id` on every tenant-owned row and foreign keys preserving tenant consistency.
- PostgreSQL RLS is enabled and forced for identity, document, version, job, passage, entity, index, and embedding tables. A protected read requires a transaction-local `app.user_id` and a current database membership. A missing or stale actor sees no protected document rows. The session layer sets this value at transaction start from a validated token; it is cleared at transaction end. The tenant and role are resolved from PostgreSQL, not trusted session variables or stale JWT department claims. Application retrieval queries still include explicit tenant and department predicates.
- Each service uses a dedicated database login. `di_api_read_login` can select authorized rows for library, job status, and `/query`; `di_api_write_login` handles ingest and version activation; `di_auth_login` handles registration, login, and current membership lookup without passage grants; `di_worker_login` accesses a single job and its version-scoped derived rows through transaction-local `app.job_id`; `di_reconciler_login` and `di_monitor_login` have only their operational table grants. Only the migration/bootstrap process receives the database owner credential.
- The migration creates non-login capability roles, disabled login roles, and a non-login RLS policy-owner role. Deployment supplies independent passwords and enables the logins after migration. The policy owner has `BYPASSRLS` solely so locked-search-path security-definer predicates can inspect the source-of-truth associations without policy recursion. It has no login capability. Role creation and `BYPASSRLS` require a database administrator during migration.
- Editors may insert initial `document_departments` associations only in the same transaction that inserts the document, for departments in their current membership. Later assignment changes require a tenant administrator. Versions inherit the document's existing associations.
- This decision keeps a shared PostgreSQL schema. Per-tenant schemas are not required to enforce the current isolation contract and would add migration and operations complexity without replacing role grants or RLS.
- The application database role can set PostgreSQL custom session variables. RLS therefore protects against missing application predicates and accidental cross-tenant queries, but arbitrary SQL execution under that role could forge `app.user_id` or `app.job_id`. Parameterized SQL, narrow database grants, secret handling, and SQL-injection prevention remain required. A future stronger database identity assertion would be needed if the threat model requires RLS to withstand arbitrary SQL execution using a compromised runtime credential.
- Object-storage keys are tenant and document-version scoped; object access is mediated by the application rather than exposed as broad public bucket access.
- Documents and indexed chunks carry authorization metadata: `tenant_id`, a synchronized department-set projection, allowed roles, document ID, version, validity/status, and any classification needed for policy enforcement. The `document_departments` association remains the source of truth for department policy.
- The vector/lexical retrieval query receives the same authorization metadata filter before scoring. It must not retrieve cross-tenant candidates and discard them later.

### Transport, encryption, and secrets

- Production traffic uses TLS from the public ingress/load balancer to the API. Internal service traffic is restricted to the private network; production deployments must use encrypted internal connections where the platform supports them.
- At-rest encryption is provided by the selected production database and object-storage platform, including backups. Object storage uses server-side encryption, and PostgreSQL data volumes use the managed service or host's encrypted-storage capability.
- Secrets, including token signing material and provider API keys, are supplied through environment-backed secret configuration locally and a managed secret store in production. They are never committed or logged.
- Docker Compose is a local-development environment. Any local relaxation of TLS or volume encryption is documented as development-only and must not be represented as production security.

### Abuse protection, privacy, and auditing

- An atomic Redis counter limits `POST /query` per authenticated tenant/user across API instances. The default is 30 requests in a 60-second window from the first request; `QUERY_RATE_LIMIT_REQUESTS` and `QUERY_RATE_LIMIT_WINDOW_SECONDS` configure it. The API checks quota before retrieval or provider calls, returns `429` with `Retry-After` when exhausted, and fails closed with `503` when Redis cannot be checked. This API quota is separate from retries after a model provider's `429` response.
- Each request receives a correlation ID propagated to the API, queued job, worker, database audit fields where useful, and structured logs.
- Logs record request lifecycle, authorization result, latency, status, and safe IDs. They must not contain raw document text, bearer tokens, passwords, or provider API keys.

## Acceptance criteria

- Requests without valid authorization cannot ingest, read job status, or query.
- A user cannot retrieve, cite, or infer content from another tenant or unauthorized department.
- Query filters cannot broaden the authenticated authorization scope.
- Query abuse is rate-limited per user and logs remain free of document content and credentials.
