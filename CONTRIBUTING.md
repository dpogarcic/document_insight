# Contributing

Thank you for contributing to Document Insight Platform. This project handles sensitive
documents, so correctness, tenant isolation, and evidence-grounded behavior matter as
much as feature delivery.

## Shared expectations

- Read [README.md](README.md), [AGENTS.md](AGENTS.md), and
  [docs/CODE_QUALITY.md](docs/CODE_QUALITY.md) before starting implementation work.
- Treat the architecture and ADRs as the current implementation contract. Raise a
  design conflict before changing a documented decision.
- Keep each change focused. Include tests and documentation changes in the same pull
  request when behavior, configuration, security, or operations change.
- Do not commit secrets, private documents, sample customer data, or logs containing
  sensitive content.
- Use the pull-request template and explain authorization, versioning, migration, and
  provider impact where relevant.

## For people

### Local workflow

1. Create a focused branch from the current default branch.
2. Install the development toolchain and the repository hooks:

   ```bash
   uv sync --group dev
   uv run pre-commit install
   ```

3. Make the smallest coherent change that solves the problem.
4. Run the relevant checks before opening a pull request. As implementation progresses,
   these commands will be available:

   ```bash
   make lint
   make test
   make test-integration
   make test-e2e
   ```

5. Open a pull request using the provided template. Respond to review feedback with
   code, tests, or a documented design decision rather than an undocumented workaround.

### Review expectations

Reviewers verify that changes preserve tenant and department isolation, protect document
content and credentials, maintain versioning semantics, and produce evidence-grounded
query behavior. Database migrations need a rollback or recovery plan. Changes to
architecture, authorization, provider contracts, or operations require documentation
updates.

## For AI coding agents

AI coding agents must follow [AGENTS.md](AGENTS.md) before inspecting or modifying code.

- Read the architecture, all three ADRs, and the code-quality standards before making a
  plan or implementation change.
- Treat direct user instructions as authoritative. If they conflict with the existing
  design, explain the conflict and request or record a decision instead of silently
  choosing a different architecture.
- Preserve uncommitted work that is unrelated to the requested change. Do not reset,
  overwrite, or delete user changes without explicit permission.
- Make typed, tested, narrowly scoped changes. Run the relevant quality checks and
  report what was verified.
- Update the appropriate README, architecture document, ADR, configuration example, or
  test when a change affects documented behavior.
- Never place secrets, real document content, access tokens, or sensitive logs in code,
  fixtures, prompts, commits, or responses.
- Do not add optional stretch features, introduce a new provider/backend, or alter
  tenant/department authorization without explicit approval.

## Questions and design changes

Use an ADR update when a decision changes service boundaries, async processing,
versioning, provider selection, retrieval, tenancy, departments, or security. Use the
architecture document for system diagrams, data flow, deployment position, and
cross-component trade-offs.
