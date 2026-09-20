# Code Quality Standards

- **Status:** In Review
- **Applies to:** Python application code, tests, migrations, scripts, and CI configuration
- **Purpose:** Keep the platform understandable, safe to change, and demonstrably reliable from its first release.

## Baseline

- Core services are written in Python 3.13 or later.
- Code is formatted with Ruff. Formatting is not a review discussion.
- Ruff linting runs in CI with project rules enabled.
- Mypy runs in strict mode for application modules. Third-party typing gaps are isolated at adapter boundaries rather than allowed to spread through business logic.
- CI fails when formatting, linting, type checking, security scanning, or required tests fail.

## Types and interfaces

- Every function and method has parameter and return type annotations. Use `None` explicitly for procedures with no return value.
- Public request, response, persistence, and event schemas use explicit typed models. Do not pass untyped dictionaries across application boundaries.
- Use application types, enums, and value objects for important concepts such as IDs, job states, document versions, roles, and provider configuration.
- Use `Protocol` interfaces for external capabilities, including object storage, queue delivery, OCR, embeddings, reranking, generation, and retrieval. Application services depend on those protocols, not vendor SDKs.
- `Any`, `cast`, and `# type: ignore` require a narrow justification and must not mask application errors.
- Keep framework models and ORM entities at the transport/persistence edge. Convert them into application models before business logic uses them.

## Structure and readability

- Keep HTTP routes thin: validate transport input, call one application service, and map expected application errors to HTTP responses.
- Separate API routes, application services and models, persistence adapters, and provider adapters. Avoid circular imports and cross-layer database access.
- Keep models with their owning application feature; do not introduce a separate `domain/`
  layer in this project.
- Use one repository per persisted entity or association. Coordinate cross-entity writes
  in an application service under an explicit shared transaction; do not let one
  repository mutate another repository's records.
- Keep each repository protocol, implementation, and ORM model together under
  `infrastructure/<entity>/`, with the concrete adapter explicitly implementing the local
  protocol. Keep only shared database plumbing in `infrastructure/database/`.
- Name SQLAlchemy persistence classes `<Entity>Model`. Name HTTP input schemas
  `<Operation>Request`; name HTTP responses and their nested payload schemas
  `<Concept>DTO`. Avoid redundant names such as `UserResponseDTO`; use `UserDTO`.
- Split security capabilities under `infrastructure/security/`. Co-locate each capability
  protocol with its explicitly implementing adapter instead of grouping unrelated token
  and password behavior in one module.
- Put application use-case inputs in focused `commands.py` modules. Put persistence
  creation data beside the owning infrastructure protocol. Avoid generic `contracts.py`
  modules that mix commands, persistence payloads, and infrastructure interfaces.
- Prefer small, single-purpose functions. When a function needs several unrelated responsibilities, extract a named collaborator.
- Prefer clear control flow over clever abstractions. Names must describe the business purpose rather than the implementation detail.
- Avoid hidden side effects. File writes, database writes, queue publication, network calls, and time-dependent behavior must be visible in a function's dependencies or return contract.
- Use configuration objects validated at startup. Application code must not read environment variables directly outside the configuration layer.

## Documentation and comments

- Public modules, classes, and non-trivial public functions require meaningful docstrings that describe purpose, important inputs/outputs, and observable failure behavior where useful.
- Comments explain intent, constraints, security reasoning, or non-obvious trade-offs; they do not restate code.
- Every externally visible API behavior, configuration option, and operational decision belongs in the relevant README, architecture document, or ADR.
- Update an ADR when changing an accepted architectural decision. Update the architecture document when changing component boundaries, data flow, or security flow.

## Errors, logging, and security

- Raise and handle explicit application errors. Do not catch broad `Exception` unless the boundary re-raises a safe, typed error and records the cause.
- API error responses are stable, actionable, and free of document content, credentials, infrastructure details, or stack traces.
- Structured logs include correlation ID, safe resource IDs, operation, outcome, and latency where relevant. Never log raw document text, bearer tokens, passwords, API keys, or unredacted prompts.
- Validate untrusted input at the boundary: file signature and size, request schemas, identifiers, filter values, and provider responses.
- Authorization scope is mandatory before every document, chunk, lexical, vector, source, or generation operation. User input may narrow that scope but never broaden it.
- Dependencies are pinned through the project lockfile and checked for known vulnerabilities in CI.

## Testing standards

### Test pyramid

- **Unit tests:** Test domain rules and application services in isolation. Use fakes for time, storage, queues, repositories, and model providers; they must not require network access or Docker.
- **Integration tests:** Exercise real service boundaries through Docker Compose, including PostgreSQL/search extensions, Redis/RQ, and object storage.
- **End-to-end test:** Cover an authenticated upload, successful background processing, and an authorized query with cited sources. Include at least one tenant/department denial case.

### Coverage and test quality

- The `src/` application package must maintain at least **70% branch coverage**. CI enforces the threshold with `pytest --cov=src --cov-branch --cov-fail-under=70`.
- New or materially changed business logic requires focused unit tests for its success path, expected failures, authorization behavior, and retry/idempotency behavior where applicable.
- Tests state observable behavior, not internal implementation details. Prefer fakes at provider boundaries over mocks of private methods.
- Tests must be deterministic: no real model providers, uncontrolled clocks, random values, network calls, or dependency on test order.
- Regression bugs require a failing test before or together with the fix.

## Review and merge criteria

A change is ready to merge when:

- formatting, linting, type checks, tests, coverage, and security checks pass;
- public behavior and configuration are documented;
- security-sensitive changes include authorization and negative-path tests;
- migrations are reversible or have a documented recovery plan;
- the change does not introduce secrets, sensitive logs, unchecked inputs, or cross-tenant/department access paths; and
- a reviewer can understand the intent without relying on unstated context.

## Exceptions

An exception to this standard must be narrow, documented in the pull request, and include a follow-up issue or ADR when it affects architecture, security, or operational reliability. Exceptions do not lower the CI coverage threshold or bypass security controls.

## Initial enforcement commands

The repository will expose these commands as implementation begins:

```text
make format-check   # Ruff formatting check
make lint           # Ruff linting and Mypy strict checks
make test           # Unit tests with branch coverage
make test-integration
make test-e2e
make quality        # All required local quality checks
```
