# Security Policy

## Reporting a vulnerability

Do not report suspected vulnerabilities in a public issue, pull request, discussion, or
chat message. Report them privately to the repository owner through an agreed private
channel. If GitHub private vulnerability reporting is enabled for this repository, use
that channel instead.

Please include:

- a clear description of the issue and its potential impact;
- affected component, version, or commit;
- safe reproduction steps or a minimal proof of concept;
- any suggested mitigation; and
- whether the issue could expose tenant data, document content, credentials, or service
availability.

Do not include real customer documents, passwords, bearer tokens, API keys, or other
secrets in a report.

## Security priorities

The following areas require especially careful review:

- tenant and department authorization before lexical search, vector search, source
  lookup, and generation;
- document-version and retrieval-metadata synchronization;
- authentication, password handling, token signing, and rate limiting;
- file-upload validation, object-storage access, and processing jobs;
- secret handling, logs, prompts, traces, backups, and error responses; and
- provider adapters and data sent to external model services.

## Scope

The policy applies to application code, infrastructure configuration, CI/CD workflows,
dependencies, documentation that exposes operational details, and local-development
tooling distributed by this repository.

## Disclosure and remediation

The maintainer will assess reports privately, prioritize issues that risk data exposure
or cross-tenant access, and coordinate a fix before public disclosure. Contributors
must not publish exploit details until the repository owner agrees that remediation is
available.

## Development safeguards

- Never commit secrets or real internal documents.
- Use synthetic, sanitized fixtures for tests and demonstrations.
- Run the configured pre-commit hooks and CI checks before merging changes.
- Treat authorization failures and unexpected cross-tenant/department visibility as
  security defects, not ordinary product bugs.
